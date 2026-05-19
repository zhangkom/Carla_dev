#!/usr/bin/env bash
# Package an MGSC DAW Docker image for Ubuntu deployment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_DIR="$(cd "$REPO_DIR/.." && pwd)"

VERSION="${VERSION:-6.5.11.1222}"
IMAGE_NAME="${IMAGE_NAME:-mgsc_daw_service:${VERSION}}"
OUTPUT_DIR="${OUTPUT_DIR:-$WORKSPACE_DIR/docker_images}"
TEST_ZIPS_DIR="${TEST_ZIPS_DIR:-$OUTPUT_DIR/test_zips}"
SPLIT_BYTES="${SPLIT_BYTES:-1900000000}"
KEEP_FULL_TAR="${KEEP_FULL_TAR:-0}"

IMAGE_TAR="$OUTPUT_DIR/mgsc_daw_service_${VERSION}.tar"
FULL_SUMS="$OUTPUT_DIR/SHA256SUMS_${VERSION}.txt"
PART_SUMS="$OUTPUT_DIR/SHA256SUMS_${VERSION}_parts.txt"
TEST_ZIPS_ZIP="$OUTPUT_DIR/test_zips_${VERSION}.zip"
TEST_ZIPS_SUMS="$OUTPUT_DIR/SHA256SUMS_test_zips_${VERSION}.txt"
MANIFEST="$OUTPUT_DIR/MANIFEST_${VERSION}.txt"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required" >&2
  exit 1
fi
if ! command -v split >/dev/null 2>&1; then
  echo "split is required" >&2
  exit 1
fi
if ! command -v sha256sum >/dev/null 2>&1; then
  echo "sha256sum is required" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

docker image inspect "$IMAGE_NAME" >/dev/null

rm -f "$IMAGE_TAR" "$IMAGE_TAR".part* "$FULL_SUMS" "$PART_SUMS" \
  "$TEST_ZIPS_ZIP" "$TEST_ZIPS_SUMS" "$MANIFEST"

cp "$REPO_DIR/deploy_mgsc_daw_service.sh" "$OUTPUT_DIR/deploy_mgsc_daw_service.sh"
chmod +x "$OUTPUT_DIR/deploy_mgsc_daw_service.sh"

echo "Saving image $IMAGE_NAME -> $IMAGE_TAR"
docker save "$IMAGE_NAME" -o "$IMAGE_TAR"
sha256sum "$IMAGE_TAR" > "$FULL_SUMS"

echo "Splitting image into <= $SPLIT_BYTES byte parts"
split -b "$SPLIT_BYTES" -d -a 2 --numeric-suffixes=1 "$IMAGE_TAR" "$IMAGE_TAR.part"
sha256sum "$IMAGE_TAR".part* > "$PART_SUMS"

if [ "$KEEP_FULL_TAR" != "1" ]; then
  rm -f "$IMAGE_TAR"
fi

if [ -d "$TEST_ZIPS_DIR" ]; then
  if command -v zip >/dev/null 2>&1; then
    tmp_dir="$(mktemp -d)"
    find "$TEST_ZIPS_DIR" -maxdepth 1 -type f -name '*.zip' ! -iname '*debug*' -exec cp {} "$tmp_dir/" \;
    (
      cd "$tmp_dir"
      zip -q -r "$TEST_ZIPS_ZIP" .
    )
    rm -rf "$tmp_dir"
    sha256sum "$TEST_ZIPS_ZIP" > "$TEST_ZIPS_SUMS"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$TEST_ZIPS_DIR" "$TEST_ZIPS_ZIP" <<'PY'
import sys
import zipfile
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(source.glob("*.zip")):
        if "debug" in path.name.lower():
            continue
        archive.write(path, path.name)
PY
    sha256sum "$TEST_ZIPS_ZIP" > "$TEST_ZIPS_SUMS"
  else
    echo "zip and python3 are not installed; skip test zip bundle" >&2
  fi
fi

{
  echo "MGSC DAW Docker deployment package"
  echo "version: $VERSION"
  echo "image: $IMAGE_NAME"
  echo "created_at: $(date '+%Y-%m-%d %H:%M:%S %z')"
  echo
  echo "copy these files to Ubuntu:"
  echo "deploy_mgsc_daw_service.sh"
  for part in "$IMAGE_TAR".part*; do
    basename "$part"
  done
  basename "$FULL_SUMS"
  basename "$PART_SUMS"
  [ -f "$TEST_ZIPS_ZIP" ] && basename "$TEST_ZIPS_ZIP"
  [ -f "$TEST_ZIPS_SUMS" ] && basename "$TEST_ZIPS_SUMS"
  basename "$MANIFEST"
  echo
  if [ -f "$IMAGE_TAR" ]; then
    echo "full image:"
    ls -lh "$IMAGE_TAR"
  else
    echo "full image:"
    echo "removed after split; set KEEP_FULL_TAR=1 to keep it in the package directory"
  fi
  cat "$FULL_SUMS"
  echo
  echo "parts:"
  ls -lh "$IMAGE_TAR".part*
  cat "$PART_SUMS"
} > "$MANIFEST"

echo "Package manifest: $MANIFEST"
