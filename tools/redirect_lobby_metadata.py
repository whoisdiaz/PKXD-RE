#!/usr/bin/env python3
"""Redirect only the two production lobby literals in the known v29 metadata.

Creates a separate file. Does not modify the native library, protocol, account
hosts, certificate verification, or APK signatures.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path
from urllib.parse import urlsplit

ORIGINAL_SHA256 = "f2e909fe0d8668da323805d2a8cef2d69068b6f114322aedd0d2b3452a24ffde"
LOBBY_LITERALS = (
    b"https://pkxd-lobby.aftvrsys.com",
    b"https://pkxd-lobby.playpkxd.com",
)


def redirect_metadata(original, url):
    if hashlib.sha256(original).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Metadata does not match the file analyzed for this project; refusing guessed offsets.")
    if struct.unpack_from("<II", original) != (0xFAB11BAF, 29):
        raise ValueError("Expected IL2CPP metadata version 29.")
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) lobby base URL without credentials.")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Use a lobby base URL without a path, query, or fragment.")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("Invalid lobby port.") from error
    url = url.rstrip("/")
    replacement = url.encode("ascii")
    if len(replacement) > min(map(len, LOBBY_LITERALS)):
        raise ValueError("Lobby URL is longer than the original literal slots; use a shorter hostname/URL.")
    literal_offset, literal_size, data_offset, data_size = struct.unpack_from("<IIII", original, 8)
    if literal_size % 8 or literal_offset < 256 or data_offset < 256:
        raise ValueError("Invalid metadata literal tables.")
    if literal_offset + literal_size > len(original) or data_offset + data_size > len(original):
        raise ValueError("Metadata literal table exceeds the input size.")
    records = []
    selected = []
    found = set()
    for index in range(literal_size // 8):
        record_offset = literal_offset + index * 8
        length, relative = struct.unpack_from("<Ii", original, record_offset)
        if relative < 0 or relative + length > data_size:
            raise ValueError("Invalid literal data range.")
        start = data_offset + relative
        value = original[start:start + length]
        records.append((index, start, start + length))
        if value in LOBBY_LITERALS:
            selected.append((index, record_offset, start, length, value))
            found.add(value)
    if found != set(LOBBY_LITERALS):
        raise ValueError("Both expected production lobby URLs must be present.")
    selected_indices = {r[0] for r in selected}
    for _, _, start, length, _ in selected:
        for index, other_start, other_end in records:
            if index not in selected_indices and max(start, other_start) < min(start + length, other_end):
                raise ValueError("A lobby literal overlaps another literal; refusing to modify it.")
    result = bytearray(original)
    changes = []
    for index, record_offset, start, length, value in selected:
        struct.pack_into("<I", result, record_offset, len(replacement))
        result[start:start + length] = replacement + b"\0" * (length - len(replacement))
        changes.append({"literal_index": index, "length_offset": record_offset,
                        "data_offset": start, "old_length": length,
                        "old_url": value.decode("ascii"), "new_url": url})
    return bytes(result), changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Original global-metadata.dat")
    parser.add_argument("output", type=Path, help="Separate output path; existing files are preserved")
    parser.add_argument("--lobby-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different files.")
    try:
        original = args.input.read_bytes()
        result, changes = redirect_metadata(original, args.lobby_url)
        with args.output.open("xb") as target:
            target.write(result)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Could not redirect the lobby: {error}\n")
    print(json.dumps({"output": str(args.output), "sha256": hashlib.sha256(result).hexdigest(),
                      "size_bytes": len(result), "changes": changes}, indent=2))


if __name__ == "__main__":
    main()
