#!/usr/bin/env python3
"""Run extract_keyframes.py on real recordings and score against ground truth.

Usage:
    python tests/realworld/eval_real.py <recordings-dir>

Expects <name>.webm / transcoded <name>-<variant>.mp4 files plus the
<name>.events.json files written by record_real_flows.py. Optionally create
compression/fps variants first, e.g.:

    ffmpeg -i saucedemo-checkout.webm -r 30 -c:v libx264 -crf 23 -pix_fmt yuv420p \
        saucedemo-checkout-30fps-crf23.mp4

The Playwright video's t=0 precedes the flow script's clock (recording starts
at page creation, the clock after first navigation), so a constant offset per
video is fitted (searched 0..5s) minimizing total distance from each
ground-truth event to its nearest extracted frame; per-event nearest-frame
error is reported at that offset. Interpret errors > ~0.5s by looking at the
contact sheet — the offset fit is crude and a visually-captured state can
still score high.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills" / "flow-recording-report" / "scripts" / "extract_keyframes.py"
)
VARIANT_MARKERS = ("-30fps-", "-60fps-")


def events_path(rec: Path, video: Path) -> Path:
    base = video.stem
    for m in VARIANT_MARKERS:
        if m in base:
            base = base.split(m)[0]
    return rec / f"{base}.events.json"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    rec = Path(sys.argv[1]).resolve()
    out = rec / "eval"
    videos = sorted(
        p for p in rec.iterdir()
        if p.suffix in (".webm", ".mp4") and events_path(rec, p).exists()
    )
    if not videos:
        print(f"no videos with matching .events.json in {rec}")
        return 1

    results = []
    for video in videos:
        outdir = out / video.name.replace(".", "_")
        p = subprocess.run(
            [sys.executable, str(SCRIPT), str(video), "-o", str(outdir), "--json"],
            capture_output=True, text=True,
        )
        if p.returncode != 0:
            results.append({"video": video.name, "error": p.stderr.strip()[:300]})
            continue
        man = json.loads(p.stdout)
        frames = [f["t"] for f in man["frames"]]
        events = json.loads(events_path(rec, video).read_text())

        best = None
        for off10 in range(0, 51):
            off = off10 / 10
            total = sum(min(abs(ft - (e["t"] + off)) for ft in frames) for e in events)
            if best is None or total < best[1]:
                best = (off, total)
        off = best[0]

        # score cursor estimates against ground-truth click coordinates: the UI
        # transition follows the click, so match each click to the nearest
        # scene-change frame in [-0.3s, +1.2s] around it
        click_rows = []
        for e in events:
            if "click" not in e:
                continue
            target = e["t"] + off
            cand = [f for f in man["frames"]
                    if f["reason"] == "scene-change" and -0.3 <= f["t"] - target <= 1.2]
            if not cand:
                click_rows.append({"click": e["event"], "frame": None,
                                   "note": "no scene-change frame near this click"})
                continue
            fr = min(cand, key=lambda f: abs(f["t"] - target))
            cur = fr.get("cursor")
            row = {"click": e["event"], "frame_t": fr["t"], "cursor": bool(cur)}
            if cur:
                row["err_px"] = round(math.hypot(cur["x"] - e["click"][0],
                                                 cur["y"] - e["click"][1]), 1)
                row["confidence"] = cur["confidence"]
            click_rows.append(row)

        results.append({
            "video": video.name,
            "strategy": man["selection"]["strategy"],
            "candidates": man["selection"]["candidates_found"],
            "frames": len(frames),
            "tokens": man["cost"]["est_visual_tokens_all_frames"],
            "naive_2fps": man["cost"]["est_visual_tokens_naive_2fps"],
            "fitted_offset_s": off,
            "events": [
                {
                    "event": e["event"],
                    "err_s": round(min(abs(ft - (e["t"] + off)) for ft in frames), 2),
                }
                for e in events
            ],
            "clicks": click_rows,
            "sheet": man["contact_sheet"],
        })

    print(json.dumps(results, indent=2))
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval-results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
