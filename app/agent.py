import os
import json
import sys
import argparse
import requests
from tools import TOOL_DECLARATIONS, validate_args, make_tool_adapters
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.style import Style

console = Console()
DIM_STYLE = Style(color="grey50")

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY")
DEFAULT_MODEL = os.environ.get("MISTRAL_MODEL", "mistral-large-latest")
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
FINCH_HOME = os.environ.get("FINCH_HOME", os.path.expanduser("~/.finch"))
HISTORY_FILE = os.path.join(FINCH_HOME, "history.json")

# --- Terminal styling ---
GREY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN_BOLD = "\033[96m\033[1m"


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

MISTRAL_TOOLS = [
    {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
    for t in TOOL_DECLARATIONS
]


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
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def _clean_messages_for_mistral(history):
    """Mistral wants tool_calls omitted (not null) when absent, and every
    'tool' message needs a matching preceding assistant tool_calls entry —
    both already hold true given how this app builds history, but we strip
    None fields defensively since the API is strict about null keys."""
    cleaned = []
    for msg in history:
        m = {k: v for k, v in msg.items() if v is not None}
        cleaned.append(m)
    return cleaned


def ask_brain(model, history, use_tools=True):
    """Streams a response from the raw Mistral REST API. Returns
    {'content': str, 'tool_calls': list|None}."""
    payload = {
        "model": model,
        "messages": _clean_messages_for_mistral(history),
        "stream": True,
    }
    if use_tools:
        payload["tools"] = MISTRAL_TOOLS
        payload["tool_choice"] = "auto"

    try:
        resp = requests.post(
            MISTRAL_API_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {MISTRAL_API_KEY}",
            },
            json=payload,
            stream=True,
            timeout=120,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:500]
        except Exception:
            pass
        print(f"{YELLOW}Mistral API error: {e}{RESET}")
        if body:
            print(f"{YELLOW}{body}{RESET}")
        return {"content": "", "tool_calls": None}
    except requests.exceptions.RequestException as e:
        print(f"{YELLOW}Mistral API error: {e}{RESET}")
        return {"content": "", "tool_calls": None}

    full_content = ""
    tool_calls_by_index = {}
    answer_started = False
    live = None

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

            try:
                chunk = json.loads(payload_line)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}

            text = delta.get("content")
            delta_tool_calls = delta.get("tool_calls")

            if text:
                if not answer_started:
                    answer_started = True
                    live = Live(console=console, refresh_per_second=12, vertical_overflow="visible")
                    live.start()
                full_content += text
                live.update(Markdown(full_content))

            if delta_tool_calls:
                for tc in delta_tool_calls:
                    idx = tc.get("index", 0) or 0
                    if idx not in tool_calls_by_index:
                        tool_calls_by_index[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    acc = tool_calls_by_index[idx]

                    tc_id = tc.get("id")
                    if tc_id:
                        acc["id"] = tc_id

                    fn = tc.get("function") or {}
                    fn_name = fn.get("name")
                    fn_args = fn.get("arguments")
                    if fn_name:
                        acc["function"]["name"] += fn_name
                    if fn_args:
                        # Guard against a provider sending a full JSON object
                        # in one chunk rather than string fragments.
                        if isinstance(fn_args, str):
                            acc["function"]["arguments"] += fn_args
                        else:
                            acc["function"]["arguments"] += json.dumps(fn_args)
    finally:
        if live is not None:
            live.stop()
        resp.close()

    if not answer_started:
        print()

    tool_calls = list(tool_calls_by_index.values()) if tool_calls_by_index else None
    return {"content": full_content, "tool_calls": tool_calls}


def print_banner(model):
    print(f"{YELLOW}{BOLD}")
    print("╔══════════════════════════════════════╗")
    print("║                FINCH                  ║")
    print("╚══════════════════════════════════════╝")
    print(f"{RESET}")
    print(f"{GREY}Model: {model}{RESET}")
    print(f"{GREY}Commands: /clear (wipe screen + history), /read <path> (load a file), /exit or /reset{RESET}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Mistral model to use (default: mistral-large-latest, or $MISTRAL_MODEL)")
    parser.add_argument("--dir", default=".", help="Working directory the agent's tools operate in (default: current directory)")
    args = parser.parse_args()

    workdir = os.path.abspath(args.dir)
    if not os.path.isdir(workdir):
        print(f"{YELLOW}Directory not found: {workdir}{RESET}")
        sys.exit(1)

    tool_adapters = make_tool_adapters(workdir)

    if not MISTRAL_API_KEY:
        print(f"{YELLOW}Warning: MISTRAL_API_KEY is not set in environment.{RESET}")

    print_banner(args.model)
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
            print_banner(args.model)
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
                result = ask_brain(args.model, history, use_tools=True)
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
