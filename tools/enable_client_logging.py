#!/usr/bin/env python3
"""Enable managed Unity logs in the supplied PK XD 1.38.4 ARM64 library.

Creates a separate library for replacement with the same APK editor/signing key
already used for the local client. Does not install, sign or uninstall the app.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zipfile

PACKAGE = "com.movile.playkids.pkxd"
LIB_ENTRY = "lib/arm64-v8a/libil2cpp.so"
LIB_SIZE = 91868752
ORIGINAL_SHA = "32e8e598619d9ff1136a184b39b0c93b19a461b56ef612bb56871072765e6fbe"
ENABLED_SHA = "39251a034d833e74e48797eed3b608732d7a952f9dafdc55b1a5ef48e964856e"
PATCH_OFFSET = 0x2738E8C
ORIGINAL_BYTES = bytes.fromhex("e1031f2a")  # mov w1, wzr: logEnabled=false
ENABLED_BYTES = bytes.fromhex("21008052")   # mov w1, #1: logEnabled=true


def transform(data, *, restore=False):
    if len(data) != LIB_SIZE:
        raise ValueError("Tamanho de lib diferente da build ARM64 estudada. Nenhum patch foi aplicado.")
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("A biblioteca precisa ser ELF64 little-endian AArch64.")
    digest = hashlib.sha256(data).hexdigest()
    if digest not in (ORIGINAL_SHA, ENABLED_SHA):
        raise ValueError(f"SHA-256 da lib não corresponde à build estudada: {digest}. Nenhum patch foi aplicado.")
    source_bytes = ENABLED_BYTES if digest == ENABLED_SHA else ORIGINAL_BYTES
    if data[PATCH_OFFSET:PATCH_OFFSET + 4] != source_bytes:
        raise ValueError("Instrução original inesperada. Nenhum patch foi aplicado.")
    desired_bytes, desired_sha = (ORIGINAL_BYTES, ORIGINAL_SHA) if restore else (ENABLED_BYTES, ENABLED_SHA)
    result = data[:PATCH_OFFSET] + desired_bytes + data[PATCH_OFFSET + 4:]
    if hashlib.sha256(result).hexdigest() != desired_sha:
        raise ValueError("Falha na verificação da biblioteca de saída.")
    return result


def read_library(path):
    if path.stat().st_size != LIB_SIZE:
        raise ValueError("Tamanho de lib diferente da build ARM64 estudada.")
    return path.read_bytes()


def read_apk(path):
    with zipfile.ZipFile(path) as apk:
        entries = [info for info in apk.infolist() if info.filename == LIB_ENTRY]
        if not entries:
            return None
        if len(entries) != 1 or entries[0].file_size != LIB_SIZE:
            raise ValueError("Entrada ARM64 ambígua ou de tamanho diferente da build estudada.")
        return apk.read(entries[0])


def read_device(adb):
    result = subprocess.run(adb + ["shell", "pm", "path", PACKAGE], capture_output=True, timeout=15)
    if result.returncode:
        raise ValueError("Não consegui consultar o APK. Confira `adb devices` e a conexão autorizada.")
    paths = []
    for line in result.stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith("package:"):
            path = line[8:].strip()
            if not path.startswith("/") or not path.endswith(".apk") or "\x00" in path:
                raise ValueError("Caminho de pacote inesperado retornado pelo aparelho.")
            paths.append(path)
    if not paths or len(paths) > 32:
        raise ValueError("PK XD não encontrado ou pacote não suportado. Use --library com a lib extraída pelo MT Manager.")
    # ABI splits may hold the library while base.apk holds only assets/Java.
    paths.sort(key=lambda p: ("arm64" not in p, not p.endswith("/base.apk")))
    with tempfile.TemporaryDirectory(prefix="pkxd-logging-") as temp:
        local_apk = Path(temp) / "package.apk"
        for remote in paths:
            print("Lendo um APK instalado para localizar a lib ARM64…", flush=True)
            pulled = subprocess.run(adb + ["pull", remote, str(local_apk)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
            if pulled.returncode:
                raise ValueError("Falha ao copiar o APK por adb. O aplicativo instalado foi preservado.")
            data = read_apk(local_apk)
            local_apk.unlink()
            if data is not None:
                return data, Path(remote).name
    raise ValueError("Nenhum APK instalado contém lib/arm64-v8a/libil2cpp.so.")


def save_library(data, directory, *, source, restore=False):
    directory.mkdir(parents=True, exist_ok=True)
    library = directory / "libil2cpp.so"
    if library.exists():
        if library.stat().st_size != len(data) or hashlib.sha256(library.read_bytes()).digest() != hashlib.sha256(data).digest():
            raise ValueError("A pasta de saída já contém outra lib. Escolha outra pasta; nenhum arquivo existente foi substituído.")
    else:
        with library.open("xb") as stream:
            stream.write(data)
    manifest = {
        "appVersion": "1.38.4", "abi": "arm64-v8a", "source": source,
        "method": "PlayKids.XD.ApplicationManager.Awake", "methodRva": "0x2738D18",
        "fileOffsetAndRva": hex(PATCH_OFFSET), "patchLength": 4,
        "originalInstruction": "mov w1, wzr", "diagnosticInstruction": "mov w1, #1",
        "originalBytes": ORIGINAL_BYTES.hex(), "diagnosticBytes": ENABLED_BYTES.hex(),
        "originalSha256": ORIGINAL_SHA, "diagnosticSha256": ENABLED_SHA,
        "outputSha256": hashlib.sha256(data).hexdigest(),
        "managedLogsEnabled": not restore, "apkInstalledOrSignedByTool": False,
        "worldEntryConfirmed": False,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return library


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--library", type=Path, help="libil2cpp.so extraída do APK")
    inputs.add_argument("--apk", type=Path, help="APK local contendo a lib ARM64")
    inputs.add_argument("--from-device", action="store_true", help="Lê o APK instalado pelo adb já autorizado")
    parser.add_argument("--serial", help="Conexão exibida em adb devices, se houver várias")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "client-logging")
    parser.add_argument("--restore", action="store_true", help="Produz uma cópia com os quatro bytes originais")
    args = parser.parse_args()
    try:
        if args.library:
            if args.library.resolve() == (args.output_dir / "libil2cpp.so").resolve():
                raise ValueError("Entrada e saída devem ser arquivos distintos.")
            data, source = read_library(args.library), "biblioteca local"
        elif args.apk:
            data, source = read_apk(args.apk), args.apk.name
            if data is None:
                raise ValueError("Este APK não contém a lib ARM64. Use o APK/split que contém a biblioteca.")
        else:
            executable = shutil.which("adb")
            if executable is None:
                raise ValueError("Instale android-tools e conecte o adb antes de usar --from-device.")
            adb = [executable] + (["-s", args.serial] if args.serial else [])
            data, source = read_device(adb)
        patched = transform(data, restore=args.restore)
        library = save_library(patched, args.output_dir, source=source, restore=args.restore)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"{error}\n")
    print(f"Lib validada e gerada: {library}")
    print(f"SHA-256: {hashlib.sha256(patched).hexdigest()}")
    print("No MT Manager, substitua lib/arm64-v8a/libil2cpp.so em uma cópia do seu APK modificado.")
    print("Use a mesma chave de assinatura da instalação atual para preservar os dados do aplicativo.")
    if args.restore:
        print("A cópia contém os quatro bytes originais, com o comportamento original do logger.")
    else:
        print("O patch habilita diagnóstico; a causa do retorno ao menu ainda precisa ser capturada.")


if __name__ == "__main__":
    main()
