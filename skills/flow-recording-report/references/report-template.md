# UI Flow Regression — `<short title, imperative, names the broken step>`

**Source** `<video filename>` · `<duration>` · `<WxH>` · `<N>` keyframes extracted
**Analysed** `<date>` · frames in `<outdir>/` · overview `contact-sheet.jpg`
**Evidence tier legend** `[O]` observed in frame · `[I]` inferred · `[?]` not determinable from video

---

## Summary

One or two sentences. What flow, which step, what happened instead. No preamble.

## Expected behaviour

`<what the user said should happen>` — or `NOT PROVIDED — reporter did not state expected behaviour.`

## Observed flow

| # | Time | Frame | State on screen |
|---|---|---|---|
| 1 | 00:00.25 | `frame-01.jpg` | |
| 2 | | | |

Keep this to the steps that matter. Do not narrate frames that show no change.

## Divergence point

**Between `frame-NN` (`<time>`) and `frame-NN` (`<time>`).**

`[O]` What is visibly different between those two frames.
`[I]` What that difference implies about what the app was doing.

Measured durations, if any: `[O] spinner present <t1> → <t2> = <N.N>s`

## On-screen text captured

Quote exactly, character for character. Errors, toasts, banners, status text, visible IDs.

```
<exact string>          [O] frame-NN
```

If nothing legible: `None legible.` If text is present but too small:
`Text present in frame-NN but illegible at 1024px — re-run with --long-edge 1568.`

## Environment observed

| | | Tier |
|---|---|---|
| URL / route | | `[O]` if the address bar is visible |
| Viewport | | `[I]` from frame dimensions — this is the *recording* size, not necessarily the viewport |
| Browser | | `[I]` from window chrome, or `[?]` |
| OS | | `[I]` from window chrome, or `[?]` |
| Logged-in user / role | | usually `[?]` |
| Build / version | | usually `[?]` |

## Not determinable from this recording

Explicit list. Do not omit this section — it tells the developer what to go collect, and it
is the section that prevents the report from being trusted further than it should be.

- `[?]` HTTP status codes and response bodies
- `[?]` Console errors / stack traces
- `[?]` Component or selector involved
- `[?]` Whether this reproduces consistently
- `[?]` <anything else specific to this recording>

## Hypotheses

Ranked. Each one names the cheapest check that would disprove it.

1. **`<claim>`** — disprove by: `<a check that takes under 5 minutes>`
2. **`<claim>`** — disprove by: `<...>`

Mark clearly: these are hypotheses about mechanism. The recording shows ordering only.

## Reproduction steps `[I]`

Inferred from the recording. Not verified.

1.
2.
3.

**Expected:** `<...>`
**Actual:** `<...>`

## To confirm this, please provide

Ordered by value per unit of reporter effort.

1. Browser console output for the same flow (catches the actual exception)
2. Network tab HAR, or the failing request's status + response body
3. Whether it reproduces on retry, and on another account/browser
4. Build SHA or deploy timestamp
5. A Playwright trace if this path is covered by an existing test
