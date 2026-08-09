#!/usr/bin/env python3
"""
extract_keyframes.py — deterministic scene-change keyframe extraction for UI screen recordings.

Why not just sample at N fps:
  A 45s screen recording at 2 fps is 90 frames. At ~1300 visual tokens each that is
  ~117k tokens to describe one bug. Most of those frames are byte-identical to their
  neighbour because a UI is static between interactions.

Why not ffmpeg's default scene threshold (0.3):
  ffmpeg's scene score is a whole-frame difference metric. In a screen recording only a
  small region changes (a toast appears, a button turns grey, a row disappears), so real
  UI transitions routinely score 0.02-0.12. A 0.3 threshold finds almost nothing on a UI
  recording, which is why naive scene detection is usually abandoned for fps sampling.

What this does instead:
  1. Collect candidates with a deliberately LOW threshold (default 0.0015) so subtle UI
     changes survive.
  2. Rank candidates by scene score and apply temporal non-maximum suppression, so a
     single 400ms animation contributes one frame instead of twelve.
  3. Always pin a frame near the start and near the end (initial and final state).
  4. Emit a labelled contact sheet so a model can orient on ONE image (~1-2k tokens)
     before requesting individual full-resolution frames.

Stdlib only. Requires ffmpeg + ffprobe on PATH.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"}


# --------------------------------------------------------------------------- utils


def die(msg: str, code: int = 1) -> "None":
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def require_binaries() -> None:
    missing = [b for b in ("ffmpeg", "ffprobe") if shutil.which(b) is None]
    if missing:
        die(
            f"missing required binary/binaries: {', '.join(missing)}. "
            "Install ffmpeg (macOS: brew install ffmpeg | "
            "Debian/Ubuntu: sudo apt install ffmpeg | "
            "Windows: winget install Gyan.FFmpeg)"
        )


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, errors="replace", **kw
    )


def hhmmss(t: float) -> str:
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{m:02d}:{s:06.3f}"


def visual_tokens(w: int, h: int) -> int:
    """Claude bills images in 28x28 patches. See platform.claude.com vision docs."""
    return math.ceil(w / 28) * math.ceil(h / 28)


# ---------------------------------------------------------------------- ffprobe


@dataclass
class VideoMeta:
    path: str
    duration_s: float
    width: int
    height: int
    fps: float
    codec: str
    has_audio: bool
    size_mb: float


def probe(path: Path) -> VideoMeta:
    p = run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
    )
    if p.returncode != 0:
        die(f"ffprobe failed on {path.name}: {p.stderr.strip()[:400]}")
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        die(f"ffprobe returned unparseable JSON for {path.name}")

    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v is None:
        die(f"{path.name} contains no video stream")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or v.get("duration") or 0.0)
    if duration <= 0:
        die(f"could not determine duration of {path.name} (got {duration})")

    rate = v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"
    try:
        num, den = (float(x) for x in rate.split("/"))
        fps = num / den if den else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0

    return VideoMeta(
        path=str(path),
        duration_s=duration,
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        fps=round(fps, 3),
        codec=str(v.get("codec_name") or "unknown"),
        has_audio=a is not None,
        size_mb=round(int(fmt.get("size") or 0) / (1024 * 1024), 2),
    )


# ------------------------------------------------------------------ scene scores

# ffmpeg's metadata=print emits pairs of lines:
#   frame:0    pts:7507    pts_time:0.500467
#   lavfi.scene_score=0.083103
_FRAME_RE = re.compile(r"pts_time:([0-9]*\.?[0-9]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9]*\.?[0-9]+)")


def scene_candidates(path: Path, seed_threshold: float) -> list[tuple[float, float]]:
    """Return [(timestamp_seconds, scene_score)] for every frame above seed_threshold."""
    p = run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error",
            "-i", str(path),
            "-an", "-sn",
            "-filter_complex",
            f"select='gt(scene,{seed_threshold})',metadata=print:file=-",
            "-f", "null", "-",
        ]
    )
    # metadata=print:file=- writes to stdout; some builds interleave into stderr.
    blob = (p.stdout or "") + "\n" + (p.stderr or "")

    out: list[tuple[float, float]] = []
    pending_t: float | None = None
    for line in blob.splitlines():
        m = _FRAME_RE.search(line)
        if m:
            pending_t = float(m.group(1))
            continue
        m = _SCORE_RE.search(line)
        if m and pending_t is not None:
            out.append((pending_t, float(m.group(1))))
            pending_t = None
    return out


def suppress(
    candidates: list[tuple[float, float]],
    max_frames: int,
    min_gap: float,
    min_score: float,
) -> list[tuple[float, float]]:
    """Greedy temporal non-maximum suppression: strongest change wins its neighbourhood."""
    kept: list[tuple[float, float]] = []
    for t, score in sorted(candidates, key=lambda c: -c[1]):
        if score < min_score:
            break
        if any(abs(t - kt) < min_gap for kt, _ in kept):
            continue
        kept.append((t, score))
        if len(kept) >= max_frames:
            break
    return sorted(kept)


def uniform_fallback(duration: float, n: int) -> list[tuple[float, float]]:
    if n <= 1:
        return [(duration / 2, 0.0)]
    step = duration / (n + 1)
    return [(step * (i + 1), 0.0) for i in range(n)]


# ------------------------------------------------------------ cursor detection

# A click is inferred from motion: in the seconds before a UI transition, a moving
# pointer is a small compact blob of inter-frame change, and the UI reacts where the
# motion stopped. In-place change that never travels (spinner, caret) is not a pointer,
# and an estimate is only reported with recent evidence — never guessed.
# Constants are in terms of the low-res gray analysis frames.
CURSOR_DIFF_MIN = 26          # gray8 inter-frame delta that counts as change
CURSOR_SCAN_W = 320           # analysis frame width
CURSOR_FPS = 10               # analysis sample rate
CURSOR_MAX_AREA = 0.008       # blob bigger than this fraction of pixels: not a cursor
CURSOR_MAX_DIAG = 0.15        # blob bbox diagonal beyond this fraction: not a cursor
CURSOR_MIN_TRAVEL = 0.02      # cluster must move at least this fraction of the diagonal:
                              # spinners, carets and blinking badges change in place;
                              # a pointer travels. A single blip is ambiguous -> abstain.
CURSOR_MIN_COUNT = 5          # blobs smaller than this many pixels are noise
CURSOR_MAX_ASPECT = 5         # bbox longer than 5x its width is a line (caret, text row)
CURSOR_COHERENT_STEP = 0.10   # successive centroids within this fraction = trajectory
CURSOR_FRESH_S = 0.5          # evidence at most this old -> high confidence
CURSOR_STALE_S = 1.2          # evidence older than this -> no estimate


@dataclass
class Blob:
    count: int
    cx: float
    cy: float
    bx0: int
    by0: int
    bx1: int
    by1: int


_THRESH_RE: dict[int, "re.Pattern[bytes]"] = {}


def scan_diff_frame(buf: bytes, w: int, h: int,
                    threshold: int = CURSOR_DIFF_MIN) -> Blob | None:
    """Stats of the above-threshold pixels in one gray8 difference frame.

    A regex over the raw bytes finds runs of changed pixels at C speed — no
    per-pixel Python loop. Runs are split at row boundaries.
    """
    pat = _THRESH_RE.get(threshold)
    if pat is None:
        pat = re.compile(b"[" + re.escape(bytes([threshold])) + b"-\xff]+")
        _THRESH_RE[threshold] = pat

    count = 0
    sx = 0.0
    sy = 0.0
    bx0 = by0 = 1 << 30
    bx1 = by1 = -1
    for m in pat.finditer(buf):
        s, e = m.start(), m.end()
        row = s // w
        while s < e:
            row_end = min(e, (row + 1) * w)
            n = row_end - s
            x0 = s - row * w
            x1 = x0 + n - 1
            count += n
            sx += (x0 + x1) * n / 2
            sy += row * n
            bx0 = min(bx0, x0)
            bx1 = max(bx1, x1)
            by0 = min(by0, row)
            by1 = max(by1, row)
            s = row_end
            row += 1
    if count == 0:
        return None
    return Blob(count, sx / count, sy / count, bx0, by0, bx1, by1)


def classify_blob(blob: Blob | None, w: int, h: int) -> str:
    """'still' | 'cursor' (small, compact) | 'large' (scroll, transition, video).

    A pointer is a compact 2D glyph. Blips that are too small or too elongated —
    a blinking text caret (thin vertical line), a text row appearing during
    typing (wide flat band), a stray speck — are noise, not a pointer, and are
    treated as stillness so they neither claim a position nor block the walk.
    """
    if blob is None:
        return "still"
    if blob.count > CURSOR_MAX_AREA * w * h:
        return "large"
    if math.hypot(blob.bx1 - blob.bx0, blob.by1 - blob.by0) > CURSOR_MAX_DIAG * math.hypot(w, h):
        return "large"
    if blob.count < CURSOR_MIN_COUNT:
        return "still"
    bw = blob.bx1 - blob.bx0 + 1
    bh = blob.by1 - blob.by0 + 1
    if max(bw, bh) > CURSOR_MAX_ASPECT * min(bw, bh):
        return "still"
    return "cursor"


def estimate_cursor(samples: list[tuple[float, Blob | None]], w: int, h: int,
                    t_transition: float) -> dict | None:
    """Pointer estimate from a window of diff-frame samples before a transition.

    Walks backward: skips the trailing 'large' frames (the UI reaction itself),
    then takes the most recent cluster of cursor-like motion. Rejects clusters
    that never travel (spinner/caret) and evidence older than CURSOR_STALE_S.
    """
    diag = math.hypot(w, h)
    classed = [(t, classify_blob(b, w, h), b) for t, b in samples]

    # The window commonly ends [click motion][reaction][post-reaction stillness]:
    # walk past the trailing stillness, then past the reaction, then collect.
    i = len(classed) - 1
    while i >= 0 and classed[i][1] == "still":
        i -= 1
    while i >= 0 and classed[i][1] == "large":
        i -= 1
    cluster: list[tuple[float, str, Blob]] = []
    while i >= 0 and classed[i][1] != "large":
        if classed[i][1] == "cursor":
            cluster.append(classed[i])
        i -= 1
    cluster.reverse()
    if not cluster:
        return None

    # Travel evidence: pointers move, spinners/carets/badges change in place.
    if len(cluster) < 2:
        return None
    first = cluster[0][2]
    max_disp = max(
        math.hypot(b.cx - first.cx, b.cy - first.cy) for _, _, b in cluster
    )
    if max_disp < CURSOR_MIN_TRAVEL * diag:
        return None

    t_last, _, last = cluster[-1]
    age = t_transition - t_last
    if age > CURSOR_STALE_S:
        return None

    coherent = len(cluster) >= 3 and all(
        math.hypot(b2.cx - b1.cx, b2.cy - b1.cy) <= CURSOR_COHERENT_STEP * diag
        for (_, _, b1), (_, _, b2) in zip(cluster, cluster[1:])
    )
    return {
        "x": last.cx,
        "y": last.cy,
        "detected_at_t": round(t_last, 3),
        "confidence": "high" if coherent and age <= CURSOR_FRESH_S else "medium",
    }


def cursor_pass(video: Path, meta: "VideoMeta", frames: "list[FrameRec]",
                window: float) -> None:
    """Attach a pointer estimate to each scene-change frame, where evidence allows.

    One ffmpeg call per frame decodes the pre-transition window at low resolution,
    with tblend emitting inter-frame difference images on stdout.
    """
    if not meta.width or not meta.height:
        return
    sw = CURSOR_SCAN_W
    sh = max(2, int(round(meta.height * sw / meta.width / 2)) * 2)
    fsz = sw * sh
    def scan_window(f: FrameRec, win: float):
        # Sample up to the transition and no further: motion after it is the app
        # reacting (spinners, page paint), not the user's pointer.
        start = max(f.t - win, 0.0)
        span = f.t - start
        if span <= 0.2:
            return None, []
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-ss", f"{start:.3f}", "-i", str(video),
             "-t", f"{span:.3f}", "-an", "-sn",
             "-vf", f"fps={CURSOR_FPS},scale={sw}:{sh},format=gray,"
                    "tblend=all_mode=difference",
             "-f", "rawvideo", "-"],
            capture_output=True,
        )
        if p.returncode != 0 or not p.stdout:
            return None, []
        n = len(p.stdout) // fsz
        if n < 2:
            return None, []
        # tblend's first output frame has no real predecessor; drop it.
        samples = [
            (start + j / CURSOR_FPS,
             scan_diff_frame(p.stdout[j * fsz:(j + 1) * fsz], sw, sh))
            for j in range(1, n)
        ]
        return estimate_cursor(samples, sw, sh, f.t), samples

    for f in frames:
        if f.reason != "scene-change":
            continue
        est, samples = scan_window(f, window)
        if est is None and any(
            classify_blob(b, sw, sh) == "cursor" for _, b in samples[:3]
        ):
            # Cursor-like motion right at the window's start edge means the window
            # cut through a glide (the selected frame can trail the click when a
            # later, bigger change won NMS). Retry wider — the staleness gate still
            # bounds what the wider window may claim. A window that STARTS still
            # (e.g. only caret blinks inside it) gets no retry: reaching further
            # back could only surface older, unrelated motion.
            est, _ = scan_window(f, window * 3)
        if est is None:
            continue
        f.cursor = {
            "x": int(round(est["x"] * meta.width / sw)),
            "y": int(round(est["y"] * meta.height / sh)),
            "norm_x": round(est["x"] / sw, 4),
            "norm_y": round(est["y"] / sh, 4),
            "detected_at_t": est["detected_at_t"],
            "confidence": est["confidence"],
        }


# --------------------------------------------------------------------- OCR pass

# Optional: runs only when tesseract is on PATH, degrades to nothing when absent.
# The value is cheap grep-able signal: error strings from frames that may never be
# sent to a model. OCR output is machine-read and can be wrong — the skill's
# evidence rules require confirming against the frame before quoting as observed.
OCR_MIN_CONF = 55  # tesseract per-word confidence floor (0-100)


def find_tesseract() -> str | None:
    return shutil.which("tesseract")


def parse_tesseract_tsv(tsv: str, min_conf: float = OCR_MIN_CONF) -> str | None:
    """Confident words from tesseract TSV output, grouped into reading-order lines."""
    rows = tsv.splitlines()
    if len(rows) < 2:
        return None
    header = rows[0].split("\t")
    try:
        idx = {name: header.index(name)
               for name in ("block_num", "par_num", "line_num", "conf", "text")}
    except ValueError:
        return None

    lines: dict[tuple[str, str, str], list[str]] = {}
    for r in rows[1:]:
        cols = r.split("\t")
        if len(cols) != len(header):
            continue
        try:
            conf = float(cols[idx["conf"]])
        except ValueError:
            continue
        text = cols[idx["text"]].strip()
        if conf < min_conf or not text:
            continue
        key = (cols[idx["block_num"]], cols[idx["par_num"]], cols[idx["line_num"]])
        lines.setdefault(key, []).append(text)
    if not lines:
        return None
    return "\n".join(" ".join(words) for words in lines.values())


def ocr_pass(frames: "list[FrameRec]", outdir: Path, lang: str) -> str | None:
    """OCR each extracted frame in place. Returns the engine string, or None.

    Frames are upscaled 2x (lanczos) before recognition — measured on real
    recordings, this is the difference between missing and reading a 14px error
    banner. Known limit: low-contrast colored-on-colored text (e.g. red toast
    text on a dark red card) can still be missed; OCR here is a cheap grep
    signal, not the evidence path — the frames themselves remain the evidence.
    """
    binary = find_tesseract()
    if binary is None:
        return None
    ver = run([binary, "--version"])
    engine = (ver.stdout or ver.stderr or "tesseract").splitlines()[0].strip() or "tesseract"
    for f in frames:
        big = outdir / f"._ocr-{f.file}.png"
        try:
            up = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                      "-i", str(outdir / f.file),
                      "-vf", "scale=iw*2:ih*2:flags=lanczos", str(big)])
            src = big if up.returncode == 0 and big.exists() else outdir / f.file
            p = run([binary, str(src), "stdout", "-l", lang, "--psm", "3", "tsv"])
            if p.returncode != 0:
                continue
            f.ocr_text = parse_tesseract_tsv(p.stdout or "")
        finally:
            big.unlink(missing_ok=True)
    return engine


# ------------------------------------------------------------------- extraction


@dataclass
class FrameRec:
    index: int
    file: str
    t: float
    timestamp: str
    scene_score: float
    reason: str
    est_visual_tokens: int
    cursor: dict | None = None
    ocr_text: str | None = None


def scale_filter(long_edge: int) -> str:
    # Preserve aspect ratio, never upscale, force even dimensions for encoders.
    return (
        f"scale='if(gt(iw,ih),min({long_edge},iw),-2)':"
        f"'if(gt(iw,ih),-2,min({long_edge},ih))':flags=lanczos"
    )


def grab_frame(video: Path, t: float, dest: Path, long_edge: int, quality: int) -> bool:
    p = run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{max(t, 0):.3f}", "-i", str(video),
            "-frames:v", "1",
            "-vf", scale_filter(long_edge),
            "-q:v", str(quality),
            str(dest),
        ]
    )
    return p.returncode == 0 and dest.exists() and dest.stat().st_size > 0


def png_or_jpg_size(path: Path) -> tuple[int, int]:
    p = run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x", str(path),
        ]
    )
    try:
        w, h = p.stdout.strip().split("x")
        return int(w), int(h)
    except ValueError:
        return 0, 0


def has_drawtext() -> bool:
    p = run(["ffmpeg", "-hide_banner", "-filters"])
    return " drawtext " in (p.stdout or "")


# Without an explicit fontfile, drawtext asks fontconfig for a default font, and
# fontconfig has no default config on Windows builds (Gyan) — the whole filtergraph
# fails with "Cannot load default config file". An explicit fontfile makes freetype
# load the font directly and skips fontconfig entirely.
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
)


def find_font() -> str | None:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    return None


def _dt_escape(s: str) -> str:
    """Escape a literal for ffmpeg drawtext's text= option."""
    return s.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


