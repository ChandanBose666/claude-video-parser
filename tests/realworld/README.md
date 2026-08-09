# Real-recording validation harness

Dev-time tooling that validates `extract_keyframes.py` against **real browser
recordings** instead of the synthetic Pillow fixture. Not part of the skill, not
run in CI (needs Playwright + network).

```powershell
python -m pip install playwright
python -m playwright install chromium

python tests\realworld\record_real_flows.py recordings
# optional: transcode fps/compression variants (see eval_real.py docstring)
python tests\realworld\eval_real.py recordings
```

`record_real_flows.py` drives four flows in a real Chromium with video
recording on, a visible injected cursor, and ground-truth event timestamps
logged per flow. `eval_real.py` runs the extractor on every recording, fits the
video-start/clock offset, and reports the nearest-frame error per ground-truth
event plus candidate/frame/token counts.

## Results — 2026-08-09 (ffmpeg 9.0, Chromium 151, defaults untouched)

9 videos: 4 raw VP8 `.webm` + H.264 variants at 30fps CRF 23, 60fps CRF 32,
30fps CRF 28. Full numbers in the eval output; summary:

| Flow | Confounders | Bug-surface error | Verdict |
|---|---|---|---|
| saucedemo checkout (8 events) | real site, page navs, cursor glides, form error | 0.01–0.09s | all 8 states on the sheet |
| saucedemo locked-out login | char-by-char typing, error banner | 0.24s | clean |
| spinner-dark | dark mode, CSS spinner, low contrast | 0.02–0.03s | spinner did **not** flood (3 candidates) |
| video-in-page | continuously animating canvas | 0.01–0.08s | floods candidates (66–77) — see below |

Findings:

1. **The shipped defaults survive real recordings unchanged.** Seed threshold
   `0.0015` + NMS captured every ground-truth transition on every variant;
   compression (CRF 23→32), frame rate (30→60), codec (VP8/H.264) and dark
   mode did not shift selection meaningfully.
2. **Continuous in-page animation is the confirmed weak spot.** The canvas page
   produced 66–77 candidates and selection degraded to ~uniform sampling; the
   bug surface was still captured, but the token advantage over naive 2 fps
   collapsed (8.5k vs 9.3k). The SKILL.md guidance to raise `--threshold` to
   `0.01` works: 77→17 candidates, 10→7 frames, bug surface still captured.
3. Cursor movement and typing produced no junk candidates at default threshold.
4. End-state frames duplicate when the recording lingers after the bug (three
   near-identical error frames on the checkout flow) — cosmetic, ~1.7k wasted
   tokens worst case.
