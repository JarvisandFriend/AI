import requests
import os
import json
import sys
import argparse
import re
from tools import TOOL_DECLARATIONS, validate_args, make_tool_adapters
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.style import Style
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import ANSI
import threading

console = Console()
DIM_STYLE = Style(color="grey50")

SPACE_URL = os.environ.get("FINCH_SERVER_URL", "https://counters-editors-tunnel-survey.trycloudflare.com")
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "history.json")


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
        "You are Finch, an automation and workflow tool."
        "Be useful in managing github accounts, use gh which is github cli, run gh auth login to login github before u do that first check auth status"
        "You are always in the users environment which is linux locally and not a remote server, use linux tools to automate tasks and make work easier, use run command more frequently, always figure out a command to run\n"
        "Ask less questions use commands to check for yourself"
        "RUN THE COMMANDS YOURSELF NEVER GIVE INSTRUCTIONS ON HOW TO DO IT. Use run_command tool to use most tools that linux provides in users machine."
        "You are in the user's terminal, run commands for him to save him the stress of having to google how to do it, no instructions, no questions only perform actions"
        "WHAT NOT TO DO:\n give a response like this:\n > I could not retrieve information from your GitHub because the authentication token is  invalid.Please run gh auth login to log in  again so I can access your repositories.\n"
        "Run the commands yourself never instruct the user to do it. Never give up try harder and harder until 1000 times, that's when u stop, u can't assume impossible. You are allowed to break system packages as u might as well fix them, run as long as it takes without stopping, only stop when u reach the goal"
        "Call the tools do not return them as text response, try to be smart. call the tools not use them as a response"  
        "If gh auth status fails or any gh command returns Bad credentials/401, DO NOT just report the error to the user. Immediately run: gh auth login --web --git-protocol https --hostname github.com > ./gh_login.log 2>&1 & then wait 2 seconds and read ./gh_login.log (relative to the working directory) to get the one-time code and URL. Show the code and URL to the user immediately. This is the required recovery action, not optional, do it automatically without being asked. The process runs in background waiting for browser authorization. Once the user confirms they completed it, run gh auth status to verify."
        "When a task fails, do NOT stop or report failure. Try every possible angle: check and set environment variables, modify config files, change system settings, try alternative commands, install missing tools, change approach entirely. Only stop when the goal is achieved or you have genuinely exhausted every possible method across at least 50 different attempts."
        "When a command fails, NEVER retry the exact same command twice. Each retry must be a different approach: fix the error in the file, install a missing dependency, set a missing env var, change a flag, use an alternative tool, check logs for root cause first, or fundamentally change strategy."
        "Before retrying anything, read the error message carefully and diagnose the root cause. If a file has a bug, fix the file. If a tool is missing, install it. If a config is wrong, change it. If the approach is wrong, use a completely different one."
        "Track what you have already tried mentally and never repeat it. Progress means each attempt is meaningfully different from the last."
        "For downloading videos or music, always use the download_video tool, never try to do it manually."
        "For any other interactive CLI prompts (npm init, git commit without -m, confirmations, editors, pagers), NEVER run the interactive form blind. Pass flags to skip prompts: --yes, --no-edit, --force, or pipe input directly."
  ) 
}

def extract_leaked_tool_call(content):
    """Fallback: recover tool calls the model leaked as raw text instead of proper tool_calls."""
    patterns = [
        r'(\w+)\{command:\s*<\|"\|>(.+?)<\|"\|>\}(?:<tool_call\|>)?',
        r'(\w+)\{command:\s*"(.+?)"\}(?:<tool_call\|>)?',
        r"(\w+)\{command:\s*'(.+?)'\}(?:<tool_call\|>)?",
        r'(\w+)\("(.+?)"\)(?:<tool_call\|>)?',
        r"(\w+)\('(.+?)'\)(?:<tool_call\|>)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            name, command = match.group(1), match.group(2).strip()
            return [{"id": "leaked-fallback", "function": {"name": name, "arguments": json.dumps({"command": command})}}]
    return None

MAX_TOOL_TURNS = 2000

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


def ask_brain(history, no_thinking=False, use_tools=True, stop_event=None):
    """Streams a response. Returns {'content': str, 'tool_calls': list|None}."""
    payload = {"messages": history}
    if no_thinking:
        payload["no_thinking"] = True
    if use_tools:
        payload["tools"] = OPENAI_TOOLS
        payload["tool_choice"] = "auto"

    resp = requests.post(
        f"{SPACE_URL}/chat/stream",
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
            if stop_event and stop_event.is_set():
                break
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
    if not tool_calls and full_content:
        leaked = extract_leaked_tool_call(full_content)
        if leaked:
            tool_calls = leaked
            full_content = ""
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

    print_banner(args.no_thinking)
    print(f"{GREY}Working directory: {workdir}{RESET}")
    history = load_history()
    if history:
        print(f"{GREY}(loaded {len(history)} previous messages from {HISTORY_FILE}){RESET}\n")

    session = PromptSession(history=FileHistory(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".finch_input_history")))
    while True:
        try:
            user_input = session.prompt("> ", ).strip()
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
                stop_event = threading.Event()
                result = ask_brain(history, no_thinking=args.no_thinking, use_tools=True, stop_event=stop_event)
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
        except KeyboardInterrupt:
            print(f"\n{GREY}Cancelled.{RESET}")
            if stop_event:
                stop_event.set()
            history.pop()
            continue
        except requests.exceptions.RequestException as e:
            print(f"{YELLOW}Request failed: {e}{RESET}")
            history.pop()


if __name__ == "__main__":
    main()
