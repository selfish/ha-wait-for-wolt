#!/usr/bin/env bash
# Exercise the exact built archive in the supported Home Assistant container.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${HA_IMAGE:-ghcr.io/home-assistant/home-assistant:2026.7.3}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/wait-for-wolt-canary.XXXXXX")"
NAME="wait-for-wolt-canary-$$"
cleanup() {
  docker rm -f "${NAME}" >/dev/null 2>&1 || true
  if ! rm -rf "${WORK}" 2>/dev/null; then
    docker run --rm --entrypoint /bin/chmod \
      -v "${WORK}:/work" "${IMAGE}" -R a+rwX /work >/dev/null 2>&1 || true
    rm -rf "${WORK}" || true
  fi
}
trap cleanup EXIT

cd "${ROOT}"
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Canary requires a clean checkout so artifact metadata binds exact source" >&2
  exit 2
fi
VERSION="$(uv run python scripts/check_version.py)"
EXPECTED_COMMIT="$(git rev-parse HEAD)"
if [[ -n "${CANARY_ARCHIVE:-}" || -n "${CANARY_CHECKSUM:-}" || -n "${CANARY_METADATA:-}" ]]; then
  if [[ ! -f "${CANARY_ARCHIVE:-}" || ! -f "${CANARY_CHECKSUM:-}" || ! -f "${CANARY_METADATA:-}" ]]; then
    echo "CANARY_ARCHIVE, CANARY_CHECKSUM, and CANARY_METADATA must all name readable files" >&2
    exit 2
  fi
  cp "${CANARY_ARCHIVE}" "${WORK}/wait_for_wolt.zip"
  cp "${CANARY_CHECKSUM}" "${WORK}/wait_for_wolt.sha256"
  cp "${CANARY_METADATA}" "${WORK}/artifact.metadata"
else
  SOURCE_DATE_EPOCH="$(git show -s --format=%ct HEAD)" \
    uv run python scripts/build_release.py --label canary --output-dir "${WORK}"
  printf 'commit=%s\n' "${EXPECTED_COMMIT}" > "${WORK}/artifact.metadata"
fi
(
  cd "${WORK}"
  sha256sum -c wait_for_wolt.sha256
  grep -Fx "commit=${EXPECTED_COMMIT}" artifact.metadata
)
mkdir -p "${WORK}/config/custom_components/wait_for_wolt"
python -m zipfile -e \
  "${WORK}/wait_for_wolt.zip" \
  "${WORK}/config/custom_components/wait_for_wolt"
cat > "${WORK}/config/configuration.yaml" <<'YAML'
homeassistant:
  name: Wait for Wolt Canary
logger:
  default: warning
YAML

# Import every shipped Python module from the extracted archive in the selected
# Home Assistant runtime. This catches missing package files and import-time API
# incompatibilities even though the disposable config has no real Wolt entry.
docker run --rm \
  --name "${NAME}-import" \
  -w /config/custom_components \
  -v "${WORK}/config:/config" \
  "${IMAGE}" \
  python -c 'import wait_for_wolt, wait_for_wolt.api, wait_for_wolt.config_flow, wait_for_wolt.const, wait_for_wolt.coordinator, wait_for_wolt.diagnostics, wait_for_wolt.sensor'

docker run --rm \
  --name "${NAME}-check" \
  -v "${WORK}/config:/config" \
  "${IMAGE}" \
  python -m homeassistant --script check_config -c /config

docker run -d \
  --name "${NAME}" \
  -p 127.0.0.1::8123 \
  -v "${WORK}/config:/config" \
  "${IMAGE}" >/dev/null

PORT="$(docker inspect --format '{{(index (index .NetworkSettings.Ports "8123/tcp") 0).HostPort}}' "${NAME}")"
ready=false
for _ in $(seq 1 90); do
  if curl --fail --silent --output /dev/null "http://127.0.0.1:${PORT}/"; then
    ready=true
    break
  fi
  if ! docker inspect --format '{{.State.Running}}' "${NAME}" | grep -qx true; then
    docker logs "${NAME}"
    exit 1
  fi
  sleep 1
done
if [[ "${ready}" != true ]]; then
  docker logs "${NAME}"
  echo "Home Assistant did not become ready" >&2
  exit 1
fi

if docker logs "${NAME}" 2>&1 | grep -Eiq \
  'Error loading custom_components\.wait_for_wolt|Setup failed for custom integration.*wait_for_wolt|Invalid config for.*wait_for_wolt'; then
  docker logs "${NAME}"
  echo "Wait for Wolt startup error found" >&2
  exit 1
fi

printf 'Canary passed: version=%s image=%s port=%s\n' "${VERSION}" "${IMAGE}" "${PORT}"
