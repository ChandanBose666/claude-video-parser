# UI Flow Regression — Pay button leaves user stranded on Payment step after server error

**Source** `checkout-bug.mp4` · 12.5s · 1280x720 · 6 keyframes extracted
**Analysed** 2026-08-09 · frames in `out/` · overview `contact-sheet.jpg`
**Evidence tier legend** `[O]` observed in frame · `[I]` inferred · `[?]` not determinable from video

> This is a worked example produced from `tests/fixtures/checkout-bug.mp4` to show the output
> contract. Every claim below is tagged; note how much of the report is `[?]`. That is correct
> and intentional — it is what a screen recording can honestly support.

---

## Summary

Checkout progresses normally through Cart → Address → Payment, but submitting payment shows a
spinner for ~2.2s and then a `Payment failed` error. The user is left on the Payment step with
the form still populated and no recovery path offered.

## Expected behaviour

Clicking **Pay $188.00** should advance to step 4 (Done) and show an order confirmation.

## Observed flow

| # | Time | Frame | State on screen |
|---|---|---|---|
| 1 | 00:00.25 | `frame-01.jpg` | `[O]` Step 1 Cart. Two line items, total `$188.00`, **Continue** enabled |
| 2 | 00:02.50 | `frame-02.jpg` | `[O]` Step 2 Address. Four empty fields, **Continue** enabled |
| 3 | 00:05.00 | `frame-03.jpg` | `[O]` Step 3 Payment. Card number / Expiry / CVC empty, **Pay $188.00** enabled |
| 4 | 00:07.30 | `frame-04.jpg` | `[O]` Pay button dimmed, circular spinner rendered inside the panel |
| 5 | 00:09.50 | `frame-05.jpg` | `[O]` Red error banner top-right, spinner gone, Pay button re-enabled |
| 6 | 00:12.25 | `frame-06.jpg` | `[O]` Unchanged from frame 05. Still on step 3. Recording ends |

## Divergence point

**Between `frame-04` (00:07.30) and `frame-05` (00:09.50).**

`[O]` At 00:07.30 the Pay button is dimmed and a spinner is present — the app is in a pending
state. At 00:09.50 the spinner is gone, the Pay button is re-enabled, and a red error banner
has appeared. The step rail still shows step 3 active; it never advances to step 4.

`[I]` An asynchronous submit was initiated, remained pending, and resolved into a failure path
rather than a navigation.

`[O]` Measured pending duration: spinner first seen 00:07.30, absent by 00:09.50 = **≤ 2.2s**.
`[I]` 2.2s is short for a network timeout and long for a client-side validation rejection,
which points at a server response rather than a timeout or a local guard.

`[I]` User appears to have clicked near **(1087, 561)** — the **Pay $188.00** button region
(cursor estimate, high confidence, `frame-04`). The spinner→error transition at 00:09.50
carries no cursor estimate, consistent with an app-driven change rather than a second click.

## On-screen text captured

```
Payment failed                                    [O] frame-05, frame-06
500 Internal Server Error - ref 8c1f42            [O] frame-05, frame-06
```

`[O]` `ref 8c1f42` appears to be a correlation identifier surfaced to the user. It is the most
directly actionable item in this report — grep the server logs for it before anything else.

Both strings were flagged by the manifest's `ocr_text` for frames 05–06 and confirmed by
reading the frames (OCR alone is a pointer, not a quote — see the skill's evidence rules).

## Environment observed

| | | Tier |
|---|---|---|
| URL / route | `https://shop.acme.io/checkout/payment` | `[O]` address bar, frames 03–06 |
| Route history | `/checkout/cart` → `/checkout/address` → `/checkout/payment` | `[O]` frames 01–03 |
| Viewport | 1280x720 recording | `[I]` recording dimensions, not necessarily the viewport |
| Browser | macOS-style traffic-light window controls | `[I]` window chrome only |
| OS | likely macOS | `[I]` window chrome only |
| Logged-in user / role | — | `[?]` |
| Build / version | — | `[?]` |

## Not determinable from this recording

- `[?]` The actual HTTP status of the submit request. The banner *displays* `500`, but whether
  that reflects the real response status or a generic client-side fallback string is unknown.
- `[?]` Response body, headers, or whether the payment was charged server-side despite the
  error. **This is the highest-risk unknown here** — a failed UI with a successful charge is a
  materially different bug.
- `[?]` Console errors or unhandled rejections.
- `[?]` Which component renders the banner, and which module issues the submit.
- `[?]` Whether it reproduces on retry — the recording ends without a second attempt.
- `[?]` Whether card fields were populated. They render empty in frame 03 and the recording never
  shows them being filled, which may mean the reporter cut that part or that submission
  proceeded with an empty form.

## Hypotheses

1. **The payment service returned a genuine 500 and the client surfaced it verbatim.**
   Disprove by: grep server logs for `8c1f42`; if no matching request exists, the string is
   client-generated and the real failure is upstream of the service.
2. **Submit fired with an empty/invalid card form because client-side validation is missing.**
   Disprove by: attempt the same flow with the form empty and watch the network tab — if no
   request is sent, validation is working and this hypothesis is dead.
3. **The error is handled but navigation-on-success is unconditional elsewhere**, leaving the
   user stranded rather than offering retry. Disprove by: read the submit handler's catch block —
   if it already renders a retry affordance, the bug is that it did not render here.

These are hypotheses about mechanism. The recording establishes ordering only.

## Reproduction steps `[I]`

Inferred from the recording. Not verified.

1. Add `Mechanical keyboard` ($149.00) and `USB-C hub` ($39.00) to cart — total `$188.00`
2. Continue to Address
3. Continue to Payment
4. Click **Pay $188.00**

**Expected:** advance to step 4 with an order confirmation
**Actual:** ~2.2s spinner, then `Payment failed / 500 Internal Server Error - ref 8c1f42`;
remains on step 3 with no retry guidance

## To confirm this, please provide

1. Server-side log lines matching `8c1f42` — resolves hypothesis 1 immediately
2. Browser console output for the same flow
3. Network HAR, specifically the submit request's status and response body
4. **Whether the customer was charged** — check the payment provider dashboard for this session
5. Whether it reproduces on retry, and with a different card/account
6. Build SHA or deploy timestamp of the environment in the recording
