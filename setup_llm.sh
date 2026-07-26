#!/bin/bash
set -e

sudo apt update
sudo apt install -y build-essential cmake git python3-pip

git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build
cmake --build build --config Release -j$(nproc)
cd ..

pip install -U huggingface_hub

mkdir -p models
hf download unsloth/gemma-4-E2B-it-GGUF \
  --include "*Q4_K_M*" --local-dir ./models

echo "=== Verifying model download ==="
find ./models -name "*.gguf" || { echo "ERROR: no .gguf file downloaded"; exit 1; }
