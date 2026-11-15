"""Download, verify, and package one part of the public market data release."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
PREFIX = "https://data.binance.vision/data/"


def checked_path(entry):
    path = PurePosixPath(entry["path"])
    if (path.is_absolute() or not path.parts or path.parts[0] != "binance"
            or any(part in (".", "..") for part in path.parts)
            or not path.name.endswith(".zip")):
        raise ValueError("invalid archive path")
    if entry["url"] != PREFIX + "/".join(path.parts[1:]):
        raise ValueError("archive URL and path do not match")
    if not re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) or entry["bytes"] <= 0:
        raise ValueError("invalid expected archive size or digest")
    return path


def download(entry, staging):
    relative = checked_path(entry)
    destination = staging.joinpath(*relative.parts)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    for attempt in range(5):
        try:
            digest = hashlib.sha256()
            size = 0
            request = Request(entry["url"], headers={"User-Agent": "crypto-breakout-data-release/1"})
            with urlopen(request, timeout=90) as source, temporary.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    if size > entry["bytes"]:
                        raise ValueError(f"archive exceeds expected size: {relative}")
            if size != entry["bytes"] or digest.hexdigest() != entry["sha256"]:
                raise ValueError(f"archive checksum or size mismatch: {relative}")
            temporary.replace(destination)
            return destination
        except Exception:
            temporary.unlink(missing_ok=True)
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def create_part(manifest, part, output, staging):
    entries = [item for item in manifest["archives"] if item["part"] == part]
    if not entries:
        raise ValueError("part is empty or does not exist")
    if len({str(checked_path(item)) for item in entries}) != len(entries):
        raise ValueError("duplicate archive path")
    staging.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(download, item, staging) for item in entries]
        for n, future in enumerate(as_completed(futures), start=1):
            future.result()
            if n % 25 == 0 or n == len(entries):
                print(f"Verified {n}/{len(entries)} archives", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as tar:
        for entry in entries:
            relative = checked_path(entry)
            local_path = staging.joinpath(*relative.parts)
            info = tarfile.TarInfo(str(relative))
            info.size = entry["bytes"]
            info.mode = 0o644
            info.mtime = 0
            with local_path.open("rb") as source:
                tar.addfile(info, source)
    if output.stat().st_size >= 2 * 1024 ** 3:
        raise ValueError("part exceeds the GitHub release asset limit")
    digest = hashlib.sha256()
    with output.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    print(f"Part {part}: {output.stat().st_size} bytes, sha256 {digest.hexdigest()}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("part", type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--staging", required=True, type=Path)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "source-manifest.json").read_text(encoding="utf-8"))
    create_part(manifest, args.part, args.output, args.staging)


if __name__ == "__main__":
    main()
