#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL="deepseek-r1:8b"
MISSING_BLOB="${ROOT_DIR}/.ollama/models/blobs/sha256-e6a7edc1a4d7d9b2de136a221a57336b76316cfe53a252aeba814496c5ae439d"

if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: ollama is not installed or not in PATH."
  echo "Install Ollama first: https://ollama.com/download"
  exit 1
fi

export OLLAMA_MODELS="${ROOT_DIR}/.ollama/models"
mkdir -p "${OLLAMA_MODELS}"

echo "Using OLLAMA_MODELS=${OLLAMA_MODELS}"
echo "Pulling model ${MODEL}..."
ollama pull "${MODEL}"

if [[ -f "${MISSING_BLOB}" ]]; then
  echo "OK: Missing blob restored:"
  echo "${MISSING_BLOB}"
else
  echo "Model pull finished, but exact blob file path was not found."
  echo "This may happen if Ollama storage layout differs on your system."
fi
