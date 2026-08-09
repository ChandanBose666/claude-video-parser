# claude-skills

Skills for Claude Code / Claude Agent SDK. One skill per directory under `skills/`.

| Skill | What it does | Status |
|---|---|---|
| [`flow-recording-report`](skills/flow-recording-report) | Turns a screen recording of a broken UI flow into a structured, evidence-bounded bug report — keyframes, cursor/click inference, optional OCR, ROI scoring, trace detection | v1.3.0 |

---

## flow-recording-report

### The problem it actually solves

Claude has **no native video input** — the [vision docs](https://platform.claude.com/docs/en/build-with-claude/vision) are images only, and even animated GIFs are read first-frame-only. So any "video" workflow is really a frame-sampling workflow, and the naive version is expensive: a 45-second recording at 2 fps is 90 frames × ~1,300 visual tokens ≈ **117k tokens** to describe one bug.

This skill is for the case where you **cannot reproduce the flow yourself** — a Loom from QA, a customer's screen capture, a video artifact from a CI failure. If the app is running on your machine, drive the browser with Playwright MCP or Chrome DevTools MCP instead; the DOM, console, and network beat pixels on every axis. The skill says so itself and declines.

### Two things it does differently

**1. Scene thresholds calibrated for UI, not film.**

ffmpeg's conventional scene-change threshold is `0.3`, tuned for hard cuts in video. Measured on a screen recording of a checkout flow, real UI transitions score:

| Transition | scene score |
|---|---|
| Cart → Address page | 0.0209 |
| Address → Payment page | 0.0133 |
| Button press → spinner | 0.0089 |
| Spinner → error toast | 0.0155 |

At `0.3`, a screen recording returns **zero** scene changes — which is why most video tooling abandons scene detection and falls back to fixed-fps sampling. This extractor seeds at `0.0015` and then applies **temporal non-maximum suppression**: candidates are ranked by score and greedily accepted only if they are ≥ `--min-gap` seconds from an already-accepted frame. A 400ms spinner animation contributes one frame instead of twelve.

Result on the bundled fixture — a 12.5s recording with six distinct states:

```
strategy    scene-change + temporal-NMS  (5 candidates -> 6 frames)
est. cost   ~4,662 visual tokens for all frames (naive 2fps would be ~19,425)
```

Six frames, every real transition captured, ~4x cheaper.

**2. A labelled contact sheet, read first.**

The extractor emits `contact-sheet.jpg`: every keyframe in one grid, each tile labelled with index, timestamp, and selection reason. That is **one image, ~1k visual tokens**, and for most bugs it is sufficient on its own — on the fixture, the error string `500 Internal Server Error - ref 8c1f42` is legible at contact-sheet resolution. Individual full-resolution frames are pulled only when needed. Binary search, not a dump.

### What it deliberately does not do

No audio, no transcription, no YouTube, no MCP server, no API keys, no model downloads. Stdlib Python + ffmpeg. If you need per-segment variable-fps extraction or audio, compose with [`claude-video-vision`](https://github.com/jordanrendric/claude-video-vision) — that plugin is a perception layer, this is a reporting contract, and they stack.

### The reporting contract

The other half of the skill is `references/evidence-rules.md`, which forces every claim into one of three tiers — `[O]` observed in a cited frame, `[I]` inferred, `[?]` not determinable — and requires an explicit **"Not determinable from this recording"** section listing what video physically cannot show: HTTP status codes, console errors, the DOM selector involved, application state, whether it reproduces.

That section is the point. A screen recording looks like complete evidence and is not, and a confident wrong bug report costs a developer more time than no bug report.

---

## Install

**Via the Claude Code plugin marketplace** (recommended — works in the CLI and the IDE
extensions; keeps the skill updatable):

```
/plugin marketplace add ChandanBose666/claude-video-parser
/plugin install flow-recording-report@claude-video-parser
```

Restart Claude Code and confirm with `/plugin` or by asking Claude what skills it has.

**Via install script** (copies the skill into `~/.claude/skills/`):

```bash
# macOS / Linux
./scripts/install.sh

# Windows PowerShell
.\scripts\install.ps1
```

Pass `--project` / `-Project` to install into `.claude/skills/` of the current repo instead.

**Manual:** copy `skills/flow-recording-report/` to `~/.claude/skills/`.

### Requirements

- `ffmpeg` and `ffprobe` on PATH
  - macOS `brew install ffmpeg` · Debian/Ubuntu `sudo apt install ffmpeg` · Windows `winget install Gyan.FFmpeg`
- Python 3.10+ (stdlib only)
- `tesseract` — **optional**, enables the per-frame OCR pass (grep-able frame text in the manifest)
  - macOS `brew install tesseract` · Debian/Ubuntu `sudo apt install tesseract-ocr` · Windows `winget install UB-Mannheim.TesseractOCR`
- Pillow — **tests only**, not needed at runtime

## Use

Once installed, just tell Claude:

> QA sent me this recording of checkout breaking — `./bug.mp4`. Expected: clicking Pay goes to the confirmation page.

Or invoke the extractor directly:

```bash
python3 skills/flow-recording-report/scripts/extract_keyframes.py bug.mp4 -o ./out
python3 skills/flow-recording-report/scripts/extract_keyframes.py bug.mp4 --json   # machine-readable
```

## Test

```bash
python3 -m pip install pillow
python3 tests/test_extract.py
```

Generates a synthetic checkout-flow video (with a moving cursor) where only a small region changes between steps — the exact case naive scene detection fails on — then asserts the extractor lands within 300ms of all four known transitions, locates the cursor within 45px of each click, abstains on the app-driven transition, captures the error toast via OCR when tesseract is present, pins first/last state, beats 2fps sampling by ≥2x, falls back gracefully on a static video, and exits non-zero on a missing file. Plus `tests/test_cursor_units.py` and `tests/test_ocr_units.py` for the detection primitives, and a real-recording validation harness in `tests/realworld/`. No test framework.

## Licence

MIT
