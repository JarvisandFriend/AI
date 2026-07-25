#!/bin/bash
set -e

MODEL=$(find ./models -name "*.gguf" | head -n 1)

./llama.cpp/build/bin/llama-cli -m "$MODEL" -p "Hello" -c 4096
