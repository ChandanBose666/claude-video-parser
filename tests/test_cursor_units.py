#!/usr/bin/env python3
"""Unit tests for the cursor-detection primitives in extract_keyframes.py.

Pure-function tests on synthetic byte buffers — no video, no ffmpeg needed.

Run:  python3 tests/test_cursor_units.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = ROOT / "skills" / "claude-video-parser" / "scripts" / "extract_keyframes.py"

spec = importlib.util.spec_from_file_location("extract_keyframes", EXTRACT)
ek = importlib.util.module_from_spec(spec)
sys.modules["extract_keyframes"] = ek  # dataclasses need the module registered
spec.loader.exec_module(ek)

failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


def frame(w: int, h: int, spots: dict[tuple[int, int], int] | None = None) -> bytes:
    """Gray8 buffer, all zeros except {(x, y): value} spots."""
    buf = bytearray(w * h)
    for (x, y), v in (spots or {}).items():
        buf[y * w + x] = v
    return bytes(buf)


def block(w: int, h: int, x0: int, y0: int, bw: int, bh: int, v: int = 200) -> bytes:
    return frame(w, h, {(x, y): v for x in range(x0, x0 + bw) for y in range(y0, y0 + bh)})


def cursor_blob(cx: float, cy: float, count: int = 20, r: int = 3) -> "ek.Blob":
    return ek.Blob(count=count, cx=cx, cy=cy,
                   bx0=int(cx) - r, by0=int(cy) - r, bx1=int(cx) + r, by1=int(cy) + r)


def large_blob() -> "ek.Blob":
    return ek.Blob(count=5000, cx=160.0, cy=90.0, bx0=0, by0=0, bx1=319, by1=179)


W, H = 320, 180


def main() -> int:
    # ---- scan_diff_frame ----------------------------------------------------
    check(ek.scan_diff_frame(frame(W, H), W, H) is None,
          "scan: blank frame returns None")

    b = ek.scan_diff_frame(block(W, H, 10, 3, 5, 5), W, H)
    check(b is not None and b.count == 25, "scan: 5x5 block counted",
          f"got {b}")
    check(b is not None and abs(b.cx - 12.0) < 0.01 and abs(b.cy - 5.0) < 0.01,
          "scan: centroid of 5x5 block at (12, 5)", f"got ({b.cx}, {b.cy})" if b else "None")
    check(b is not None and (b.bx0, b.by0, b.bx1, b.by1) == (10, 3, 14, 7),
          "scan: bbox of 5x5 block", f"got {b}" if b else "None")

    check(ek.scan_diff_frame(frame(W, H, {(5, 5): 25}), W, H) is None,
          "scan: value 25 is below the default threshold")
    b = ek.scan_diff_frame(frame(W, H, {(5, 5): 26}), W, H)
    check(b is not None and b.count == 1,
          "scan: value 26 meets the default threshold")

    # run spanning a row boundary must not be treated as one horizontal run
    w2 = 40
    spots = {(37, 1): 200, (38, 1): 200, (39, 1): 200, (0, 2): 200, (1, 2): 200, (2, 2): 200}
    b = ek.scan_diff_frame(frame(w2, 20, spots), w2, 20)
    check(b is not None and b.count == 6 and abs(b.cx - 19.5) < 0.01 and abs(b.cy - 1.5) < 0.01,
          "scan: run wrapping a row boundary splits per row",
          f"got {b}")

    # ---- classify_blob ------------------------------------------------------
    check(ek.classify_blob(None, W, H) == "still", "classify: None is still")
    check(ek.classify_blob(cursor_blob(100, 50), W, H) == "cursor",
          "classify: small compact blob is cursor-like")
    check(ek.classify_blob(large_blob(), W, H) == "large",
          "classify: big blob is large")
    # small count but pixels spread across the frame (two distant dots) -> large
    spread = ek.Blob(count=20, cx=160.0, cy=90.0, bx0=0, by0=0, bx1=300, by1=170)
    check(ek.classify_blob(spread, W, H) == "large",
          "classify: small count with huge bbox is large, not cursor")

    # a pointer is a compact 2D glyph — thin lines and flat rows are not pointers
    caret = ek.Blob(count=4, cx=100.0, cy=50.0, bx0=100, by0=48, bx1=100, by1=51)
    check(ek.classify_blob(caret, W, H) == "still",
          "classify: caret-shaped blip (thin vertical line) is noise, not cursor")
    tall_caret = ek.Blob(count=8, cx=100.0, cy=50.0, bx0=100, by0=46, bx1=100, by1=53)
    check(ek.classify_blob(tall_caret, W, H) == "still",
          "classify: high-DPI caret (1x8 line) is noise, not cursor")
    text_row = ek.Blob(count=30, cx=124.0, cy=123.0, bx0=114, by0=122, bx1=135, by1=124)
    check(ek.classify_blob(text_row, W, H) == "still",
          "classify: text-row change (wide flat) is noise, not cursor")
    tiny = ek.Blob(count=3, cx=50.0, cy=50.0, bx0=49, by0=49, bx1=51, by1=51)
    check(ek.classify_blob(tiny, W, H) == "still",
          "classify: sub-cursor speck is noise, not cursor")

    # ---- estimate_cursor ----------------------------------------------------
    T = 2.5  # transition time

    # coherent approach trajectory ending just before the transition -> high
    traj = [(1.0 + i * 0.1, cursor_blob(30 + i * 5, 40 + i * 1)) for i in range(14)]
    est = ek.estimate_cursor(traj, W, H, T)
    check(est is not None and est["confidence"] == "high",
          "estimate: fresh coherent trajectory -> high confidence", f"got {est}")
    check(est is not None and abs(est["x"] - 95.0) < 1 and abs(est["y"] - 53.0) < 1,
          "estimate: position is the trajectory endpoint", f"got {est}")

    # trailing large frames (the UI reaction itself) are skipped
    react = traj + [(2.4, large_blob()), (2.5, large_blob())]
    est = ek.estimate_cursor(react, W, H, T)
    check(est is not None and abs(est["x"] - 95.0) < 1,
          "estimate: UI-reaction frames at the end are skipped", f"got {est}")

    # the window often ends reaction-then-stillness: [glide][reaction][still] —
    # the walk must get past both to reach the click motion
    settled = traj + [(2.4, large_blob()), (2.5, None), (2.6, None)]
    est = ek.estimate_cursor(settled, W, H, 2.6)
    check(est is not None and abs(est["x"] - 95.0) < 1,
          "estimate: stillness after the reaction is also skipped", f"got {est}")

    # in-place animation (spinner) must NOT be reported as a cursor
    spin = [(1.0 + i * 0.1, cursor_blob(160, 90)) for i in range(15)]
    check(ek.estimate_cursor(spin, W, H, T) is None,
          "estimate: in-place animation rejected")

    # a blinking text caret: few small diffs, all at the same spot, stills between.
    # No travel = no pointer. (This was a real 697px confident-wrong estimate.)
    caret = [(1.2, cursor_blob(100, 50)), (1.3, None), (1.4, None), (1.5, None),
             (1.7, cursor_blob(100, 50)), (1.8, None), (1.9, None), (2.0, None),
             (2.2, cursor_blob(100, 50)), (2.3, None)]
    check(ek.estimate_cursor(caret, W, H, T) is None,
          "estimate: caret blink (no travel) rejected")

    # stale motion (ended > 1.2s before the transition) -> None
    stale = [(0.5 + i * 0.1, cursor_blob(30 + i * 5, 40)) for i in range(5)]
    check(ek.estimate_cursor(stale, W, H, T) is None,
          "estimate: stale motion rejected")

    # a single blip is indistinguishable from one caret blink -> abstain
    single = [(2.2, cursor_blob(100, 50))]
    check(ek.estimate_cursor(single, W, H, T) is None,
          "estimate: single observation is ambiguous -> None")

    # two fresh observations WITH travel -> medium
    two = [(2.1, cursor_blob(80, 40)), (2.2, cursor_blob(100, 50))]
    est = ek.estimate_cursor(two, W, H, T)
    check(est is not None and est["confidence"] == "medium",
          "estimate: short travelling cluster -> medium confidence", f"got {est}")

    # nothing but stillness -> None
    still = [(1.0 + i * 0.1, None) for i in range(15)]
    check(ek.estimate_cursor(still, W, H, T) is None,
          "estimate: all-still window -> None")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all cursor unit checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
