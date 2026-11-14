#!/usr/bin/env sh
# Skillporter hardened standalone installer (Linux & macOS)
#
# Trust model & supply-chain guarantees:
#   1. Immutable release tags only (never falls back to mutable `main`).
#   2. Mandatory SHA-256 verification against release `SHA256SUMS.txt`.
#   3. Mandatory authenticity / provenance verification (fail-closed by default) via ONE of:
#      a) GitHub Artifact Attestations (`gh attestation verify` against workflow OIDC) [preferred]
#      b) Out-of-band caller-pinned digest (`SKILLPORTER_SHA256=<64-hex>`)
#      c) Detached cryptographic signature (`SKILLPORTER_PUBLIC_KEY_FILE=<pem>` verifying `SHA256SUMS.txt.sig`)
#      (Same-origin `SHA256SUMS.txt` alone detects transport corruption, NOT origin compromise;
#       set `SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM=1` only if you explicitly accept TOFU over HTTPS.)
#   4. Same-directory staging + atomic POSIX `mv -f` so failed installs/upgrades never corrupt an
#      existing installation.
set -eu

REPO="${SKILLPORTER_REPO:-Shanmukh-l33t/skillporter}"
VERSION="${SKILLPORTER_VERSION:-v3.1.0}"
RELEASE_BASE="${SKILLPORTER_RELEASE_BASE_URL:-https://github.com/${REPO}/releases/download}"
SIGNER_WORKFLOW="${SKILLPORTER_SIGNER_WORKFLOW:-${REPO}/.github/workflows/publish.yml}"

# Reject mutable branch names, path traversal, and shell metacharacters in VERSION
if ! printf '%s\n' "${VERSION}" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+([-.][A-Za-z0-9.]+)?$'; then
  echo "error: invalid SKILLPORTER_VERSION '${VERSION}'. Pin an immutable release tag such as 'v3.0.0' (mutable refs like 'main' or 'latest' are forbidden)." >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 (3.9+) is required to run skillporter." >&2
  exit 1
fi

if [ -n "${SKILLPORTER_INSTALL_DIR:-}" ]; then
  DEST_DIR="${SKILLPORTER_INSTALL_DIR}"
  mkdir -p "${DEST_DIR}"
elif [ "$(id -u)" -eq 0 ] && [ -w "/usr/local/bin" ]; then
  DEST_DIR="/usr/local/bin"
elif [ -w "/usr/local/bin" ]; then
  DEST_DIR="/usr/local/bin"
else
  DEST_DIR="${HOME}/.local/bin"
  mkdir -p "${DEST_DIR}"
fi

if [ ! -d "${DEST_DIR}" ] || [ ! -w "${DEST_DIR}" ]; then
  echo "error: install directory '${DEST_DIR}' is not writable." >&2
  exit 1
fi

DEST="${DEST_DIR}/skillporter"
TMP_WORK="$(mktemp -d 2>/dev/null || mktemp -d -t skillporter-install)"
chmod 700 "${TMP_WORK}"
# Stage binary inside DEST_DIR via O_EXCL mktemp so final `mv -f` is an atomic same-filesystem rename(2)
TMP_BIN="$(mktemp "${DEST_DIR}/.skillporter.tmp.XXXXXXXX")"

cleanup() {
  rm -rf "${TMP_WORK}"
  rm -f "${TMP_BIN}"
}
trap cleanup EXIT INT TERM

fetch_url() {
  src_url="$1"
  out_file="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL --proto '=https,http' "${src_url}" -o "${out_file}"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "${out_file}" "${src_url}"
  else
    echo "error: curl or wget is required to download release artifacts." >&2
    return 1
  fi
}

compute_sha256() {
  target_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${target_file}" | awk '{print tolower($1)}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${target_file}" | awk '{print tolower($1)}'
  else
    python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "${target_file}"
  fi
}

ARTIFACT_URL="${RELEASE_BASE}/${VERSION}/skillporter.pyz"
SUMS_URL="${RELEASE_BASE}/${VERSION}/SHA256SUMS.txt"
SUMS_FILE="${TMP_WORK}/SHA256SUMS.txt"

if ! fetch_url "${ARTIFACT_URL}" "${TMP_BIN}"; then
  echo "error: failed to download release artifact ${ARTIFACT_URL} (refusing mutable branch fallback)." >&2
  exit 1
fi

if ! fetch_url "${SUMS_URL}" "${SUMS_FILE}"; then
  echo "error: failed to download release checksum manifest ${SUMS_URL}." >&2
  exit 1
fi

EXPECTED_SUM="$(awk '$2 == "skillporter.pyz" || $2 == "*skillporter.pyz" {print tolower($1); exit}' "${SUMS_FILE}")"
if ! printf '%s\n' "${EXPECTED_SUM}" | grep -Eq '^[0-9a-f]{64}$'; then
  echo "error: SHA256SUMS.txt does not contain a valid SHA-256 entry for skillporter.pyz." >&2
  exit 1
