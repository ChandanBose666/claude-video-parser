#!/usr/bin/env bash
# Install the flow-recording-report skill for Claude Code.
#   ./scripts/install.sh            -> ~/.claude/skills          (all projects)
#   ./scripts/install.sh --project  -> ./.claude/skills          (this repo only)
#   ./scripts/install.sh --force    -> overwrite existing install
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/skills/flow-recording-report"

SCOPE="user"; FORCE=0
for arg in "$@"; do
  case "$arg" in
    --project) SCOPE="project" ;;
    --force)   FORCE=1 ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

[ -d "$SRC" ] || { echo "skill source not found at $SRC" >&2; exit 1; }

if [ "$SCOPE" = "project" ]; then
  TARGET_ROOT="$PWD/.claude/skills"
else
  TARGET_ROOT="$HOME/.claude/skills"
fi
TARGET="$TARGET_ROOT/flow-recording-report"

if [ -e "$TARGET" ] && [ "$FORCE" -eq 0 ]; then
  echo "already installed at $TARGET"
  echo "re-run with --force to overwrite."
  exit 1
fi

mkdir -p "$TARGET_ROOT"
rm -rf "$TARGET"
cp -R "$SRC" "$TARGET"
chmod +x "$TARGET/scripts/extract_keyframes.py"
echo "installed -> $TARGET"

missing=()
for b in ffmpeg ffprobe; do command -v "$b" >/dev/null 2>&1 || missing+=("$b"); done
if [ ${#missing[@]} -gt 0 ]; then
  echo
  echo "missing on PATH: ${missing[*]}"
  case "$(uname -s)" in
    Darwin) echo "  brew install ffmpeg" ;;
    *)      echo "  sudo apt install ffmpeg   # or your distro's equivalent" ;;
  esac
else
  echo "ffmpeg + ffprobe found"
fi

if command -v python3 >/dev/null 2>&1; then
  echo "$(python3 --version) found"
else
  echo "python3 not found on PATH"
fi

echo
echo "Restart Claude Code, then try:"
echo '  "QA sent me this recording of checkout breaking - ./bug.mp4"'
