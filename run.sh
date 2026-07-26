#!/bin/bash
set -e

proot-distro install ubuntu 2>/dev/null || true

MODEL="/data/data/com.termux/files/home/AI/models/gemma-4-E2B-it-Q4_K_M.gguf"
BIN="/data/data/com.termux/files/home/AI/llama-bin"

proot-distro login ubuntu -- bash -c "
  export LD_LIBRARY_PATH=${BIN}
  ${BIN}/llama-cli -m ${MODEL} -t 6 -c 2048 -b 512 --flash-attn on -n 1024
"
