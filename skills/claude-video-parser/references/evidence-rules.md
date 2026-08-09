# Evidence rules

A screen recording is a sequence of pixels. It is a far weaker evidence source than it feels
like, because it *looks* complete. These rules exist to stop a plausible-sounding report from
sending a developer down the wrong path.

## The three-tier rule

Every claim in the report is tagged as exactly one of:

- **OBSERVED** — visible in a specific frame. Cite the frame index. `The button is greyed out (frame 04).`
- **INFERRED** — a reasonable reading of observed frames, but not itself visible. `The request appears to have been in flight for ~2.2s (spinner present frames 04-05).`
- **UNKNOWN** — not determinable from video. Say so explicitly.

If you cannot tag a sentence, delete the sentence.

## What a screen recording physically cannot show

State each of these as UNKNOWN unless the user supplied it separately. Do not soften them
into hedged assertions.

| Not visible in video | Why it matters |
|---|---|
| HTTP status codes, request/response bodies, headers | "The API returned 500" is a guess unless the status is rendered on screen |
| Console errors, unhandled promise rejections, stack traces | The most common actual root cause, and entirely invisible |
| Which DOM element / component / selector is involved | Needed to locate the code; a screenshot cannot give it |
| Application or Redux/store state | A UI can render correctly over corrupt state, and vice versa |
| Whether the failure is deterministic | One recording is n=1 |
| Feature flags, A/B bucket, auth role, tenant | Changes which code path executed |
| Build SHA, app version, deploy time | Determines whether the bug is already fixed |
| Anything the user did off-camera | Another tab, devtools, a prior session |

**If on-screen text states one of these** — an error toast reading `500 Internal Server Error`,
a rendered error boundary, a visible request ID — that is OBSERVED. Quote it exactly, character
for character, and cite the frame. Do not paraphrase error strings; the exact string is often
greppable in the codebase and is the single most valuable thing in the report.

## Cursor estimates are always INFERRED

When the manifest carries a `cursor` entry for a frame, it was derived from pre-transition
motion analysis — the pointer was never read directly. Cite it as INFERRED with its
confidence: `The user appears to have clicked near (1105, 562) — the "Continue" button
region (cursor estimate, high confidence, frame 04).` When `cursor` is null, say nothing
about where the user clicked; null means no reliable estimate, not "no click". Never
promote a cursor estimate into an OBSERVED claim, and never invent a click position for a
frame that has no estimate.

## OCR text is a pointer, not a quote

`ocr_text` in the manifest is machine-read and can contain recognition errors — dropped
characters, wrong glyphs, clipped line starts. Use it to find which frame to look at.
Before quoting a string as OBSERVED, read it off the frame itself; if you quote from OCR
without visual confirmation, tag it `[I]` and say `via OCR`. Absence of text in `ocr_text`
is never evidence of absence on screen — low-contrast text is routinely missed.

## Correlation is not causation

The recording shows ordering, not mechanism. `The spinner appeared, then the error appeared`
is OBSERVED. `The request timed out, causing the error` is a hypothesis about mechanism and
belongs in a clearly-labelled Hypotheses section, ranked, with the cheapest disconfirming
check named for each.

Write hypotheses as: **claim — what would disprove it in under 5 minutes.**

## Timestamps are evidence

Durations are measurable from the video and are often the most actionable number in the report.
A spinner present from 00:07.3 to 00:09.5 is a **2.2 second** wait — that distinguishes a
client-side timeout from a slow query from an immediate rejection. Always state measured
durations with their frame citations.

## Reading a frozen or static recording

If the extractor reports `uniform-fallback` with `candidates_found: 0`, nothing on screen
changed. That is itself a finding — a hang, a frozen render, or a recording that missed the
event. Report it as such. Do not invent a flow from six identical frames.

## Anti-patterns

- Inventing UI text that is too small to read. Say `text illegible at this resolution, re-run with --long-edge 1568`.
- Asserting a component or file name from repo knowledge and presenting it as read from the video.
- Reporting "the page did not load" when the frames show a loaded page with one broken widget.
- Describing every frame in sequence. The report is about the divergence, not a narration.
- Padding the report to look thorough. An honest four-line report beats a padded page.
