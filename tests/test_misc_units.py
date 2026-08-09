#!/usr/bin/env python3
"""Unit tests for ROI parsing/suggestion and richer-artifact detection.

Run:  python3 tests/test_misc_units.py
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
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


def raises(fn, *a) -> bool:
    try:
        fn(*a)
        return False
    except (ValueError, Exception):
        return True


def main() -> int:
    # ---- parse_roi ----------------------------------------------------------
    check(ek.parse_roi("300,190,920,430") == (300, 190, 920, 430),
          "roi: four comma ints parse")
    check(ek.parse_roi(" 0, 0, 10, 10 ") == (0, 0, 10, 10),
          "roi: whitespace tolerated")
    check(raises(ek.parse_roi, "banana"), "roi: garbage rejected")
    check(raises(ek.parse_roi, "1,2,3"), "roi: three fields rejected")
    check(raises(ek.parse_roi, "0,0,-5,10"), "roi: negative width rejected")
    check(raises(ek.parse_roi, "0,0,0,10"), "roi: zero width rejected")
    check(raises(ek.parse_roi, "-1,0,5,10"), "roi: negative origin rejected")

    # ---- suggest_roi --------------------------------------------------------
    # hot region = left half -> keep the right half
    check(ek.suggest_roi((0, 0, 640, 720), 1280, 720) == (640, 0, 640, 720),
          "suggest: hot left half -> right half kept")
    # hot region centered -> the biggest clean side wins (right, here)
    check(ek.suggest_roi((400, 200, 400, 300), 1280, 720) == (800, 0, 480, 720),
          "suggest: centered hot region -> largest side kept",
          f"got {ek.suggest_roi((400, 200, 400, 300), 1280, 720)}")
    # hot region covers nearly everything -> nothing useful to keep
    check(ek.suggest_roi((10, 10, 1260, 700), 1280, 720) is None,
          "suggest: near-full hot region -> no suggestion")
    # hot region = top band -> keep everything below
    check(ek.suggest_roi((0, 0, 1280, 100), 1280, 720) == (0, 100, 1280, 620),
          "suggest: top banner hot -> lower area kept")

    # ---- URL input ----------------------------------------------------------
    check(ek.is_url("https://example.com/demo.mp4"), "url: https detected")
    check(ek.is_url("http://example.com/demo.mp4"), "url: http detected")
    check(not ek.is_url("C:\\videos\\demo.mp4"), "url: windows path is not a url")
    check(not ek.is_url("./demo.mp4"), "url: relative path is not a url")
    check(not ek.is_url("file:///tmp/demo.mp4"), "url: file scheme rejected")
    check(not ek.is_url("ftp://example.com/demo.mp4"), "url: ftp scheme rejected")

    for u in (
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://www.loom.com/share/abc123",
        "https://drive.google.com/file/d/abc123/view",
        "https://vimeo.com/123456",
    ):
        check(ek.player_page_hint(u) is not None,
              f"url: player page rejected ({u.split('/')[2]})")
    check(ek.player_page_hint("https://cdn.example.com/rec/demo.mp4") is None,
          "url: direct video url passes the player-page gate")

    check(ek.filename_from_url("https://x.com/a/b/demo.mp4?sig=1") == "demo.mp4",
          "url: filename taken from path, query stripped",
          f"got {ek.filename_from_url('https://x.com/a/b/demo.mp4?sig=1')!r}")
    check(ek.filename_from_url("https://x.com/clip.webm") == "clip.webm",
          "url: non-mp4 video suffix kept")
    check(ek.filename_from_url("https://x.com/download") == "download.mp4",
          "url: suffix-less basename gets .mp4",
          f"got {ek.filename_from_url('https://x.com/download')!r}")
    check(ek.filename_from_url("https://x.com/") == "remote-video.mp4",
          "url: empty basename falls back to remote-video.mp4",
          f"got {ek.filename_from_url('https://x.com/')!r}")

    # ---- find_richer_artifacts ---------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="flowrec-misc-"))
    try:
        vid = tmp / "run.mp4"
        vid.write_bytes(b"\x00")
        check(ek.find_richer_artifacts(vid) == [], "artifacts: empty dir -> none")

        (tmp / "session.har").write_text("{}")
        (tmp / "trace.zip").write_bytes(b"PK")
        (tmp / "playwright-trace.zip").write_bytes(b"PK")
        (tmp / "random.zip").write_bytes(b"PK")  # zip without 'trace': not an artifact
        got = ek.find_richer_artifacts(vid)
        check("session.har" in got, "artifacts: .har detected", f"got {got}")
        check("trace.zip" in got and "playwright-trace.zip" in got,
              "artifacts: trace zips detected", f"got {got}")
        check("random.zip" not in got, "artifacts: unrelated zip ignored", f"got {got}")

        # cypress layout: video lives in videos/, screenshots/ is its sibling
        cyp = tmp / "cypress"
        (cyp / "videos").mkdir(parents=True)
        (cyp / "screenshots").mkdir()
        cvid = cyp / "videos" / "spec.mp4"
        cvid.write_bytes(b"\x00")
        got = ek.find_richer_artifacts(cvid)
        check(any("screenshots" in g for g in got),
              "artifacts: cypress screenshots dir detected", f"got {got}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all misc unit checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
