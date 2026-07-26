import requests
import os
import json
import sys

HF_TOKEN = os.environ.get("HF_TOKEN")
SPACE_URL = "https://rtgcortex-movies.hf.space"

# --- Terminal styling ---
GREY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"


def ask_brain(prompt):
    resp = requests.post(
        f"{SPACE_URL}/chat/stream",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json={"prompt": prompt},
        stream=True
    )
    resp.raise_for_status()

    full_content = ""
    reasoning_started = False
    answer_started = False

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload.strip() == "[DONE]":
            break

        chunk = json.loads(payload)
        delta = chunk["choices"][0]["delta"]
        reasoning = delta.get("reasoning_content")
        text = delta.get("content")

        if reasoning:
            if not reasoning_started:
                print(f"{GREY}(thinking...)", end="", flush=True)
                reasoning_started = True
            print(f"{GREY}{reasoning}{RESET}", end="", flush=True)

        if text:
            if not answer_started:
                if reasoning_started:
                    print()  # newline after thinking block
                print(f"{GREEN}{BOLD}Brain:{RESET} ", end="", flush=True)
                answer_started = True
            print(text, end="", flush=True)
            full_content += text

    print()
    return full_content


def print_banner():
    print(f"{CYAN}{BOLD}")
    print("╔══════════════════════════════════════╗")
    print("║           LOCAL AGENT CLI             ║")
    print("║      brain: gemma-4-E2B (remote)      ║")
    print("╚══════════════════════════════════════╝")
    print(f"{RESET}")
    print(f"{GREY}Type your message, or 'exit'/'quit' to leave.{RESET}\n")


def main():
    if not HF_TOKEN:
        print(f"{YELLOW}Warning: HF_TOKEN is not set in environment.{RESET}")

    print_banner()

    while True:
        try:
            user_input = input(f"{BOLD}You:{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{GREY}Goodbye.{RESET}")
            sys.exit(0)

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print(f"{GREY}Goodbye.{RESET}")
            break

        try:
            ask_brain(user_input)
        except requests.exceptions.RequestException as e:
            print(f"{YELLOW}Request failed: {e}{RESET}")


if __name__ == "__main__":
    main()
