#!/bin/bash
set -e

REPO="JarvisandFriend/AI"
MODEL_REPO="unsloth/gemma-4-E2B-it-GGUF"
MODEL_FILE="gemma-4-E2B-it-Q4_K_M.gguf"

echo "== Installing base packages =="
pkg update -y
pkg install -y aria2 gh proot-distro python git

echo "== Installing hf CLI deps =="
pip install huggingface_hub --no-deps
pip install requests tqdm filelock pyyaml packaging typing-extensions fsspec click httpx

echo "== HuggingFace login =="
hf auth login

mkdir -p ~/AI/models
cd ~/AI

echo "== Downloading model =="
TOKEN=$(cat ~/.cache/huggingface/token)
aria2c -x 8 -s 8 -k 1M \
  --header "Authorization: Bearer $TOKEN" \
  -d ./models -o "$MODEL_FILE" \
  "https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILE}"

echo "== Fetching prebuilt ARM64 binaries =="
ARTIFACT_URL=$(gh api "repos/${REPO}/actions/artifacts" \
  --jq '.artifacts[] | select(.name=="llama-arm64-binaries") | .archive_download_url' | head -1)

if [ -z "$ARTIFACT_URL" ]; then
  echo "No artifact found. Run the build-arm64.yml workflow on GitHub first."
  exit 1
fi

curl -L -H "Authorization: token $(gh auth token)" -o binaries.zip "$ARTIFACT_URL"
rm -rf llama-bin && mkdir llama-bin
unzip -q binaries.zip -d llama-bin
rm binaries.zip

chmod +x llama-bin/llama-cli llama-bin/llama-server

echo "== Done. Run ./run.sh to start chatting. =="
