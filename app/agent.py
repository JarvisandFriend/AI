import requests
import os
import json
import sys
import argparse
from tools import TOOL_DECLARATIONS, validate_args, make_tool_adapters
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.style import Style

console = Console()
DIM_STYLE = Style(color="grey50")

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
        "personality.\n\n"
        "You have tools available for working with files and running commands "
        "in the user's current working directory. You are NOT a coding-specific "
        "agent — these tools are just available if a task happens to need them. "
        "Most conversations won't need any tool at all — just chat normally. "
        "Only call a tool when the task actually requires it.\n\n"
        "VERIFICATION RULE — this matters a lot: a tool call succeeding "
        "(exit_code 0, no error) only means the command ran without crashing. "
        "It does NOT prove the outcome you wanted actually happened. Never assume "
        "success from that alone — always confirm with a follow-up check before "
        "telling the user something worked. For example:\n"
        "- After creating a directory or file, use list_files or read_file to "
        "confirm it actually exists with the expected content.\n"
        "- After 'cd'-ing somewhere, verify you're actually in that path (e.g. "
        "run_command with 'pwd') rather than assuming the cd succeeded silently.\n"
        "- Before starting a server on a port, check whether that port is already "
        "in use (e.g. run_command with something like 'lsof -i :3000' or "
        "'curl -s localhost:3000') rather than assuming it's free.\n"
        "- After starting a server, verify it's actually running and responding "
        "(e.g. curl the endpoint) rather than assuming a clean exit code means "
        "it's live — a long-running server process can behave unexpectedly "
        "with a synchronous command, so confirm with a real check.\n"
        "- If a command times out or errors, don't just retry blindly — check "
        "what state was left behind first (did it partially succeed?) before "
        "deciding what to do next.\n"
        "Always prefer one extra confirming tool call over reporting an "
        "assumed success to the user."
    )
}

MAX_TOOL_TURNS = 15

OPENAI_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
    for t in TOOL_DECLARATIONS
]


CYAN_BOLD = "\033[96m\033[1m"


def format_tool_args(args):
    if not args:
        return ""
    parts = [f"{k}={json.dumps(v) if not isinstance(v, str) else v!r}" for k, v in args.items()]
    joined = ", ".join(parts)
    return joined if len(joined) <= 80 else joined[:77] + "..."


def print_tool_tree(name, args, result, is_last=True):
    branch = "└──" if is_last else "├──"
    print(f"{GREY}{branch} {CYAN_BOLD} ⚙  {name} {RESET}{GREY} ({format_tool_args(args)}){RESET}")

    result_str = json.dumps(result)
    preview = result_str if len(result_str) <= 300 else result_str[:297] + "..."
    is_error = isinstance(result, dict) and "error" in result
    color = YELLOW if is_error else GREY
    connector = "    " if is_last else "│   "
    print(f"{connector}{color}└─ {preview}{RESET}\n")


def run_tool_call(name, args, tool_adapters):
    validation_error = validate_args(name, args)
    if validation_error:
        return {"error": validation_error}

    adapter = tool_adapters.get(name)
    if adapter is None:
        return {"error": f"Unknown tool: {name}"}

    try:
        return adapter(args)
    except Exception as e:
        return {"error": str(e)}


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


def ask_brain(history, no_thinking=False, use_tools=True):
    """Streams a response. Returns {'content': str, 'tool_calls': list|None}."""
    payload = {"messages": history}
    if no_thinking:
        payload["no_thinking"] = True
    if use_tools:
        payload["tools"] = OPENAI_TOOLS
        payload["tool_choice"] = "auto"

    resp = requests.post(
        f"{SPACE_URL}/chat/stream",
        headers={"Authorization": f"Bearer {HF_TOKEN}"},
        json=payload,
        stream=True
    )
    resp.raise_for_status()

    full_content = ""
    full_reasoning = ""
    tool_calls_by_index = {}
    reasoning_started = False
    answer_started = False
    reasoning_live = None
    live = None
    reasoning_since_render = 0
    content_since_render = 0
    RENDER_EVERY_N_CHARS = 20

    try:
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
            delta_tool_calls = delta.get("tool_calls")

            if reasoning:
                if not reasoning_started:
                    reasoning_started = True
                    reasoning_live = Live(console=console, refresh_per_second=8, vertical_overflow="visible")
                    reasoning_live.start()
                full_reasoning += reasoning
                reasoning_since_render += len(reasoning)
                if reasoning_since_render >= RENDER_EVERY_N_CHARS:
                    reasoning_live.update(Markdown(full_reasoning, style=DIM_STYLE))
                    reasoning_since_render = 0

            if text:
                if not answer_started:
                    if reasoning_live is not None:
                        reasoning_live.update(Markdown(full_reasoning, style=DIM_STYLE))
                        reasoning_live.stop()
                    answer_started = True
                    live = Live(console=console, refresh_per_second=8, vertical_overflow="visible")
                    live.start()
                full_content += text
                content_since_render += len(text)
                if content_since_render >= RENDER_EVERY_N_CHARS:
                    live.update(Markdown(full_content))
                    content_since_render = 0

            if delta_tool_calls:
                for tc in delta_tool_calls:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    acc = tool_calls_by_index[idx]
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        acc["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["function"]["arguments"] += fn["arguments"]
    finally:
        if live is not None:
            live.update(Markdown(full_content))
            live.stop()
        if reasoning_live is not None and answer_started is False:
            reasoning_live.update(Markdown(full_reasoning, style=DIM_STYLE))
            reasoning_live.stop()

    if not reasoning_started and not answer_started:
        print()

    tool_calls = list(tool_calls_by_index.values()) if tool_calls_by_index else None
    return {"content": full_content, "tool_calls": tool_calls}


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
    parser.add_argument("--dir", default=".", help="Working directory the agent's tools operate in (default: current directory)")
    args = parser.parse_args()

    workdir = os.path.abspath(args.dir)
    if not os.path.isdir(workdir):
        print(f"{YELLOW}Directory not found: {workdir}{RESET}")
        sys.exit(1)

    tool_adapters = make_tool_adapters(workdir)

    if not HF_TOKEN:
        print(f"{YELLOW}Warning: HF_TOKEN is not set in environment.{RESET}")

    print_banner(args.no_thinking)
    print(f"{GREY}Working directory: {workdir}{RESET}")
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
            for _ in range(MAX_TOOL_TURNS):
                result = ask_brain(history, no_thinking=args.no_thinking, use_tools=True)
                tool_calls = result.get("tool_calls")
                content = result.get("content")

                if not tool_calls:
                    history.append({"role": "assistant", "content": content})
                    break

                history.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {"id": tc["id"], "type": "function", "function": tc["function"]}
                        for tc in tool_calls
                    ]
                })

                for i, call in enumerate(tool_calls):
                    fn = call.get("function", {})
                    name = fn.get("name")
                    try:
                        call_args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        call_args = {}

                    tool_result = run_tool_call(name, call_args, tool_adapters)
                    print_tool_tree(name, call_args, tool_result, is_last=(i == len(tool_calls) - 1))

                    history.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(tool_result)
                    })
            save_history(history)
        except requests.exceptions.RequestException as e:
            print(f"{YELLOW}Request failed: {e}{RESET}")
            history.pop()


if __name__ == "__main__":
    main()
