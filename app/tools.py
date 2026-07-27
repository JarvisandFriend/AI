"""
tools.py
-----------------------------------------------------------------------
Tool registry for Finch. Kept deliberately small, flat, and easy to
extend — add a new tool by adding one entry to TOOL_DECLARATIONS and
one function to TOOL_ADAPTERS. Nothing else needs to change.

Design notes (matters more than it looks like):
- Every schema is flat (no nested objects), 1-3 params per tool. Fewer,
  simpler tools means fewer wrong-tool / malformed-args mistakes from a
  smaller local model.
- Args are validated against the declared schema BEFORE execution. A
  missing/wrong-typed arg returns a clear error string back to the model
  instead of throwing — the model can self-correct on the next turn.
- All tools operate relative to WORKDIR (set by the agent from --dir or
  cwd). Paths are resolved and checked to stay inside WORKDIR — this is
  basic jailing, not OS-level sandboxing. Don't point --dir at anything
  you don't trust running arbitrary shell commands against.
- autoApprove is 'all' by design for this project — every tool call
  runs immediately, no permission prompts. That's a deliberate choice
  for a local, single-user tool; know that before adding tools that
  could do something destructive by default.
-----------------------------------------------------------------------
"""

import os
import json
import subprocess
import fnmatch
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


class ToolError(Exception):
    pass


def _resolve_safe(workdir, rel_path):
    """Resolve a relative path against workdir, refusing to escape it."""
    full = os.path.realpath(os.path.join(workdir, rel_path))
    workdir_real = os.path.realpath(workdir)
    if not (full == workdir_real or full.startswith(workdir_real + os.sep)):
        raise ToolError(f"Path '{rel_path}' escapes the working directory — refused.")
    return full


# -------------------------------------------------------------------------
# Tool schema (flat, OpenAI-function-style declarations)
# -------------------------------------------------------------------------
TOOL_DECLARATIONS = [
    {
        "name": "read_file",
        "description": "Read the full contents of a text file, relative to the working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a file or overwrite it entirely with new content. Use for new files or full rewrites.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "content": {"type": "string", "description": "Full new file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Replace one exact, unique occurrence of `search` with `replace` in an "
            "existing file. Prefer this over write_file for small changes. Include "
            "enough surrounding context in `search` that it matches only once."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative file path"},
                "search": {"type": "string", "description": "Exact existing text to find (must match exactly once)"},
                "replace": {"type": "string", "description": "Text to replace it with"},
            },
            "required": ["path", "search", "replace"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and folders at a path, relative to the working directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative directory path, default '.'"},
                "recursive": {"type": "boolean", "description": "List subdirectories too, default false"},
            },
        },
    },
    {
        "name": "search_files",
        "description": (
            "Search file contents for a plain text pattern across the working directory. "
            "Use this before read_file to locate where something is, instead of guessing paths."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
                "path": {"type": "string", "description": "Relative directory to search within, default '.'"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command in the working directory and wait for it to finish. "
            "Do not use this to start long-running/background processes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Full shell command, e.g. 'ls -la'"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for current information — news, docs, prices, versions, "
            "anything that could have changed recently or that you're not sure about. "
            "Returns a grounded answer with source citations. Uses Gemini's Google "
            "Search grounding under the hood."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"}
            },
            "required": ["query"],
        },
    },
]


# -------------------------------------------------------------------------
# Arg validation
# -------------------------------------------------------------------------
def validate_args(tool_name, args):
    decl = next((t for t in TOOL_DECLARATIONS if t["name"] == tool_name), None)
    if decl is None:
        return f"Unknown tool: {tool_name}"

    props = decl["parameters"].get("properties", {})
    required = decl["parameters"].get("required", [])

    for key in required:
        if key not in args or args[key] is None:
            return f"Missing required argument '{key}' for {tool_name}"

    for key, val in args.items():
        schema = props.get(key)
        if not schema:
            continue  # ignore unexpected extra args rather than failing the whole call
        expected = schema.get("type")
        actual = "array" if isinstance(val, list) else type(val).__name__
        type_map = {"string": "str", "number": "float", "boolean": "bool", "array": "array", "object": "dict"}
        if expected == "string" and not isinstance(val, str):
            return f"Argument '{key}' for {tool_name} should be string, got {actual}"
        if expected == "boolean" and not isinstance(val, bool):
            return f"Argument '{key}' for {tool_name} should be boolean, got {actual}"
        if expected == "number" and not isinstance(val, (int, float)):
            return f"Argument '{key}' for {tool_name} should be number, got {actual}"

    return None  # valid


