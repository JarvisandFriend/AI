# Gemma on Termux (ARM64)

Runs Gemma-4-E2B locally on an Android phone, via Termux + llama.cpp.

## How it works

llama.cpp can't be compiled directly on Termux (missing libc function).
Instead, GitHub Actions builds the ARM64 binaries in a proper Linux
environment, and the phone downloads the finished binaries rather than
building them itself. setup.sh handles this end to end.

## Setup

