#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="$PROJECT_DIR/.local/whisper.cpp"
MODEL_NAME="${WHISPER_LOCAL_MODEL:-small-q5_1}"
MODEL_FILE="$INSTALL_DIR/models/ggml-$MODEL_NAME.bin"
CMAKE_RUNNER="$PROJECT_DIR/.venv/bin/cmake"

if [[ ! -x "$CMAKE_RUNNER" ]]; then
  "$PROJECT_DIR/.venv/bin/python" -m pip install "cmake>=3.16"
fi

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "$INSTALL_DIR"
fi

"$CMAKE_RUNNER" -S "$INSTALL_DIR" -B "$INSTALL_DIR/build" -DCMAKE_BUILD_TYPE=Release
"$CMAKE_RUNNER" --build "$INSTALL_DIR/build" --config Release --target whisper-cli --parallel "$(nproc)"

if [[ ! -f "$MODEL_FILE" ]]; then
  bash "$INSTALL_DIR/models/download-ggml-model.sh" "$MODEL_NAME"
fi

"$INSTALL_DIR/build/bin/whisper-cli" --version
echo "Local Whisper ready: $MODEL_FILE"
