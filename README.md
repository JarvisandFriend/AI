# Gemma on Termux (ARM64)

Run Gemma-4-E2B locally on your phone via Termux + llama.cpp.

## Why this is complicated

- Termux uses Bionic libc, not glibc. llama.cpp's vendored subprocess.h
  needs posix_spawn_file_actions_addchdir_np, which Bionic lacks — can't
  compile directly in Termux.
- Building inside proot-distro ubuntu OOMs/crashes on 4GB RAM with -j 8,
  and is slow even at -j 2.
- Fix: build on GitHub Actions' free ubuntu-24.04-arm runner, ship the
  binaries down.
- The binary still needs glibc to run, so it executes through
  proot-distro login ubuntu, not raw Termux.

## One-time setup

1. Push .github/workflows/build-arm64.yml to your repo.
2. GitHub Actions tab -> Build llama.cpp ARM64 -> Run workflow.
3. On phone: ./setup.sh (installs deps, downloads model + binaries)

## Running

./run.sh

## Gotchas hit along the way

| Problem | Fix |
|---|---|
| hf deps missing on fresh Termux | pip install huggingface_hub --no-deps + manual deps |
| Single-connection HF download slow | aria2c -x 8 -s 8 |
| hf_transfer won't build (no Rust/Android target) | skip it |
| git clone drops on flaky connection | git clone --depth 1 |
| -j 8 compile OOMs on 4GB RAM | -j 2, or build on Actions |
| Termux binary aborts: TLS segment underaligned | run through proot-distro ubuntu |
| wget/aria2c get 403 on GitHub artifact download | Azure blob rejects forwarded auth header, use curl -L |
| gh run download errors path traversal | use gh api ... archive_download_url + curl instead |
| Missing .so at runtime | upload the whole build/bin/ folder, not individual files |
| Slow generation | GGML_NATIVE=OFF alone drops ARM dotprod/i8mm accel — add -DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+i8mm |
| Model just thinks, never answers | -n too low, raise to -n 1024+ |
