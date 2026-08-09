# Project brief — read this first

> Drop this file into your IDE and point Claude at it when you resume work on this repo.
> It carries the decisions and the reasoning behind them so you do not re-litigate them.

## What this repo is

A collection of Claude Code skills. Currently one: `flow-recording-report`.

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

## Architecture

```
skills/flow-recording-report/
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
6. `concat` + `tile` filtergraph → labelled contact sheet (`tile` consumes one stream, so
   per-image chains must be concatenated first — this is the non-obvious bit)
7. `manifest.json` with per-frame token estimates and the naive-2fps comparison

## Known gaps / candidate next work

Ranked by value, honestly:

1. **Validate on real recordings.** Everything is tuned against one synthetic fixture. Thresholds
   may need adjustment for compression noise, cursor movement, video-in-page, dark mode, and
   30fps vs 60fps captures. **This is the highest-value next step by a wide margin** — do it
   before adding any feature.
2. **Cursor / click detection.** Locating the pointer at each transition would give "the user
   clicked *here*", which is the single biggest thing missing from the report.
3. **Optional OCR pass** (tesseract, degrade gracefully if absent). Captures error text from
   frames never sent to the model. Cheap signal per token. Was scoped out of v1 deliberately.
4. **Trace preference.** If a sibling `trace.zip` / `.har` / Cypress `screenshots/` exists next
   to the video, detect it and tell the user to use that instead. Currently only prose guidance.
5. **Region-of-interest scoring.** Crop chrome/nav before scene scoring so the score reflects
   the content area. Would raise sensitivity on subtle in-panel changes.

Explicitly **not** planned: audio, YouTube, live browser control, auto-filing issues.

## How to evaluate a change

Run `python3 tests/test_extract.py`. A change is a regression if it drops below 18 passing
checks, or if `est_visual_tokens_all_frames` on the fixture rises above ~6,000.

The metric that matters is not "did it extract frames" but **"did it capture every real
transition in as few frames as possible."** The test asserts the first half directly (within
300ms of four known transitions) and the second half via the 2x-cheaper-than-2fps check.
