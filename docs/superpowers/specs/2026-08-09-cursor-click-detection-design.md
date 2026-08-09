# Cursor / click detection — design

Date: 2026-08-09. Status: approved in principle by the user ("go ahead with
cursor/click detection"); design details decided autonomously per this doc.

## Goal

For each scene-change frame the extractor selects, estimate where the pointer
was immediately before the UI reacted, so the bug report can say "the user
clicked *here*" — the single biggest thing missing from the report.

## Constraint

Stdlib Python + ffmpeg only. This is the skill's main differentiator and is
non-negotiable. No numpy, no OpenCV, no Pillow at runtime.

## Approaches considered

1. **Pre-transition motion tracking (chosen).** In a short window before each
   transition, diff consecutive low-res grayscale frames. A moving cursor is a
   small coherent blob of change; the last small-blob position before the UI
   reaction approximates the click point. No assumption about cursor shape,
   works with recorder-drawn fake cursors, abstains honestly when there is no
   pointer (keyboard-driven transitions, headless recordings).
2. Cursor template matching (rejected): OS/theme/DPI/custom-cursor variance,
   expensive without numpy, silently wrong when the template mismatches.
3. Click-overlay (halo) detection (rejected): specific to recorders that draw
   click circles; could be an additive signal later.

## Detection pipeline (per scene-change frame at time t)

1. One ffmpeg call decodes the window `[t - 1.5s, t + 0.15s]` at ~10 fps,
   scaled to width 320, `format=gray`, through `tblend=all_mode=difference`,
   output as raw gray8 frames on stdout. Each output frame n is |frame n −
   frame n−1|; the first is dropped.
2. Python scans each diff frame for above-threshold pixels using a compiled
   regex over the raw bytes (`re` finds runs of bytes ≥ threshold at C speed —
   no per-pixel Python loop). Collect changed-pixel count, centroid, bbox.
3. Classify each diff frame: `still` (no change), `cursor-like` (small count,
   compact bbox), `large` (anything bigger: scroll, page transition, video).
4. Walk backward from t: skip the `large` frames that are the UI reaction
   itself, take the most recent run of `cursor-like` frames. Its last centroid,
   scaled to source resolution, is the estimate.
5. Confidence: `high` = ≥3-frame coherent trajectory (successive centroids
   near each other) ending ≤0.5s before t; `medium` = shorter/staler evidence
   (≤1.2s); otherwise no estimate (`null`). Never guess.

Classification thresholds (tunable constants, validated by tests): diff pixel
value ≥ 26; cursor-like = ≤0.8% of pixels changed and bbox diagonal ≤15% of
frame diagonal.

Runs only for `scene-change` frames — pinned initial/final frames and
uniform-fallback frames are not transitions. `--no-cursor` disables the pass;
`--cursor-window` (default 1.5s) sizes the look-back.

## Output contract

- `manifest.json` per frame: `"cursor": null` or
  `{"x", "y", "norm_x", "norm_y", "detected_at_t", "confidence"}` (source-video
  pixel coords; norm in 0–1). A manifest note states the basis: inferred from
  pre-transition motion — always `[I]` evidence, never `[O]`.
- Human output appends `cursor≈(x,y)` to frame lines when present.
- `evidence-rules.md`: cursor estimates are always `[I]`; absence of an
  estimate must not be invented.
- `report-template.md`: optional per-step line for the inferred click position.

## Testing

- Pure functions (`scan_diff_frame`, classification, backward walk) get unit
  tests on synthetic byte buffers — no video needed.
- `make_fixture.py` gains a drawn cursor that glides to each button in the
  ~0.9s before each transition and rests there; button centers are exported as
  ground truth. End-to-end test asserts estimates within tolerance for ≥3 of 4
  transitions, null for pinned frames, and no new scene candidates from cursor
  motion (regression on the existing 18 checks).
- Real-world: a richer recorded flow (more clicks, scroll, dropdown) logs
  ground-truth click coordinates; `eval_real.py` reports pixel error.

## Risks

- Typing-driven transitions produce no estimate — correct behavior, documented.
- A cursor resting motionless > window before a click yields no estimate —
  acceptable; medium-confidence stale evidence covers the common case.
- Highly animated pages classify everything `large` → abstains. Consistent
  with the validated flooding limitation.