def _dt_path_escape(path: str) -> str:
    """Escape a filesystem path for drawtext's fontfile= option (drive colons)."""
    return path.replace("\\", "/").replace(":", r"\:")


def contact_sheet(
    frames: list[FrameRec],
    outdir: Path,
    cols: int,
    tile_w: int,
    aspect: float,
    label: bool,
) -> str | None:
    """One labelled grid image. Lets a model orient cheaply before pulling full frames.

    `tile` consumes successive frames of a SINGLE stream, so the per-image chains are
    concatenated first. Every tile is forced to identical dimensions because concat
    rejects mismatched sizes.
    """
    if not frames:
        return None

    band = 26
    body_h = max(2, int(round(tile_w * aspect)) // 2 * 2)
    tile_h = body_h + band
    rows = math.ceil(len(frames) / cols)
    dest = outdir / "contact-sheet.jpg"
    font = find_font() if label else None

    def build_cmd(with_labels: bool) -> list[str]:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for f in frames:
            cmd += ["-i", str(outdir / f.file)]

        chains = []
        for i, f in enumerate(frames):
            vf = (
                f"scale={tile_w}:{body_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
                f"pad={tile_w}:{tile_h}:(ow-iw)/2:{band}:color=0x101014,"
                f"setsar=1,format=yuv420p"
            )
            if with_labels:
                text = _dt_escape(f"{f.index:02d}  {f.timestamp}  {f.reason}")
                fontopt = f"fontfile='{_dt_path_escape(font)}':" if font else ""
                vf += (
                    f",drawtext={fontopt}text='{text}':x=8:y=4:fontsize=17:"
                    f"fontcolor=0xE6E6EA"
                )
            chains.append(f"[{i}:v]{vf}[t{i}]")

        # Pad a ragged final row with blank tiles so the grid stays rectangular.
        blanks = rows * cols - len(frames)
        labels = "".join(f"[t{i}]" for i in range(len(frames)))
        filt = ";".join(chains)
        for b in range(blanks):
            filt += (
                f";color=c=0x101014:s={tile_w}x{tile_h}:d=1,setsar=1,"
                f"format=yuv420p[b{b}]"
            )
            labels += f"[b{b}]"

        n = rows * cols
        filt += (
            f";{labels}concat=n={n}:v=1:a=0[cat]"
            f";[cat]tile={cols}x{rows}:padding=6:margin=6:color=0x101014[out]"
        )

        cmd += ["-filter_complex", filt, "-map", "[out]",
                "-frames:v", "1", "-q:v", "4", str(dest)]
        return cmd

    p = run(build_cmd(with_labels=label))
    if label and (p.returncode != 0 or not dest.exists()):
        # drawtext can still fail (broken fontconfig and no known font, exotic
        # builds). A sheet without labels beats no sheet.
        print(
            f"warning: labelled contact sheet failed, retrying without labels: "
            f"{p.stderr.strip()[:200]}",
            file=sys.stderr,
        )
        p = run(build_cmd(with_labels=False))
    if p.returncode != 0 or not dest.exists():
        print(f"warning: contact sheet failed: {p.stderr.strip()[:300]}", file=sys.stderr)
        return None
    return dest.name


# ------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="extract_keyframes.py",
        description="Scene-change keyframe extraction tuned for UI screen recordings.",
    )
    ap.add_argument("video", type=Path, help="path to the screen recording")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output directory (default: ./<videoname>-keyframes)")
    ap.add_argument("--max-frames", type=int, default=14,
                    help="hard cap on extracted frames (default: 14)")
    ap.add_argument("--min-gap", type=float, default=0.5,
                    help="seconds of temporal suppression around each kept frame (default: 0.5)")
    ap.add_argument("--threshold", type=float, default=0.0015,
                    help="seed scene threshold for candidate collection (default: 0.0015). "
                         "Measured UI transitions score 0.002-0.05; ffmpeg's conventional 0.3 "
                         "finds nothing on a screen recording.")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="drop candidates scoring below this (default: 0.0, i.e. keep all; raise to ~0.005 if a noisy recording yields junk frames)")
    ap.add_argument("--long-edge", type=int, default=1024,
                    help="downscale long edge in px (default: 1024 ~= 800 visual tokens)")
    ap.add_argument("--quality", type=int, default=4,
                    help="ffmpeg -q:v for JPEG output, 2=best 31=worst (default: 4)")
    ap.add_argument("--no-cursor", action="store_true",
                    help="skip cursor/click estimation for scene-change frames")
    ap.add_argument("--cursor-window", type=float, default=1.5,
                    help="seconds of pre-transition motion to inspect for the pointer (default: 1.5)")
    ap.add_argument("--no-ocr", action="store_true",
                    help="skip the OCR pass even if tesseract is installed")
    ap.add_argument("--ocr-lang", default="eng",
                    help="tesseract language(s), e.g. eng or eng+deu (default: eng)")
    ap.add_argument("--no-contact-sheet", action="store_true",
                    help="skip generating the grid overview image")
    ap.add_argument("--sheet-cols", type=int, default=4)
    ap.add_argument("--sheet-tile", type=int, default=420)
    ap.add_argument("--json", action="store_true",
                    help="print manifest JSON to stdout instead of the human summary")
    args = ap.parse_args()

    require_binaries()

    video: Path = args.video.expanduser().resolve()
    if not video.exists():
        die(f"no such file: {video}")
    if video.suffix.lower() not in VIDEO_SUFFIXES:
        print(
            f"warning: {video.suffix} is not a recognised video suffix; trying anyway",
            file=sys.stderr,
        )

    meta = probe(video)

    outdir: Path = (args.out or Path.cwd() / f"{video.stem}-keyframes").expanduser().resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. candidates -------------------------------------------------------------
    cands = scene_candidates(video, args.threshold)
    used_fallback = False

    picks = suppress(cands, args.max_frames - 2, args.min_gap, args.min_score)

    if len(picks) < 2:
        # Static or near-static recording (e.g. a hang / frozen spinner bug).
        used_fallback = True
        picks = uniform_fallback(meta.duration_s, min(args.max_frames - 2, 6))

    # 2. pin first and last state ----------------------------------------------
    head = min(0.30, meta.duration_s * 0.02)
    tail = max(meta.duration_s - 0.25, 0.0)
    timeline: list[tuple[float, float, str]] = [(head, 0.0, "initial-state")]
    for t, s in picks:
        if abs(t - head) < 0.25 or abs(t - tail) < 0.25:
            continue
        timeline.append((t, s, "uniform-fallback" if used_fallback else "scene-change"))
    timeline.append((tail, 0.0, "final-state"))
    timeline.sort(key=lambda x: x[0])

    # 3. extract ----------------------------------------------------------------
    frames: list[FrameRec] = []
    failures: list[float] = []
    for i, (t, score, reason) in enumerate(timeline, start=1):
        name = f"frame-{i:02d}.jpg"
        dest = outdir / name
        if not grab_frame(video, t, dest, args.long_edge, args.quality):
            failures.append(t)
            continue
        w, h = png_or_jpg_size(dest)
        frames.append(
            FrameRec(
                index=i,
                file=name,
                t=round(t, 3),
                timestamp=hhmmss(t),
                scene_score=round(score, 5),
                reason=reason,
                est_visual_tokens=visual_tokens(w, h) if w and h else 0,
            )
        )

    if not frames:
        die("extracted zero frames — the file may be corrupt or use an unsupported codec")

    # renumber contiguously after any failures
    for new_i, f in enumerate(frames, start=1):
        f.index = new_i

    # 4. cursor / click estimation ----------------------------------------------
    if not args.no_cursor:
        cursor_pass(video, meta, frames, args.cursor_window)

    # 5. OCR (optional, requires tesseract on PATH) ------------------------------
    ocr_engine = None
    if not args.no_ocr:
        ocr_engine = ocr_pass(frames, outdir, args.ocr_lang)

    # 6. contact sheet ----------------------------------------------------------
    sheet = None
    if not args.no_contact_sheet:
        aspect = (meta.height / meta.width) if meta.width else 0.5625
        sheet = contact_sheet(
            frames, outdir, args.sheet_cols, args.sheet_tile, aspect, has_drawtext()
        )

    # 7. manifest ---------------------------------------------------------------
    total_tokens = sum(f.est_visual_tokens for f in frames)
    naive_2fps = int(meta.duration_s * 2) * visual_tokens(args.long_edge, int(args.long_edge * 0.5625))
    manifest = {
        "tool": "extract_keyframes.py",
        "version": "1.2.0",
        "video": asdict(meta),
        "selection": {
            "strategy": "uniform-fallback" if used_fallback else "scene-change + temporal-NMS",
            "seed_threshold": args.threshold,
            "min_score": args.min_score,
            "min_gap_s": args.min_gap,
            "max_frames": args.max_frames,
            "candidates_found": len(cands),
            "frames_kept": len(frames),
            "extraction_failures_at": failures,
        },
        "cost": {
            "long_edge_px": args.long_edge,
            "est_visual_tokens_all_frames": total_tokens,
            "est_visual_tokens_naive_2fps": naive_2fps,
        },
        "contact_sheet": sheet,
        "ocr": {
            "engine": ocr_engine,
            "note": (
                "per-frame ocr_text is machine-read and may contain errors; "
                "confirm against the frame before quoting a string as observed"
                if ocr_engine else
                "tesseract not found on PATH (or --no-ocr) — ocr_text is null "
                "everywhere; install tesseract for grep-able frame text"
            ),
        },
        "frames": [asdict(f) for f in frames],
        "notes": [
            "Audio is not processed. This tool is visual-only by design.",
            "scene_score 0.0 means the frame was pinned (initial/final state) or "
            "selected by uniform fallback, not that nothing changed.",
            "cursor is INFERRED from pre-transition pointer motion, never observed "
            "directly — cite it as [I] evidence, and treat null as 'no reliable "
            "estimate' (keyboard-driven or app-driven transition, or no visible "
            "pointer), not as 'no click happened'.",
        ],
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(manifest, indent=2))
        return 0

    print(f"video       {video.name}  ({meta.width}x{meta.height}, "
          f"{meta.duration_s:.1f}s, {meta.fps:g}fps, audio={'yes' if meta.has_audio else 'no'})")
    print(f"strategy    {manifest['selection']['strategy']}  "
          f"({len(cands)} candidates -> {len(frames)} frames)")
    print(f"output      {outdir}")
    if sheet:
        print(f"overview    {sheet}   <- look at this first")
    print(f"est. cost   ~{total_tokens:,} visual tokens for all frames "
          f"(naive 2fps would be ~{naive_2fps:,})")
    if ocr_engine:
        n_text = sum(1 for f in frames if f.ocr_text)
        print(f"ocr         {ocr_engine} - text captured on {n_text}/{len(frames)} "
              f"frames (ocr_text in manifest.json)")
    else:
        print("ocr         skipped (tesseract not on PATH)" if not args.no_ocr
              else "ocr         skipped (--no-ocr)")
    if used_fallback:
        print("note        no meaningful scene changes detected; the UI may be frozen, "
              "or lower --threshold and retry")
    if failures:
        print(f"warning     {len(failures)} frame(s) failed to extract")
    print()
    for f in frames:
        cur = ""
        if f.cursor:
            cur = f"  cursor~({f.cursor['x']},{f.cursor['y']}) [{f.cursor['confidence']}]"
        print(f"  {f.index:02d}  {f.timestamp}  score={f.scene_score:<8} {f.reason:<16} {f.file}{cur}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