fi

ACTUAL_SUM="$(compute_sha256 "${TMP_BIN}")"
if [ "${ACTUAL_SUM}" != "${EXPECTED_SUM}" ]; then
  echo "error: SHA-256 integrity mismatch for skillporter.pyz (expected ${EXPECTED_SUM}, got ${ACTUAL_SUM})." >&2
  exit 1
fi

# Cryptographic authenticity / out-of-band provenance gate (fail-closed)
PROVENANCE_VERIFIED=0

if [ -n "${SKILLPORTER_SHA256:-}" ]; then
  PINNED_SUM="$(printf '%s' "${SKILLPORTER_SHA256}" | tr 'A-F' 'a-f')"
  if ! printf '%s\n' "${PINNED_SUM}" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "error: SKILLPORTER_SHA256 must be a 64-character hexadecimal SHA-256 digest." >&2
    exit 1
  fi
  if [ "${ACTUAL_SUM}" != "${PINNED_SUM}" ]; then
    echo "error: downloaded artifact SHA-256 (${ACTUAL_SUM}) does not match pinned SKILLPORTER_SHA256 (${PINNED_SUM})." >&2
    exit 1
  fi
  PROVENANCE_VERIFIED=1
fi

if [ -n "${SKILLPORTER_PUBLIC_KEY_FILE:-}" ]; then
  if [ ! -f "${SKILLPORTER_PUBLIC_KEY_FILE}" ]; then
    echo "error: SKILLPORTER_PUBLIC_KEY_FILE '${SKILLPORTER_PUBLIC_KEY_FILE}' does not exist." >&2
    exit 1
  fi
  if ! command -v openssl >/dev/null 2>&1; then
    echo "error: openssl is required to verify detached signature with SKILLPORTER_PUBLIC_KEY_FILE." >&2
    exit 1
  fi
  SIG_URL="${RELEASE_BASE}/${VERSION}/SHA256SUMS.txt.sig"
  SIG_FILE="${TMP_WORK}/SHA256SUMS.txt.sig"
  if ! fetch_url "${SIG_URL}" "${SIG_FILE}"; then
    echo "error: failed to download detached signature ${SIG_URL}." >&2
    exit 1
  fi
  if ! openssl dgst -sha256 -verify "${SKILLPORTER_PUBLIC_KEY_FILE}" -signature "${SIG_FILE}" "${SUMS_FILE}" >/dev/null 2>&1; then
    echo "error: cryptographic signature verification FAILED for SHA256SUMS.txt.sig." >&2
    exit 1
  fi
  PROVENANCE_VERIFIED=1
fi

if [ "${PROVENANCE_VERIFIED}" -eq 0 ] && [ "${SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM:-0}" != "1" ] && command -v gh >/dev/null 2>&1; then
  if gh attestation verify "${TMP_BIN}" --repo "${REPO}" --signer-workflow "${SIGNER_WORKFLOW}" >/dev/null 2>&1; then
    PROVENANCE_VERIFIED=1
  else
    echo "error: GitHub artifact attestation verification failed for ${VERSION}/skillporter.pyz." >&2
    echo "Ensure 'gh auth status' is active or verify out-of-band via SKILLPORTER_SHA256=<sha256>." >&2
    exit 1
  fi
fi

if [ "${PROVENANCE_VERIFIED}" -eq 0 ]; then
  if [ "${SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM:-0}" = "1" ]; then
    echo "warning: proceeding with same-origin SHA256SUMS.txt verification only (SKILLPORTER_ALLOW_UNATTESTED_CHECKSUM=1); origin provenance was not attested." >&2
  else
    echo "error: refusing to install unattested artifact (same-origin SHA256SUMS.txt alone does not prove publisher authenticity)." >&2
    echo "Provide an independent root of trust using one of:" >&2
    echo "  1. Install GitHub CLI ('gh') and authenticate so 'gh attestation verify' checks Sigstore OIDC provenance." >&2
    echo "  2. Pin the expected SHA-256 digest out of band: SKILLPORTER_SHA256=<64-hex> sh install.sh" >&2
    echo "  3. Verify a detached OpenSSL signature: SKILLPORTER_PUBLIC_KEY_FILE=/path/to/pub.pem sh install.sh" >&2
    exit 1
  fi
fi

# Structural archive check prior to installation (never executes payload during check)
if ! python3 -c 'import sys, zipfile; sys.exit(0 if zipfile.is_zipfile(sys.argv[1]) else 1)' "${TMP_BIN}"; then
  echo "error: downloaded artifact is not a valid Python zipapp archive." >&2
  exit 1
fi

chmod 755 "${TMP_BIN}"
mv -f "${TMP_BIN}" "${DEST}"

echo "Installed verified skillporter (${VERSION}, sha256:${ACTUAL_SUM}) to ${DEST}"
"${DEST}" --version
