---
name: flow-recording-report
description: Use when the user has a screen recording, screen capture, Loom, .mp4/.mov/.webm/.mkv/.gif, or CI test video of a UI flow that is broken, and wants it turned into a written bug report. Triggers on "QA sent me a video", "here's a recording of the bug", "watch this screen capture", "a customer sent a screen recording", "turn this video into a ticket", "what breaks in this recording". Do NOT use when the app is running locally and reproducible — drive the browser directly instead.
license: MIT
---

# Flow Recording → Bug Report

Turn a screen recording of a broken UI flow into a structured, evidence-bounded bug report.

## When NOT to use this

Say so and stop, rather than proceeding, if any of these hold:

- **The user can reproduce the bug locally.** A browser automation tool (Playwright MCP, Chrome DevTools MCP, Puppeteer) beats a recording on every axis: it sees the DOM, console, and network, and it can retry. A video is pixels. Recommend that instead.
- **A Playwright/Cypress trace exists.** `trace.zip`, `.har`, or a Cypress `screenshots/` + `videos/` pair ships with structured data. Read the trace. The video is the fallback, not the primary.
- **The recording is longer than ~10 minutes** and the user has not said where in it the bug occurs. Ask for a timestamp range first. Analysing 10 minutes of pixels to find a 4-second bug is waste.

Being upfront about this is more useful than producing a mediocre report from a bad input.

## Workflow

### 1. Locate the video and confirm scope

Confirm the file exists and get its duration before anything else:

```bash
ffprobe -v error -show_entries format=duration:stream=width,height -of default=nw=1 <video>
```

If the user has not said what *should* have happened, ask now — one question. A bug report without an expected-behaviour statement is a description, not a report. If they are unavailable, proceed and mark the expected behaviour as `NOT PROVIDED` in the output.

### 2. Extract keyframes

```bash
python3 scripts/extract_keyframes.py <video> -o <outdir>
```

This writes `<outdir>/` containing `frame-NN.jpg`, `contact-sheet.jpg`, and `manifest.json`.
Stdlib Python + ffmpeg only. No API keys, no model downloads, no MCP server.

Useful flags:

| Flag | When to reach for it |
|---|---|
| `--max-frames N` | Default 14. Raise for a long multi-page flow, lower for a 10s clip. |
| `--threshold X` | Default `0.0015`. Raise to `0.01` if a noisy recording (video content, animated background) yields junk frames. Lower to `0.0005` if a genuinely subtle change was missed. |
| `--min-gap S` | Default 0.5s. Raise to 1.5 if one long animation dominates the selection. |
| `--long-edge N` | Default 1024 (~800 visual tokens/frame). Raise to 1568 only when on-screen text is unreadable. |

**Why these defaults matter.** ffmpeg's conventional scene threshold is `0.3`, tuned for film cuts. Measured UI transitions in screen recordings score **0.002–0.05** — a toast appearing changes maybe 4% of the frame. At `0.3` a screen recording returns zero scene changes, which is why most video tooling gives up and samples at a fixed fps instead. This script seeds low and then applies temporal non-maximum suppression, so a 400ms spinner animation contributes one frame rather than twelve.

### 3. Read the contact sheet FIRST

View `contact-sheet.jpg` before any individual frame. It is one image (~1–1.5k visual tokens) showing every keyframe with its index and timestamp. For most bugs it is sufficient on its own.

Only then pull individual full-resolution frames, and only the ones you need — typically the frame before the divergence and the frame after it. Do not view all frames by default. Read `manifest.json` for exact timestamps and per-frame token cost.

If text in the contact sheet is unreadable, re-run with `--long-edge 1568 --sheet-tile 640` rather than opening every frame.

### 4. Write the report

Use `references/report-template.md` verbatim as the structure. Fill every section; write `Not determinable from video` rather than deleting a section — the absences are diagnostic.

Before writing, read `references/evidence-rules.md`. It is short and it is the part of this skill that matters most. A confident, wrong bug report costs a developer more time than no bug report.

### 5. Deliver

Write the report to `<outdir>/BUG-REPORT.md` and hand the user:

- the report path,
- the contact sheet path,
- the frame indices that carry the evidence.

Offer, in one line, to file it as a GitHub issue via `gh issue create` — do not do it unprompted.

## Composition

If the `claude-video-vision` MCP server is available in the session, prefer its
`video_analyze` / `video_detail` tools for **drill-down into a specific moment** — it has
per-segment variable-fps extraction and audio transcription, which this skill deliberately
does not. Use this skill's extractor for the initial pass and its report contract for the
output. The two are complementary: that plugin is a perception layer, this is a reporting
contract.
