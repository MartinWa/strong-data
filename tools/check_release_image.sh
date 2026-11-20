#!/usr/bin/env bash
# Check a single release platform image and write its SBOM.
set -euo pipefail
: "${IMAGE:?IMAGE must name the release image by digest}"
: "${VERSION:?VERSION must be the release version}"
: "${SBOM:?SBOM must be the SBOM output path}"
: "${PLATFORM:?PLATFORM must be a linux platform such as linux/arm64}"
docker pull "$IMAGE"
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true --tmpfs /tmp \
  --env EXPECTED_VERSION="$VERSION" \
  --env STRONG_SECRET_KEY=synthetic-release-check-key-never-for-runtime-00000000 \
  --env STRONG_ALLOWED_HOSTS=127.0.0.1 \
  "$IMAGE" python -m tools.check_production
bash "$(dirname "$0")/audit_image.sh" "$IMAGE" "$SBOM" "$PLATFORM"
