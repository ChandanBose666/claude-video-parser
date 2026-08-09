# Project brief — read this first

> Drop this file into your IDE and point Claude at it when you resume work on this repo.
> It carries the decisions and the reasoning behind them so you do not re-litigate them.

## What this repo is

A collection of Claude Code skills. Currently one: `claude-video-parser`.

## Problem statement (narrow — keep it narrow)

A developer receives a **screen recording of a broken UI flow that they cannot reproduce**
(from QA, a PM, a customer, or a CI artifact) and needs it turned into a written bug report.

The scope was deliberately narrowed from the original idea, which was "add video support to
Claude in the IDE." That framing was wrong for three reasons, all of which still apply:

1. **Claude has no native video input.** Images only; animated GIFs are read first-frame-only.
   Any video workflow is a frame-sampling workflow. This is a hard constraint, not a gap to fill.
2. **Someone already built the perception layer.** `jordanrendric/claude-video-vision` is a
   mature MCP plugin: ffmpeg frame extraction, audio transcription via Gemini/Whisper/OpenAI,
   YouTube support, session manifest with frame caching, real test suite and CI. Rebuilding
   frame extraction generally would be worse-than-parity work.
3. **When the flow is reproducible, video is the wrong artifact.** Playwright MCP or Chrome
   DevTools MCP give the DOM, console, and network, and can retry. A recording gives pixels.
   The skill's own SKILL.md declines the job in that case, on purpose.

What is left after removing those three is small and true: **deterministic, cheap frame
selection tuned for UI recordings, plus an opinionated report contract with anti-hallucination
guardrails.** That is the whole product. Resist re-expanding it.

## Decisions made, and why

| Decision | Reasoning | Cost of reversing |
|---|---|---|
| Zero runtime dependencies (stdlib Python + ffmpeg) | Competing tool needs Node 20+, a TS build, and either an API key or a Whisper download. Install weight is the main reason a skill does not get adopted. | Low — but you lose the main differentiator |
| No audio / transcription | Out of scope for the bug-report use case, and it is where the dependency weight lives. Compose with `claude-video-vision` if needed. | Medium |
| Seed scene threshold `0.0015`, not ffmpeg's conventional `0.3` | Measured: real UI transitions score 0.002–0.05 because only a small screen region changes. At 0.3 a screen recording yields zero candidates. | High — this is the core insight |
| Temporal non-maximum suppression over top-N-by-score | A low threshold alone produces clusters (one animation → twelve frames). NMS with `--min-gap` gives one frame per *event*, not per *changed frame*. | High |
| Contact sheet read before individual frames | One ~1k-token image usually answers the question. Error text is legible at tile resolution. Turns "view 14 images" into "view 1, then maybe 2". | Medium |
| Three-tier evidence tagging `[O]` / `[I]` / `[?]` | The failure mode of video bug reports is confident invention — asserting "the API returned 500" from a spinner. A wrong report costs more than no report. | High — this is the other half of the product |
| Explicit "Not determinable from this recording" section | Tells the developer what to go collect. Prevents the report being trusted further than it should be. | High |
| Cursor detection abstains rather than guesses | Motion-only inference cannot always distinguish a pointer from typing/caret activity. Shape gates (compact 2D glyph), a travel requirement, and a 1.2s staleness gate each kill a measured real-world false positive (697px confident-wrong from a blinking caret). Result on the validation set: every located click ≤49px, zero wrong claims, honest nulls elsewhere. | High — loosening any gate re-admits a measured failure |

## Architecture

```
skills/claude-video-parser/
  SKILL.md                        trigger description + workflow + when NOT to use
  scripts/extract_keyframes.py    the only executable. probe → score → NMS → extract → sheet
  references/
    evidence-rules.md             three-tier tagging, what video cannot show, anti-patterns
    report-template.md            the output contract, filled verbatim
tests/
  make_fixture.py                 synthesises a checkout-flow recording (Pillow + ffmpeg)
  test_extract.py                 18 assertions on selection quality, not just exit code
```

`extract_keyframes.py` pipeline:

1. `ffprobe` → duration, dimensions, fps, audio presence
2. `ffmpeg select='gt(scene,T)',metadata=print` → `[(timestamp, score)]` candidates
3. Greedy temporal NMS → ≤ `max_frames - 2` picks
4. Pin `initial-state` (~0.3s) and `final-state` (duration − 0.25s)
5. Per-frame accurate seek + lanczos downscale to `--long-edge`
6. Cursor/click estimation per scene-change frame: one ffmpeg decode of the pre-transition
   window (low-res gray + `tblend` difference frames on stdout), a regex over raw bytes finds
   changed-pixel blobs at C speed, then classify (compact glyph vs line/row/large) → walk
   backward past the UI reaction → most recent *travelling* cluster = pointer; abstain on
   spinners, carets, typing, staleness. Emitted as `cursor` in the manifest, always `[I]`.
