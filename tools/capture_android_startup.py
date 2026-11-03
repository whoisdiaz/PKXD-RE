#!/usr/bin/env python3
"""Capture PK XD startup messages through an already paired local adb."""
import argparse
from datetime import datetime
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from collections import deque
from urllib.parse import urlsplit, urlunsplit

PACKAGE = "com.movile.playkids.pkxd"
MAX_CAPTURE = 64 * 1024
MAX_FOCUS = 16 * 1024
STARTUP_MARKERS = re.compile(
    r"GameController|PlayerCreation|InitStep|initializ|Exception|Addressabl|AssetBundle|"
    r"deadlock|timeout|failed|failure|error|fatal|carregando", re.IGNORECASE)


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
    text = re.sub(r'''(?i)(["']?(?:authToken|userToken|token|authorization|sessionId|deviceId|password|passwd|secret|api[_-]?key)["']?\s*[:=]\s*)(["']?)[^\s"',;}]+''',
                  r"\1<oculto>", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "<jwt oculto>", text)
    return re.sub(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b", "<uuid oculto>", text)


def read_capture(stream):
    stream.seek(0)
    prefix, tail, size = bytearray(), bytearray(), 0
    for raw_line in stream:
        # Sanitize entire lines before clipping, so a tail beginning just after
        # "userToken=" cannot expose the token after losing its label.
        line = redact(raw_line.decode("utf-8", errors="replace")).encode("utf-8")
        size += len(line)
        prefix.extend(line[:MAX_CAPTURE - len(prefix)])
        tail.extend(line[-MAX_CAPTURE // 2:])
        if len(tail) > MAX_CAPTURE // 2:
            del tail[:-MAX_CAPTURE // 2]
    data = prefix if size <= MAX_CAPTURE else prefix[:MAX_CAPTURE // 2] + b"\n[... captura truncada ...]\n" + tail
    return data.decode("utf-8", errors="replace")


def focus_capture(stream):
    """Keep startup/error context even when it falls outside the log's ends."""
    stream.seek(0)
    lines, kept_bytes, context, count, unity_count = deque(), 0, 0, 0, 0
    for raw_line in stream:
        if not raw_line.strip() or raw_line.startswith(b"---------"):
            continue
        count += 1
        line = raw_line.decode("utf-8", errors="replace")
        unity_count += bool(re.search(r"\bUnity\b", line))
        if STARTUP_MARKERS.search(line):
            context = 8
        elif context:
            context -= 1
        else:
            continue
        # Redact before retention so clipping cannot sever a credential label.
        encoded = redact(line).encode("utf-8")[:MAX_FOCUS]
        lines.append(encoded)
        kept_bytes += len(encoded)
        while kept_bytes > MAX_FOCUS:
            kept_bytes -= len(lines.popleft())
    return b"".join(lines).decode("utf-8", errors="replace"), count, unity_count


def app_pids(adb):
    try:
        result = subprocess.run(adb + ["shell", "pidof", PACKAGE], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Não consegui consultar o aparelho. Confira `adb devices` e a conexão sem fio.") from None
    pids = result.stdout.decode("ascii", errors="replace").split()
    if result.returncode or not pids or not all(pid.isdigit() for pid in pids):
        raise ValueError("Abra o PK XD e deixe na tela inicial. Confira se `adb devices` mostra um único aparelho autorizado; use --serial se houver vários.")
    return pids


def capture(adb, seconds, output, *, errors_only=False):
    pids = app_pids(adb)
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    # Include history: the previous -T 1/error-only filter could miss a failure
    # emitted just before collection or a warning/info initialization message.
    filters = ["Unity:E", "AndroidRuntime:E", "*:S"] if errors_only else ["*:V"]
    command = adb + ["logcat", "-T", "500", "--pid", pids[0], "-v", "threadtime"] + filters
    mode = "erros" if errors_only else "mensagens de todos os níveis"
    print(f"Capturando {mode} do PK XD por {seconds}s (PID {pids[0]}).", flush=True)
    print("Agora volte ao jogo e toque em Jogar. Aguarde a captura terminar, mesmo se voltar ao menu.", flush=True)
    print("O servidor deve continuar aberto em outra sessão. Ctrl+C salva uma captura parcial.", flush=True)
    started, interrupted, finished = time.monotonic(), False, "leitor encerrado"
    with tempfile.TemporaryFile() as raw:
        process = subprocess.Popen(command, stdout=raw, stderr=subprocess.PIPE)
        try:
            _, error = process.communicate(timeout=seconds)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as reason:
            interrupted = isinstance(reason, KeyboardInterrupt)
            finished = "interrompida por Ctrl+C" if interrupted else "janela concluída"
            process.terminate()
            try:
                _, error = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                _, error = process.communicate()
        elapsed = time.monotonic() - started
        text = read_capture(raw)
        focus, count, unity_count = focus_capture(raw)
    reader_error = process.returncode not in (0, -2, -15, -9, 130)
    if reader_error:
        finished = f"leitor ADB encerrou com status {process.returncode}; confira a conexão"
    try:
        final_pids = app_pids(adb)
        process_state = "mesmo processo ativo" if pids[0] in final_pids else "processo mudou"
    except ValueError:
        process_state = "PID final indisponível; processo pode ter fechado ou adb perdeu conexão"
    header = (f"PK XD 1.38.4 — mensagens do aplicativo durante a entrada\n"
              f"Início no aparelho: {started_at}\n"
              f"Captura: {finished}; {elapsed:.1f}s de {seconds}s; PID {pids[0]}; {process_state}\n"
              f"Linhas coletadas: {count}; linhas mencionando Unity: {unity_count}; histórico solicitado: 500 linhas\n")
    if reader_error and error:
        header += "Detalhe do ADB: " + redact(error.decode("utf-8", errors="replace"))[:2048] + "\n"
    if not count or not text.strip():
        text = "Nenhuma mensagem do processo foi capturada. Isso não confirma ausência de falha no jogo.\n"
    if focus:
        header += "\nTrechos de inicialização/erro e contexto:\n" + focus + "\n"
    report = header + "\nLog limitado do processo:\n" + text
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(report, end="" if report.endswith("\n") else "\n")
    print(f"Relatório salvo em: {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="Serial exibido por adb devices, se houver mais de uma conexão")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--errors-only", action="store_true", help="Usa apenas Unity:E/AndroidRuntime:E, como a captura anterior")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "android-startup.txt")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 180:
        parser.error("--seconds deve ficar entre 1 e 180")
    executable = shutil.which("adb")
    if executable is None:
        parser.exit(1, "Instale o adb no Termux: pkg install android-tools\n")
    adb = [executable] + (["-s", args.serial] if args.serial else [])
    try:
        capture(adb, args.seconds, args.output, errors_only=args.errors_only)
    except (ValueError, OSError) as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
