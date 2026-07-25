#!/bin/bash
set -e

REPO="JarvisandFriend/AI"
MODEL_REPO="unsloth/gemma-4-E2B-it-GGUF"
MODEL_FILE="gemma-4-E2B-it-Q4_K_M.gguf"

echo "== Installing base packages =="
pkg update -y
pkg install -y aria2 gh proot-distro python git

echo "== GitHub login (needed to trigger the build) =="
gh auth login

echo "== Installing hf CLI deps =="
pip install huggingface_hub --no-deps
pip install requests tqdm filelock pyyaml packaging typing-extensions fsspec click httpx

mkdir -p ~/AI/models
cd ~/AI

if [ -f "models/$MODEL_FILE" ]; then
  echo "== Model already downloaded, skipping =="
else
  echo "== HuggingFace login =="
  hf auth login

  echo "== Downloading model =="
  TOKEN=$(cat ~/.cache/huggingface/token)
  aria2c -x 8 -s 8 -k 1M \
    --header "Authorization: Bearer $TOKEN" \
    -d ./models -o "$MODEL_FILE" \
    "https://huggingface.co/${MODEL_REPO}/resolve/main/${MODEL_FILE}"
fi

echo "== Building ARM64 binaries on GitHub Actions =="
gh workflow run build-arm64.yml --repo "$REPO"
sleep 5
RUN_ID=$(gh run list --repo "$REPO" --workflow build-arm64.yml --limit 1 --json databaseId --jq '.[0].databaseId')
echo "Build running (id $RUN_ID), this takes about 5-10 minutes..."
gh run watch "$RUN_ID" --repo "$REPO" --exit-status

echo "== Downloading binaries =="
ARTIFACT_URL=$(gh api "repos/${REPO}/actions/artifacts" \
  --jq '.artifacts[] | select(.name=="llama-arm64-binaries") | .archive_download_url' | head -1)
curl -L -H "Authorization: token $(gh auth token)" -o binaries.zip "$ARTIFACT_URL"
rm -rf llama-bin && mkdir llama-bin
unzip -q binaries.zip -d llama-bin
rm binaries.zip
chmod +x llama-bin/llama-cli llama-bin/llama-server

echo "== Done. Run ./run.sh to start chatting. =="
