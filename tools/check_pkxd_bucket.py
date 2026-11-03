#!/usr/bin/env python3
"""Check public PK XD configuration URLs from the same network as the Android client."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import http.client
import json
from pathlib import Path
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://pkxd-bucket.aftvrsys.com/"
PATHS = (
    "creators/creators-panels.json", "news/news.json",
    "recurrent-activity/recurrent_activities_config.json", "server-health/health.json",
    "soft-update/update-info.json", "ugc-teleporter-config/ugc-teleporter-config.json",
)
MAX_BODY = 512 * 1024
USER_AGENT = "PKXD-RE/bucket-diagnostic"


def inspect_response(response, method):
    parsed_url = urllib.parse.urlsplit(response.geturl())
    result = {
        "status": response.status,
        "finalUrl": urllib.parse.urlunsplit((parsed_url.scheme, parsed_url.hostname or "", parsed_url.path, "", "")),
        "contentType": response.headers.get("Content-Type", ""),
        "contentMd5": response.headers.get("Content-MD5", ""),
        "etag": response.headers.get("ETag", ""),
        "lastModified": response.headers.get("Last-Modified", ""),
    }
    if method == "GET":
        body = response.read(MAX_BODY + 1)
        result.update(bytesRead=len(body), truncated=len(body) > MAX_BODY, jsonValid=False)
        if len(body) <= MAX_BODY:
            try:
                data = json.loads(body.decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                pass
            else:
                result.update(jsonValid=True, jsonRootType=type(data).__name__)
                if isinstance(data, dict):
                    result["jsonKeys"] = sorted(data)[:32]
    return result


def fetch(url, method, timeout, *, opener=None):
    request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            return inspect_response(response, method)
    except urllib.error.HTTPError as error:
        with error:
            return inspect_response(error, method)
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        kind = ("tls" if isinstance(reason, ssl.SSLError) else
                "dns" if isinstance(reason, socket.gaierror) else
                "timeout" if isinstance(reason, TimeoutError) else "connection")
        return {"status": None, "error": kind, "errorType": type(reason).__name__}


def check_path(path, timeout):
    url = BASE + path
    # Client retrievers may validate HEAD before attempting to download JSON.
    return {"url": url, "head": fetch(url, "HEAD", timeout), "get": fetch(url, "GET", timeout)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "pkxd-bucket.json")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout deve ficar entre 1 e 30 segundos")
    print("Verificando HEAD e GET dos JSONs públicos do pkxd-bucket…", flush=True)
    records = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        pending = {pool.submit(check_path, path, args.timeout): path for path in PATHS}
        for future in as_completed(pending):
            path = pending[future]
            record = future.result()
            records[path] = record
            head, get = record["head"], record["get"]
            print(f"{path}: HEAD={head.get('status') or head.get('error')} GET={get.get('status') or get.get('error')} JSON={get.get('jsonValid', False)}", flush=True)
    report = {"checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
              "userAgent": USER_AGENT, "urls": [records[path] for path in PATHS],
              "worldEntryFailureCauseConfirmed": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Relatório salvo em: {args.output}")
    print("O teste verifica conectividade/JSON; os logs do cliente indicarão se alguma dessas falhas bloqueia a entrada.")


if __name__ == "__main__":
    main()
