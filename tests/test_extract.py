#!/usr/bin/env python3
"""
End-to-end test: build the synthetic checkout fixture, run the extractor, assert the
selection is actually good — not merely that the script exited 0.

Run:  python3 tests/test_extract.py
Deps: ffmpeg, Pillow (fixture generation only). No test framework.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = ROOT / "skills" / "claude-video-parser" / "scripts" / "extract_keyframes.py"
FIXTURE_SRC = ROOT / "tests" / "make_fixture.py"

# Ground truth: the fixture holds each state for a known window.
# cart 0.0-2.5 | address 2.5-5.0 | payment 5.0-7.0 | press 7.0-7.3
# | spinner 7.3-9.5 | error 9.5-12.5
TRANSITIONS = [2.5, 5.0, 7.3, 9.5]
TOLERANCE = 0.30

# Click-driven transitions and where the fixture cursor rests when they fire
# (see make_fixture.py). 9.5s is app-driven (spinner -> error): no click there.
CLICK_TARGETS = [(2.5, 1105, 562), (5.0, 1105, 562), (7.3, 1095, 562)]
CURSOR_TOL_PX = 45

failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


def main() -> int:
    if shutil.which("ffmpeg") is None:
        print("SKIP: ffmpeg not on PATH")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="flowrec-test-"))
    try:
        video = tmp / "checkout-bug.mp4"
        subprocess.run([sys.executable, str(FIXTURE_SRC), str(video)], check=True)

        out = tmp / "keyframes"
        proc = subprocess.run(
            [sys.executable, str(EXTRACT), str(video), "-o", str(out)],
            capture_output=True, text=True,
        )
        print(proc.stdout)
        check(proc.returncode == 0, "extractor exits 0", proc.stderr[:300])

        manifest_path = out / "manifest.json"
        check(manifest_path.exists(), "manifest.json written")
        if not manifest_path.exists():
            return 1
        m = json.loads(manifest_path.read_text())

        sel = m["selection"]
        check(
            sel["strategy"].startswith("scene-change"),
            "used scene detection, not the uniform fallback",
            f"got {sel['strategy']!r}; UI scene scores may need a lower --threshold",
        )
        check(sel["candidates_found"] >= 4,
              "found >=4 scene candidates", f"got {sel['candidates_found']}")

        frames = m["frames"]
        check(4 <= len(frames) <= 14, "kept a sane frame count", f"got {len(frames)}")
        check(all((out / f["file"]).exists() for f in frames), "every frame file exists")

        times = [f["t"] for f in frames]
        for want in TRANSITIONS:
            near = [t for t in times if abs(t - want) <= TOLERANCE]
            check(bool(near), f"captured transition at ~{want:.1f}s",
                  f"nearest frames: {[round(t,2) for t in times]}")

        check(frames[0]["reason"] == "initial-state", "first frame pinned to initial state")
        check(frames[-1]["reason"] == "final-state", "last frame pinned to final state")

        cost = m["cost"]
        check(
            cost["est_visual_tokens_all_frames"] < cost["est_visual_tokens_naive_2fps"] / 2,
            "at least 2x cheaper than naive 2fps sampling",
            f"{cost['est_visual_tokens_all_frames']} vs {cost['est_visual_tokens_naive_2fps']}",
        )

        check(m["contact_sheet"] is not None, "contact sheet generated")
        if m["contact_sheet"]:
            sheet = out / m["contact_sheet"]
            check(sheet.exists() and sheet.stat().st_size > 5000,
                  "contact sheet is a non-trivial image")

        # ---- cursor / click detection ------------------------------------
        check(sel["candidates_found"] <= 10,
              "cursor motion does not flood scene candidates",
              f"got {sel['candidates_found']}")

        for want_t, want_x, want_y in CLICK_TARGETS:
            near = [f for f in frames if abs(f["t"] - want_t) <= TOLERANCE]
            cur = near[0].get("cursor") if near else None
            ok = (
                cur is not None
                and abs(cur["x"] - want_x) <= CURSOR_TOL_PX
                and abs(cur["y"] - want_y) <= CURSOR_TOL_PX
            )
            check(ok, f"cursor located within {CURSOR_TOL_PX}px of click at ~{want_t}s",
                  f"got {cur}, want ~({want_x},{want_y})")

        near95 = [f for f in frames if abs(f["t"] - 9.5) <= TOLERANCE]
        check(bool(near95) and near95[0].get("cursor") is None,
              "app-driven transition at ~9.5s claims no cursor",
              f"got {near95[0].get('cursor') if near95 else 'no frame'}")

        check(frames[0].get("cursor") is None, "pinned initial frame has no cursor claim")
        check(frames[-1].get("cursor") is None, "pinned final frame has no cursor claim")

        # ---- OCR pass (optional dependency, both paths must hold) --------
        ocr = m.get("ocr") or {}
        if shutil.which("tesseract"):
            check(bool(ocr.get("engine")), "ocr engine recorded when tesseract present",
                  f"got {ocr!r}")
            text = frames[-1].get("ocr_text") or ""
            check("Payment failed" in text and "500 Internal Server Error" in text,
                  "ocr captured the error toast text on the final frame",
                  f"got {text!r}")
        else:
            print("  SKIP  ocr text checks (tesseract not on PATH)")
            check(
                ocr.get("engine") is None
                and all(f.get("ocr_text") is None for f in frames),
                "ocr degrades to null without tesseract",
            )

        # ---- richer sibling artifacts + ROI ------------------------------
        check(m.get("richer_artifacts") == [],
              "no richer artifacts reported when none exist",
              f"got {m.get('richer_artifacts')!r}")

        (tmp / "trace.zip").write_bytes(b"PK\x05\x06" + b"\x00" * 18)
        fast = ["--no-cursor", "--no-ocr", "--no-contact-sheet", "--max-frames", "6"]
        rp = subprocess.run(
            [sys.executable, str(EXTRACT), str(video), "-o", str(tmp / "kf-richer"), *fast],
            capture_output=True, text=True,
        )
        rm = json.loads((tmp / "kf-richer" / "manifest.json").read_text())
        check("trace.zip" in rm.get("richer_artifacts", []),
              "sibling trace.zip is surfaced in the manifest",
              f"got {rm.get('richer_artifacts')!r}")
        check("trace" in (rp.stderr + rp.stdout).lower(),
              "sibling trace.zip is surfaced in the output")

        # scoring on a region keeps working and is recorded in the manifest
        pr = subprocess.run(
            [sys.executable, str(EXTRACT), str(video), "-o", str(tmp / "kf-roi"),
             "--roi", "300,190,920,430", *fast],
            capture_output=True, text=True,
        )
        check(pr.returncode == 0, "--roi run exits 0", pr.stderr[:300])
        pm = json.loads((tmp / "kf-roi" / "manifest.json").read_text())
        check(pm["selection"]["roi"] == [300, 190, 920, 430],
              "--roi recorded in the manifest", f"got {pm['selection'].get('roi')!r}")
        check(pm["selection"]["strategy"].startswith("scene-change"),
              "--roi run still finds scene changes",
              f"got {pm['selection']['strategy']!r}")

        bad = subprocess.run(
            [sys.executable, str(EXTRACT), str(video), "--roi", "banana"],
            capture_output=True, text=True,
        )
        check(bad.returncode != 0, "malformed --roi exits non-zero")
        big = subprocess.run(
            [sys.executable, str(EXTRACT), str(video), "--roi", "0,0,5000,5000"],
            capture_output=True, text=True,
        )
        check(big.returncode != 0, "out-of-frame --roi exits non-zero")

        # Degenerate input: a completely static video must fall back, not crash.
        static = tmp / "static.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=0x202020:s=640x360:d=4",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(static)],
            check=True,
        )
        sp = subprocess.run(
            [sys.executable, str(EXTRACT), str(static), "-o", str(tmp / "static-kf")],
            capture_output=True, text=True,
        )
        check(sp.returncode == 0, "static video does not crash the extractor", sp.stderr[:200])
        sm = json.loads((tmp / "static-kf" / "manifest.json").read_text())
        check(sm["selection"]["strategy"] == "uniform-fallback",
              "static video reports uniform-fallback", sm["selection"]["strategy"])

        # Missing file must fail loudly, not silently.
        mp = subprocess.run(
            [sys.executable, str(EXTRACT), str(tmp / "nope.mp4")],
            capture_output=True, text=True,
        )
        check(mp.returncode != 0, "missing file exits non-zero")

        # ---- URL input ---------------------------------------------------
        # Serve the fixture over localhost: a direct video URL must work end to end.
        import http.server
        import threading

        (tmp / "index.html").write_text("<html><body>not a video</body></html>")
        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(
            *a, directory=str(tmp), **kw)
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            up = subprocess.run(
                [sys.executable, str(EXTRACT),
                 f"http://127.0.0.1:{port}/checkout-bug.mp4",
                 "-o", str(tmp / "kf-url"), *fast],
                capture_output=True, text=True,
            )
            check(up.returncode == 0, "direct video url exits 0", up.stderr[:300])
            um_path = tmp / "kf-url" / "manifest.json"
            check(um_path.exists(), "url run writes manifest.json")
            if um_path.exists():
                um = json.loads(um_path.read_text())
                check(um.get("source_url") == f"http://127.0.0.1:{port}/checkout-bug.mp4",
                      "manifest records the source url",
                      f"got {um.get('source_url')!r}")
                check(all((tmp / "kf-url" / f["file"]).exists() for f in um["frames"]),
                      "url run extracts real frames")

            # An HTML page is not a video: fail loudly with guidance.
            hp = subprocess.run(
                [sys.executable, str(EXTRACT),
                 f"http://127.0.0.1:{port}/index.html", *fast],
                capture_output=True, text=True,
            )
            check(hp.returncode != 0, "html url exits non-zero")
            check("not a video" in hp.stderr.lower(),
                  "html url error says it is not a video", hp.stderr[:200])
        finally:
            httpd.shutdown()

        # Player-page links fail fast with guidance, before any network request.
        yp = subprocess.run(
            [sys.executable, str(EXTRACT), "https://www.youtube.com/watch?v=abc"],
            capture_output=True, text=True,
        )
        check(yp.returncode != 0, "player-page url exits non-zero")
        check("direct" in yp.stderr.lower(),
              "player-page error asks for a direct video link", yp.stderr[:200])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
