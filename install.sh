#!/usr/bin/env sh
# Skillporter universal one-line installer (Linux & macOS)
# Bypasses PEP 668 externally-managed-environment by installing the
# zero-dependency standalone zipapp directly to /usr/local/bin or ~/.local/bin.
set -eu

REPO="Shanmukh-l33t/skillporter"
VERSION="${SKILLPORTER_VERSION:-v2.0.2}"
URL="https://github.com/${REPO}/releases/download/${VERSION}/skillporter.pyz"
FALLBACK_URL="https://raw.githubusercontent.com/${REPO}/main/npm/bin/skillporter.pyz"

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 (3.9+) is required to run skillporter." >&2
  exit 1
fi

if [ "$(id -u)" -eq 0 ] && [ -w "/usr/local/bin" ]; then
  DEST_DIR="/usr/local/bin"
elif [ -w "/usr/local/bin" ]; then
  DEST_DIR="/usr/local/bin"
else
  DEST_DIR="${HOME}/.local/bin"
  mkdir -p "${DEST_DIR}"
fi

DEST="${DEST_DIR}/skillporter"
TMP="$(mktemp)"
trap 'rm -f "${TMP}"' EXIT

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "${URL}" -o "${TMP}" 2>/dev/null || curl -fsSL "${FALLBACK_URL}" -o "${TMP}"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "${TMP}" "${URL}" 2>/dev/null || wget -qO "${TMP}" "${FALLBACK_URL}"
else
  echo "error: curl or wget is required." >&2
  exit 1
fi

chmod +x "${TMP}"
mv "${TMP}" "${DEST}"

echo "Installed skillporter to ${DEST}"
"${DEST}" --version
