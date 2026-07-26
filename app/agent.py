import requests
import os
import json
import sys
import argparse

HF_TOKEN = os.environ.get("HF_TOKEN")
SPACE_URL = "https://rtgcortex-movies.hf.space"
HISTORY_FILE = "./history.json"

# --- Terminal styling ---
GREY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"


SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are Finch, a friendly and casual general-purpose assistant. "
        "Keep your tone warm, relaxed, and conversational — like chatting with "
        "a helpful friend, not a formal support agent. Be direct and clear, "
        "avoid unnecessary formality, and don't be afraid to show a little "
        "personality."
    )
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
                if history and history[0].get("role") == "system":
                    return history
                return [SYSTEM_PROMPT] + history
        except (json.JSONDecodeError, IOError):
            return [SYSTEM_PROMPT]
    return [SYSTEM_PROMPT]


def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def ask_brain(history, no_thinking=False):
    payload = {"messages": history}
    if no_thinking:
        payload["no_thinking"] = True

    resp = requests.post(
        f"{SPACE_URL}/chat/stream",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json=payload,
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
        payload_line = line[len("data: "):]
        if payload_line.strip() == "[DONE]":
            break

        chunk = json.loads(payload_line)
        delta = chunk["choices"][0]["delta"]
        reasoning = delta.get("reasoning_content")
        text = delta.get("content")

        if reasoning:
            if not reasoning_started:
                print(f"{GREY}", end="", flush=True)
                reasoning_started = True
            print(f"{reasoning}", end="", flush=True)

        if text:
            if not answer_started:
                if reasoning_started:
                    print(f"{RESET}")
                answer_started = True
            print(text, end="", flush=True)
            full_content += text

    print()
    return full_content


def print_banner(no_thinking):
    print(f"{YELLOW}{BOLD}")
    print("╔══════════════════════════════════════╗")
    print("║                FINCH                  ║")
    print("╚══════════════════════════════════════╝")
    print(f"{RESET}")
    mode = "no-thinking (fast)" if no_thinking else "thinking (default)"
    print(f"{GREY}Mode: {mode}{RESET}")
    print(f"{GREY}Commands: /clear (wipe screen + history), /read <path> (load a file), /exit or /reset{RESET}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-thinking", action="store_true", help="Skip the model's reasoning phase for faster responses")
    args = parser.parse_args()

    if not HF_TOKEN:
        print(f"{YELLOW}Warning: HF_TOKEN is not set in environment.{RESET}")

    print_banner(args.no_thinking)
    history = load_history()
    if history:
        print(f"{GREY}(loaded {len(history)} previous messages from {HISTORY_FILE}){RESET}\n")

    while True:
        try:
            user_input = input(f"{GREEN}{BOLD}>{RESET} {GREEN}").strip()
            sys.stdout.write(RESET)
        except (EOFError, KeyboardInterrupt):
            print(f"\n{GREY}Goodbye.{RESET}")
            sys.exit(0)

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit", "/exit"):
            print(f"{GREY}Goodbye.{RESET}")
            break

        if user_input.lower() in ("reset", "/reset"):
            history = [SYSTEM_PROMPT]
            save_history(history)
            print(f"{GREY}History cleared.{RESET}\n")
            continue

        if user_input.lower() == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            if os.path.exists(HISTORY_FILE):
                os.remove(HISTORY_FILE)
            history = [SYSTEM_PROMPT]
            print_banner(args.no_thinking)
            continue

        if user_input.lower().startswith("/read "):
            file_path = user_input[len("/read "):].strip()
            if not os.path.exists(file_path):
                print(f"{YELLOW}File not found: {file_path}{RESET}\n")
                continue
            try:
                with open(file_path, "r", errors="replace") as f:
                    file_content = f.read()
            except IOError as e:
                print(f"{YELLOW}Could not read file: {e}{RESET}\n")
                continue
            user_input = f"Here is the content of {file_path}:\n\n{file_content}"

        history.append({"role": "user", "content": user_input})

        try:
            answer = ask_brain(history, no_thinking=args.no_thinking)
            history.append({"role": "assistant", "content": answer})
            save_history(history)
        except requests.exceptions.RequestException as e:
            print(f"{YELLOW}Request failed: {e}{RESET}")
            history.pop()


if __name__ == "__main__":
    main()
