#!/usr/bin/env bash
# Generates the media served by the stub API (e2e/stub/.media/):
#
#   ad-spot.mp4    45.0 s, 640x360, 25 fps, H.264 yuv420p + AAC, faststart,
#                  one keyframe per second. Each fixture segment has its own
#                  background colour, a burned-in "SEG n of 9" + title, a
#                  running timecode and a white bar that sweeps left to right
#                  over the 45 s, so a screenshot proves which time is showing.
#   filmstrip.jpg  1600x450 sprite, 10 columns x 5 rows of 160x90 tiles,
#                  row-major, tile i = the frame at exactly i seconds.
#
# Idempotent: files that are newer than their inputs are kept. `--force` rebuilds.
# Uses only the system ffmpeg/ffprobe and node; needs no network access.
set -euo pipefail

STUB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "$STUB_DIR/../.." && pwd)"
MEDIA_DIR="$STUB_DIR/.media"
VIDEO="$MEDIA_DIR/ad-spot.mp4"
SPRITE="$MEDIA_DIR/filmstrip.jpg"
GRAPH_TOOL="$STUB_DIR/tools/filtergraph.ts"
PALETTE="$STUB_DIR/data/palette.ts"
FIXTURE="$FRONTEND_DIR/src/types/timeline/__tests__/adSpotFixture.ts"

FFMPEG="${FFMPEG:-/usr/bin/ffmpeg}"
FFPROBE="${FFPROBE:-/usr/bin/ffprobe}"
DURATION=45
FPS=25
TILE_W=160
TILE_H=90
SPRITE_COLS=10  # not COLUMNS/LINES: bash overwrites those with the terminal size
SPRITE_ROWS=5

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

say() { printf '[make-media] %s\n' "$*"; }
die() { printf '[make-media] ERROR: %s\n' "$*" >&2; exit 1; }

require_tools() {
  [[ -x "$FFMPEG" ]] || die "ffmpeg not found at $FFMPEG (set FFMPEG=/path/to/ffmpeg)"
  [[ -x "$FFPROBE" ]] || die "ffprobe not found at $FFPROBE (set FFPROBE=/path/to/ffprobe)"
  command -v node >/dev/null || die "node is required to derive the filter graph from the fixture"
}

# True when $1 exists and is newer than every other argument.
up_to_date() {
  local target="$1"; shift
  [[ -f "$target" && "$FORCE" -eq 0 ]] || return 1
  local input
  for input in "$@"; do
    [[ "$target" -nt "$input" ]] || return 1
  done
}

# Prints "<sans-bold> <mono-bold>" font paths, or nothing when drawtext cannot be used.
find_fonts() {
  local filters sans mono
  # Captured first: `ffmpeg | grep -q` would trip pipefail when grep exits early.
  filters="$("$FFMPEG" -hide_banner -filters 2>/dev/null || true)"
  grep -q ' drawtext ' <<<"$filters" || return 0
  command -v fc-match >/dev/null || return 0
  sans="$(fc-match -f '%{file}' 'DejaVu Sans:bold' 2>/dev/null || true)"
  mono="$(fc-match -f '%{file}' 'DejaVu Sans Mono:bold' 2>/dev/null || true)"
  [[ -f "$sans" && -f "$mono" ]] && printf '%s %s' "$sans" "$mono"
  return 0
}

build_video() {
  local fonts graph tmp="$MEDIA_DIR/.ad-spot.tmp.mp4"
  fonts="$(find_fonts)"
  if [[ -z "$fonts" ]]; then
    say "drawtext or fonts unavailable: falling back to per-segment colours + sweep bar (no burned-in text)"
  fi
  # shellcheck disable=SC2086  # $fonts is two space-separated paths, or empty
  graph="$(node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON "$GRAPH_TOOL" $fonts)"
  say "encoding $VIDEO"
  "$FFMPEG" -hide_banner -loglevel error -y \
    -f lavfi -i "sine=frequency=220:sample_rate=48000:duration=$DURATION" \
    -filter_complex "$graph" -map '[v]' -map 0:a \
    -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p -r "$FPS" \
    -g "$FPS" -keyint_min "$FPS" -sc_threshold 0 \
    -c:a aac -b:a 64k -ac 1 -af 'volume=0.05' \
    -t "$DURATION" -movflags +faststart "$tmp"
  mv -f "$tmp" "$VIDEO"
}

build_sprite() {
  local tmp="$MEDIA_DIR/.filmstrip.tmp.jpg"
  say "tiling $SPRITE"
  # select (not fps=1) so tile i is the frame at exactly i seconds, not the one ~0.5 s later.
  "$FFMPEG" -hide_banner -loglevel error -y -i "$VIDEO" \
    -vf "select='not(mod(n\,$FPS))',scale=$TILE_W:$TILE_H,tile=${SPRITE_COLS}x${SPRITE_ROWS}" \
    -fps_mode passthrough -frames:v 1 -q:v 3 -update 1 "$tmp"
  mv -f "$tmp" "$SPRITE"
}

verify() {
  local size duration
  size="$("$FFPROBE" -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$SPRITE")"
  [[ "$size" == "$((TILE_W * SPRITE_COLS)),$((TILE_H * SPRITE_ROWS))" ]] || die "unexpected sprite size: $size"
  duration="$("$FFPROBE" -v error -show_entries format=duration -of csv=p=0 "$VIDEO")"
  say "ok: ad-spot.mp4 ${duration}s, filmstrip.jpg ${size/,/x}"
}

main() {
  require_tools
  mkdir -p "$MEDIA_DIR"
  if up_to_date "$VIDEO" "$GRAPH_TOOL" "$PALETTE" "$FIXTURE" "${BASH_SOURCE[0]}"; then
    say "up to date: $VIDEO"
  else
    build_video
  fi
  if up_to_date "$SPRITE" "$VIDEO"; then
    say "up to date: $SPRITE"
  else
    build_sprite
  fi
  verify
}

main
