#!/usr/bin/env python3
"""Unit tests for the OCR TSV parsing in extract_keyframes.py.

Pure-function tests on synthetic tesseract TSV output — no tesseract needed.

Run:  python3 tests/test_ocr_units.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = ROOT / "skills" / "claude-video-parser" / "scripts" / "extract_keyframes.py"

spec = importlib.util.spec_from_file_location("extract_keyframes", EXTRACT)
ek = importlib.util.module_from_spec(spec)
sys.modules["extract_keyframes"] = ek
spec.loader.exec_module(ek)

failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


HEADER = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
          "\tleft\ttop\twidth\theight\tconf\ttext")


def row(block: int, par: int, line: int, word: int, conf: float, text: str) -> str:
    return f"5\t1\t{block}\t{par}\t{line}\t{word}\t0\t0\t10\t10\t{conf}\t{text}"


def main() -> int:
    # words grouped into lines, in order
    tsv = "\n".join([
        HEADER,
        row(1, 1, 1, 1, 96.0, "Payment"),
        row(1, 1, 1, 2, 92.5, "failed"),
        row(1, 1, 2, 1, 91.0, "500"),
        row(1, 1, 2, 2, 88.0, "Internal"),
        row(1, 1, 2, 3, 90.2, "Server"),
        row(1, 1, 2, 4, 89.9, "Error"),
    ])
    out = ek.parse_tesseract_tsv(tsv)
    check(out == "Payment failed\n500 Internal Server Error",
          "tsv: words grouped into lines in reading order", f"got {out!r}")

    # low-confidence words are dropped; a line of only junk disappears
    tsv = "\n".join([
        HEADER,
        row(1, 1, 1, 1, 95.0, "Deploy"),
        row(1, 1, 1, 2, 30.0, "sm0ke"),
        row(1, 1, 2, 1, 12.0, "|||"),
    ])
    out = ek.parse_tesseract_tsv(tsv)
    check(out == "Deploy", "tsv: low-confidence words dropped", f"got {out!r}")

    # structural rows (conf -1) and blank text never contribute
    tsv = "\n".join([
        HEADER,
        row(1, 1, 1, 0, -1.0, ""),
        row(1, 1, 1, 1, 97.0, "Continue"),
        row(1, 1, 1, 2, 96.0, "   "),
    ])
    out = ek.parse_tesseract_tsv(tsv)
    check(out == "Continue", "tsv: structural and blank rows ignored", f"got {out!r}")

    # nothing confident -> None, not empty string
    tsv = "\n".join([HEADER, row(1, 1, 1, 1, 20.0, "noise")])
    check(ek.parse_tesseract_tsv(tsv) is None, "tsv: all-junk page returns None")

    check(ek.parse_tesseract_tsv("") is None, "tsv: empty input returns None")
    check(ek.parse_tesseract_tsv(HEADER) is None, "tsv: header-only input returns None")

    # malformed rows are skipped without crashing
    tsv = "\n".join([HEADER, "garbage\trow", row(1, 1, 1, 1, 95.0, "OK")])
    out = ek.parse_tesseract_tsv(tsv)
    check(out == "OK", "tsv: malformed rows skipped", f"got {out!r}")

    # distinct blocks stay distinct lines even with equal line numbers
    tsv = "\n".join([
        HEADER,
        row(1, 1, 1, 1, 95.0, "Header"),
        row(2, 1, 1, 1, 95.0, "Body"),
    ])
    out = ek.parse_tesseract_tsv(tsv)
    check(out == "Header\nBody", "tsv: separate blocks are separate lines", f"got {out!r}")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all ocr unit checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
