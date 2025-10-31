#!/usr/bin/env bash
# clean_to_wav_configured.sh
# Convert audio files to WAV (22,050 Hz, 16-bit PCM), strip metadata,
# and mirror the folder structure from input to output.
# Requirements: bash 4+, ffmpeg, ffprobe
#
# Usage:
#   ./clean_to_wav_configured.sh /path/to/input /path/to/output
#
# You can configure defaults BELOW (CONFIG section). Env vars (EXTS/SUFFIX/FORCE_CHANNELS)
# still override these defaults when provided.
#
set -euo pipefail

############################
# ====== CONFIG ========= #
############################
# 只处理的扩展名（空格分隔，大小写不敏感）
EXTS_DEFAULT="wav mp3 flac aif aiff m4a ogg opus wma aac caf aiffc"

# 输出文件名后缀
SUFFIX_DEFAULT="_22050_16bit"

# 强制声道数：设为 "1" 或 "2"；置空 "" 则保留原声道
FORCE_CHANNELS_DEFAULT="1"
############################
# ==== END CONFIG ======== #
############################

# Allow environment variables to override defaults
EXTS="${EXTS:-$EXTS_DEFAULT}"
SUFFIX="${SUFFIX:-$SUFFIX_DEFAULT}"
FORCE_CHANNELS="${FORCE_CHANNELS:-$FORCE_CHANNELS_DEFAULT}"

if [[ "${BASH_VERSINFO:-0}" -lt 4 ]]; then
  echo "Please run with Bash 4+ (Bash version too old)." >&2
  exit 1
fi

command -v ffmpeg >/dev/null 2>&1 || { echo "Error: ffmpeg not found in PATH." >&2; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo "Error: ffprobe not found in PATH." >&2; exit 1; }

IN="${1:-}"
OUT="${2:-}"
if [[ -z "${IN}" || -z "${OUT}" ]]; then
  echo "Usage: $0 <input_dir> <output_dir>" >&2
  exit 1
fi
[[ -d "${IN}" ]] || { echo "Error: input dir not found: ${IN}" >&2; exit 1; }

mkdir -p "${OUT}"
shopt -s globstar nullglob

# Iterate files recursively
while IFS= read -r -d '' SRC; do
  # Filter by extension (case-insensitive)
  EXT="${SRC##*.}"
  EXT_LC="${EXT,,}"
  MATCHED=0
  for e in ${EXTS}; do
    if [[ "${EXT_LC}" == "${e}" ]]; then
      MATCHED=1
      break
    fi
  done
  [[ $MATCHED -eq 1 ]] || continue

  # Relative path & destination path
  REL="${SRC#${IN%/}/}"
  BASENOEXT="${REL%.*}"
  DEST_DIR="${OUT%/}/$(dirname "${REL}")"
  DEST="${OUT%/}/${BASENOEXT}${SUFFIX}.wav"
  mkdir -p "${DEST_DIR}"

  # Determine channel count from source (keep original unless overridden)
  if [[ -n "${FORCE_CHANNELS}" ]]; then
    CH="${FORCE_CHANNELS}"
  else
    CH="$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of csv=p=0 "${SRC}" || true)"
    [[ -n "${CH}" ]] || CH=2
  fi

  echo "Processing: ${SRC}  ->  ${DEST} (ch=${CH})"

  # Two-stage pipeline to guarantee clean WAV without extra chunks:
  # 1) Decode to raw PCM s16le @ 22050 Hz (no metadata in raw)
  # 2) Re-wrap to WAV with minimal header, drop all metadata/chunks
  ffmpeg -hide_banner -v error -nostdin -y -i "${SRC}" \
         -vn -sn -dn -ar 22050 -ac "${CH}" -sample_fmt s16 -f s16le - \
  | ffmpeg -hide_banner -v error -nostdin -y -f s16le -ar 22050 -ac "${CH}" -i - \
           -map_metadata -1 -fflags +bitexact -write_bext 0 -rf64 0 -c:a pcm_s16le "${DEST}"

done < <(find "${IN}" -type f -print0)

echo "Done. Output at: ${OUT}"