# -------------------------------------------------------------------------
# Tool adapters — actual local filesystem/shell implementations.
# All operate relative to `workdir`.
# -------------------------------------------------------------------------
def make_tool_adapters(workdir):
    def read_file(path):
        full = _resolve_safe(workdir, path)
        if not os.path.isfile(full):
            return {"error": f"File not found: {path}"}
        try:
            with open(full, "r", errors="replace") as f:
                return {"content": f.read()}
        except IOError as e:
            return {"error": str(e)}

    def write_file(path, content):
        full = _resolve_safe(workdir, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        try:
            with open(full, "w") as f:
                f.write(content)
            return {"output": f"wrote {len(content)} bytes to {path}"}
        except IOError as e:
            return {"error": str(e)}

    def edit_file(path, search, replace):
        full = _resolve_safe(workdir, path)
        if not os.path.isfile(full):
            return {"error": f"File not found: {path}"}
        with open(full, "r", errors="replace") as f:
            original = f.read()
        count = original.count(search)
        if count == 0:
            return {"error": f'"{search}" not found in {path}'}
        if count > 1:
            return {"error": f'"{search}" matches {count} times in {path} — must match exactly once. Add more context.'}
        updated = original.replace(search, replace)
        with open(full, "w") as f:
            f.write(updated)
        return {"output": f"replaced 1 occurrence in {path}"}

    def list_files(path=".", recursive=False):
        full = _resolve_safe(workdir, path)
        if not os.path.isdir(full):
            return {"error": f"Directory not found: {path}"}
        if not recursive:
            try:
                entries = sorted(os.listdir(full))
                return {"entries": entries}
            except OSError as e:
                return {"error": str(e)}
        results = []
        for root, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv")]
            for name in files:
                rel = os.path.relpath(os.path.join(root, name), full)
                results.append(rel)
        return {"entries": sorted(results)}

    def search_files(query, path="."):
        full = _resolve_safe(workdir, path)
        if not os.path.isdir(full):
            return {"error": f"Directory not found: {path}"}
        matches = []
        skip_dirs = {".git", "node_modules", "__pycache__", ".venv"}
        for root, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                fpath = os.path.join(root, name)
                try:
                    with open(fpath, "r", errors="ignore") as f:
                        for i, line in enumerate(f, start=1):
                            if query in line:
                                rel = os.path.relpath(fpath, workdir)
                                matches.append({"file": rel, "line": i, "text": line.strip()[:300]})
                                if len(matches) >= 200:
                                    return {"matches": matches, "truncated": True}
                except (IOError, UnicodeDecodeError):
                    continue
        return {"matches": matches, "truncated": False}

    def run_command(command):
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            }
        except subprocess.TimeoutExpired:
            return {"error": "command timed out after 60s"}
        except Exception as e:
            return {"error": str(e)}

    def web_search(query):
        if not GEMINI_API_KEY:
            return {"error": "GEMINI_API_KEY is not set. Run 'finch --set search' to add one."}
        try:
            resp = requests.post(
                GEMINI_URL,
                params={"key": GEMINI_API_KEY},
                json={
                    "contents": [{"parts": [{"text": query}]}],
                    "tools": [{"google_search": {}}],
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            return {"error": f"Gemini search request failed: {e}"}

        data = resp.json()
        try:
            candidate = data["candidates"][0]
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        except (KeyError, IndexError):
            return {"error": f"Unexpected Gemini response: {json.dumps(data)[:500]}"}

        sources = []
        grounding = candidate.get("groundingMetadata", {})
        for chunk in grounding.get("groundingChunks", []):
            web = chunk.get("web", {})
            if web.get("uri"):
                sources.append({"title": web.get("title", ""), "url": web["uri"]})

        return {"answer": text, "sources": sources}

    return {
        "read_file": lambda args: read_file(args["path"]),
        "write_file": lambda args: write_file(args["path"], args["content"]),
        "edit_file": lambda args: edit_file(args["path"], args["search"], args["replace"]),
        "list_files": lambda args: list_files(args.get("path", "."), args.get("recursive", False)),
        "search_files": lambda args: search_files(args["query"], args.get("path", ".")),
        "run_command": lambda args: run_command(args["command"]),
        "web_search": lambda args: web_search(args["query"]),
    }