7. `concat` + `tile` filtergraph → labelled contact sheet (`tile` consumes one stream, so
   per-image chains must be concatenated first — this is the non-obvious bit). Labels pass
   an explicit `fontfile=` to drawtext: without one, drawtext consults fontconfig, which has
   no default config on Windows ffmpeg builds and kills the whole filtergraph. Falls back to
   an unlabelled sheet if no known font exists.
8. `manifest.json` with per-frame token estimates and the naive-2fps comparison

## Known gaps / candidate next work

Ranked by value, honestly:

1. ~~**Validate on real recordings.**~~ **Done 2026-08-09** — see `tests/realworld/README.md`.
   Nine real Chromium recordings (real sites + local confounder pages; VP8 and H.264 at
   30/60fps, CRF 23–32, dark mode, cursor glides, typing). The shipped defaults survived
   unchanged: every ground-truth transition captured, bug surface within 0.24s on all nine.
   Confirmed weak spot: continuously animating page content (canvas/video) floods candidates
   and selection degrades to ~uniform sampling — bug still captured, but the token advantage
   over naive 2fps collapses. The documented `--threshold 0.01` mitigation works (77→17
   candidates). This makes region-of-interest scoring (below) the fix with evidence behind it.
2. ~~**Cursor / click detection.**~~ **Done 2026-08-09** — see the design spec in
   `docs/superpowers/specs/` and results in `tests/realworld/README.md`. Pre-transition
   motion analysis (stdlib + ffmpeg, no new dependencies), TDD'd with 21 unit checks and
   7 new end-to-end checks. On the real 8-click validation flow: every located click within
   1–49px (most ≤20px), zero wrong claims across codecs/fps/compression; abstains honestly
   on keyboard/app-driven transitions, spinners, carets, and clicks whose selected frame
   trails the click beyond the staleness gate.
3. ~~**Optional OCR pass**~~ **Done 2026-08-09 (v1.2.0)** — per-frame `ocr_text` in the
   manifest when tesseract is on PATH, null everywhere otherwise (both paths tested in the
   e2e suite; TSV parsing has its own unit suite, `tests/test_ocr_units.py`). Frames are
   upscaled 2x before recognition — measured on real recordings, that is the difference
   between missing and reading a 14px error banner. Known limit, documented in the skill:
   low-contrast colored-on-colored text (red toast on dark red card) can still be missed,
   so `ocr_text` is a grep pointer, never the evidence path. Also done the same day: the
   repo is now a Claude Code plugin marketplace (`.claude-plugin/marketplace.json` +
   `plugin.json`, `claude plugin validate . --strict` passes) — install with
   `/plugin marketplace add ChandanBose666/claude-video-parser` then
   `/plugin install claude-video-parser@claude-video-parser` (marketplace and plugin
   share one name since v1.3.1 so the catalog shows a single entry).
4. ~~**Trace preference.**~~ **Done 2026-08-09 (v1.3.0)** — `find_richer_artifacts()` detects
   sibling `trace.zip` / `*trace*.zip` / `*.har` files and the Cypress `videos/` +
   `screenshots/` layout, surfaces them in the human output, stderr, and the manifest's
   `richer_artifacts` field; SKILL.md instructs stopping and telling the user. Unit + e2e
   tested.
5. ~~**Region-of-interest scoring.**~~ **Done 2026-08-09 (v1.3.0)** — `--roi X,Y,W,H` crops
   *scoring only* (frames still extracted full-size); the score normalises over the crop, so
   in-panel changes gain sensitivity. When candidate collection floods (> 3x max-frames),
   the extractor locates the continuously-changing region (per-block change frequency over
   the whole video) and prints the exact `--roi` to retry with — suggest, don't silently
   crop. Validated on the animated-canvas recording: 76 candidates → 2, 9 frames → 4,
   7.7k → 3.4k tokens, the banner transition selected cleanly and its full error string
   captured by OCR.

All five items above are now done. Explicitly **not** planned, still: audio, YouTube, live
browser control, auto-filing issues. Candidate future work, unranked: perceptual dedup of
near-identical end-state frames (~1.7k wasted tokens worst case), auto-ROI for browser
chrome, validating OCR on non-English UIs.

## How to evaluate a change

Run `python3 tests/test_extract.py` (34 end-to-end checks: cursor localisation within 45px
on the fixture's three clicks, mandatory abstention on the app-driven transition, OCR
behaviour on both the tesseract-present and -absent paths, richer-artifact surfacing, and
`--roi` behaviour incl. loud failure on bad input), `python3 tests/test_cursor_units.py`
(21 unit checks), `python3 tests/test_ocr_units.py` (8) and `python3 tests/test_misc_units.py`
(16, ROI parsing/suggestion + artifact detection). A change is a regression if any suite
drops a check, or if
`est_visual_tokens_all_frames` on the fixture rises above ~6,000. For threshold-affecting
changes, also run the real-recording harness (`tests/realworld/`) and compare against the
results table in its README — zero wrong cursor claims is a hard requirement.

The metric that matters is not "did it extract frames" but **"did it capture every real
transition in as few frames as possible."** The test asserts the first half directly (within
300ms of four known transitions) and the second half via the 2x-cheaper-than-2fps check.
