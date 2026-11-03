#!/usr/bin/env python3
"""Capture PK XD Unity/AndroidRuntime errors through an already paired local adb."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit

PACKAGE = "com.movile.playkids.pkxd"
MAX_CAPTURE = 64 * 1024


def redact(text):
    def safe_url(match):
        try:
            url = urlsplit(match.group())
            host = url.hostname or "host"
            return urlunsplit((url.scheme, host, url.path, "", ""))
        except ValueError:
            return "<url omitida>"
    text = re.sub(r"https?://[^\s<>\"']+", safe_url, text)
    text = re.sub(r"(?i)(/v1/auth/sessions/)[^/\s\"']+", r"\1<sessao oculta>", text)
    text = re.sub(r"(?i)Bearer\s+[^\s\"',}]+", "Bearer <oculto>", text)
    text = re.sub(r'''(?i)(["']?(?:authToken|userToken|token|authorization|sessionId|deviceId)["']?\s*[:=]\s*)(["']?)[^\s"',;}]+''',
                  r"\1<oculto>", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "<jwt oculto>", text)
    return re.sub(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", "<uuid oculto>", text)


def read_capture(stream):
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    if size <= MAX_CAPTURE:
        data = stream.read()
    else:
        data = stream.read(MAX_CAPTURE // 2)
        stream.seek(-MAX_CAPTURE // 2, 2)
        data += b"\n[... captura truncada ...]\n" + stream.read(MAX_CAPTURE // 2)
    return redact(data.decode("utf-8", errors="replace"))


def capture(adb, seconds, output):
    try:
        result = subprocess.run(adb + ["shell", "pidof", PACKAGE], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Não consegui consultar o aparelho. Confira `adb devices` e a conexão sem fio.") from None
    pids = result.stdout.decode("ascii", errors="replace").split()
    if result.returncode or not pids or not all(pid.isdigit() for pid in pids):
        raise ValueError("Abra o PK XD e deixe na tela inicial. Confira se `adb devices` mostra um único aparelho autorizado; use --serial se houver vários.")
    command = adb + ["logcat", "-T", "1", "--pid", pids[0], "-v", "threadtime", "Unity:E", "AndroidRuntime:E", "*:S"]
    print(f"Capturando erros do PK XD por {seconds}s. Agora volte ao jogo e toque em Jogar.", flush=True)
    print("Ctrl+C encerra e salva o que já foi capturado. O servidor deve continuar aberto em outra sessão.", flush=True)
    with tempfile.TemporaryFile() as raw:
        process = subprocess.Popen(command, stdout=raw, stderr=subprocess.PIPE)
        try:
            _, error = process.communicate(timeout=seconds)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            process.terminate()
            try:
                _, error = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                _, error = process.communicate()
        text = read_capture(raw)
    if process.returncode not in (0, -2, -15, -9, 130):
        raise ValueError("O adb não conseguiu ler o logcat. Confira a conexão e a versão do android-tools.")
    if not text.strip() or not any(tag in text for tag in ("Unity", "AndroidRuntime")):
        text = "Nenhum erro Unity/AndroidRuntime do PK XD foi capturado nesta tentativa.\n"
    report = "PK XD 1.38.4 — erros do aplicativo durante a entrada\n" + text
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report, end="" if report.endswith("\n") else "\n")
    print(f"Relatório salvo em: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="Serial exibido por adb devices, se houver mais de uma conexão")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "android-startup.txt")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180:
        parser.error("--seconds deve ficar entre 1 e 180")
    executable = shutil.which("adb")
    if executable is None:
        parser.exit(1, "Instale o adb no Termux: pkg install android-tools\n")
    adb = [executable] + (["-s", args.serial] if args.serial else [])
    try:
        capture(adb, args.seconds, args.output)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
