"""Extract a named file (e.g. system/main.dol) out of a GameCube ISO.

Usage: extract_iso_file.py <iso> <path-suffix> <out>
"""
from __future__ import annotations

import struct
import sys


def iter_files(iso_path: str):
    with open(iso_path, "rb") as f:
        f.seek(0x420)
        _dol_off, fst_off, fst_len = struct.unpack(">3I", f.read(12))
        f.seek(fst_off)
        fst = f.read(fst_len)
    n = len(fst) // 12
    strings_off = n * 12

    def name_of(i: int) -> str:
        off = struct.unpack(">I", fst[i * 12 + 8 : i * 12 + 12])[0] & 0x03FFFFFF
        end = fst.index(b"\0", strings_off + off)
        return fst[strings_off + off : end].decode("latin1")

    def walk(j: int, end: int, prefix: str):
        while j < end:
            w0, w1, w2 = struct.unpack(">3I", fst[j * 12 : j * 12 + 12])
            nm = name_of(j)
            path = f"{prefix}/{nm}"
            if w2 & 0x80000000:
                yield from walk(j + 1, w2 & 0x03FFFFFF, path)
            else:
                yield path, w0 << 2, w1 << 2
            j += 1

    root_end = struct.unpack(">I", fst[8:12])[0] & 0x03FFFFFF
    yield from walk(1, root_end, "")


def extract(iso_path: str, wanted: str, out_path: str) -> None:
    found = False
    with open(iso_path, "rb") as f:
        for path, start, length in iter_files(iso_path):
            if path.lower().endswith(wanted.lower()):
                f.seek(start)
                with open(out_path, "wb") as o:
                    remaining = length
                    while remaining:
                        chunk = f.read(min(1 << 22, remaining))
                        if not chunk:
                            break
                        o.write(chunk)
                        remaining -= len(chunk)
                print(f"extracted {path} ({length} bytes at iso offset {start:#x}) -> {out_path}")
                found = True
    if not found:
        sys.exit(f"{wanted} not found in {iso_path}")


if __name__ == "__main__":
    extract(sys.argv[1], sys.argv[2], sys.argv[3])
