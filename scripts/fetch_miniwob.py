"""Fetch the MiniWoB++ task pages this repo serves, pinned to one upstream commit.

The pages are vendored under vendor/miniwob/ so a clean clone works offline; this script is
how they got there, and how to re-verify them. Every file is checked against the git blob
SHA-1 recorded in vendor/miniwob/MANIFEST.json, so a truncated or tampered download fails
loudly instead of producing a subtly broken task.

    uv run python scripts/fetch_miniwob.py            # download anything missing, verify all
    uv run python scripts/fetch_miniwob.py --verify   # verify only, no network

Only raw.githubusercontent.com is used (GitHub codeload is throttled on this network).
The flight/ subtree (the separate book-flight benchmark) is not fetched.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "miniwob"
MANIFEST = VENDOR / "MANIFEST.json"
RAW = "https://raw.githubusercontent.com/Farama-Foundation/miniwob-plusplus/{sha}/{path}"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def fetch(url: str, attempts: int = 4) -> bytes:
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                return resp.read()
        except OSError as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f"giving up on {url}: {exc}") from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="verify only, never download")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sha = manifest["commit"]
    missing = [e for e in manifest["files"] if not (VENDOR / e["path"]).exists()]
    bad = fetched = 0
    if args.verify:
        for entry in missing:
            print(f"MISSING {entry['path']}")
        bad += len(missing)
    else:

        def download(entry: dict) -> None:
            data = fetch(RAW.format(sha=sha, path=f"miniwob/html/{entry['path']}"))
            dest = VENDOR / entry["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # One file at a time took ~10 s each on a throttled link; 16 in flight took 3.5 min
        # for 145 files.
        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(download, missing))
        fetched = len(missing)
    for entry in manifest["files"]:
        dest = VENDOR / entry["path"]
        if dest.exists() and git_blob_sha(dest.read_bytes()) != entry["sha"]:
            print(f"CHECKSUM MISMATCH {entry['path']}")
            bad += 1
    total = len(manifest["files"])
    print(f"{total - bad}/{total} files verified against commit {sha[:12]} ({fetched} fetched)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
