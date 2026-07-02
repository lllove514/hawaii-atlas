"""Resumable download helper shared by discovery and the full download.

Skips files that already exist and are non-empty, so an interrupted overnight
run restarts cleanly. Retries with exponential backoff on transient errors.
"""

import sys
import time
import zipfile
from pathlib import Path

import requests

_UA = {"User-Agent": "lava-flow-history-map/1.0 (+overnight batch)"}


def download(url, dest, retries=5, backoff=2.0, min_bytes=1):
    """Download url -> dest (Path), resumable. Returns dest.

    If dest already exists and is at least min_bytes, it is left untouched.
    Streams to a .part file and renames on success so a partial file is never
    mistaken for a finished one.
    """
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"  skip (exists): {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=60, headers=_UA) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                got = 0
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        got += len(chunk)
                        if total:
                            pct = 100 * got / total
                            print(f"\r  {dest.name}: {got/1e6:6.1f}/{total/1e6:.1f} MB "
                                  f"({pct:4.1f}%)", end="", flush=True)
                print()
            if got < min_bytes:
                raise IOError(f"downloaded {got} bytes, expected >= {min_bytes}")
            part.replace(dest)
            return dest
        except Exception as e:  # network / HTTP / IO — all retriable
            last_err = e
            wait = backoff ** attempt
            print(f"\n  attempt {attempt}/{retries} failed for {dest.name}: {e}; "
                  f"retry in {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"failed to download {url}: {last_err}")


def unzip(zip_path, dest_dir, marker=None):
    """Extract zip_path into dest_dir unless marker (a path under dest_dir)
    already exists. Returns dest_dir."""
    zip_path, dest_dir = Path(zip_path), Path(dest_dir)
    if marker is not None and Path(marker).exists():
        print(f"  skip (extracted): {zip_path.name}")
        return dest_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest_dir)
    print(f"  extracted: {zip_path.name} -> {dest_dir}")
    return dest_dir


def _selfcheck():
    # A tiny end-to-end check against a stable, tiny public file.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "robots.txt"
        download("https://www.sciencebase.gov/robots.txt", p)
        assert p.exists() and p.stat().st_size > 0
        # Second call must skip (resumability), not re-download.
        mtime = p.stat().st_mtime
        download("https://www.sciencebase.gov/robots.txt", p)
        assert p.stat().st_mtime == mtime, "resume skip failed"
    print("fetch self-check OK")


if __name__ == "__main__":
    _selfcheck()
