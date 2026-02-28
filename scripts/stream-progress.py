#!/usr/bin/env python3
"""Filter claude stream-json into progress lines on stderr, log everything to file.

Usage: echo prompt | claude -p --output-format stream-json 2>&1 | python3 -u stream-progress.py <logfile>

Reads NDJSON from stdin. Writes every line to the log file. Prints
human-readable progress to stderr so the user sees activity.

Event types from claude -p --output-format stream-json:
  {"type": "system", "subtype": "init|task_started|task_progress|task_notification|hook_*"}
  {"type": "assistant", "message": {"content": [{"type": "text|tool_use|thinking", ...}]}}
  {"type": "user", "message": {"content": [{"type": "tool_result", ...}]}}
  {"type": "rate_limit_event", "rate_limit_info": {...}}
  {"type": "result", "num_turns": N, "duration_ms": N}
"""
import json
import os
import sys
import time

if len(sys.argv) < 2:
    print("Usage: stream-progress.py <logfile>", file=sys.stderr)
    sys.exit(1)

log_path = sys.argv[1]

# --- state ---
tasks = {}  # task_id -> {description, tool_count, started_at}
is_tty = sys.stderr.isatty()
try:
    cols = os.get_terminal_size(sys.stderr.fileno()).columns
except (OSError, ValueError):
    cols = 80


def _clear():
    """Clear the overwriting status line (TTY only)."""
    if is_tty:
        print(f"\r{' ' * (cols - 1)}\r", end="", file=sys.stderr, flush=True)


def _out(msg):
    """Print a permanent line to stderr."""
    _clear()
    print(msg, file=sys.stderr, flush=True)


def _status():
    """Overwrite a single status line showing active agent count (TTY only)."""
    if not is_tty or not tasks:
        return
    active = len(tasks)
    total_tools = sum(t.get("tool_count", 0) for t in tasks.values())
    newest = max(tasks.values(), key=lambda t: t.get("updated", 0))
    desc = newest.get("short_desc", "")
    if len(desc) > 50:
        desc = desc[:47] + "..."
    line = f"  ... {active} agent(s) | {total_tools} tools | {desc}"
    line = line[: cols - 1]
    print(f"\r{line}", end="", file=sys.stderr, flush=True)


# --- main loop ---
with open(log_path, "a") as log:
    for line in sys.stdin:
        log.write(line)
        log.flush()

        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue

        etype = event.get("type", "")

        # --- system events ---
        if etype == "system":
            sub = event.get("subtype", "")

            if sub == "task_started":
                desc = event.get("description", "agent")
                tid = event.get("task_id", "")
                tasks[tid] = {
                    "description": desc,
                    "short_desc": desc,
                    "tool_count": 0,
                    "updated": time.time(),
                }
                _out(f"  \u2192 {desc}")
                _status()

            elif sub == "task_progress":
                tid = event.get("task_id", "")
                usage = event.get("usage", {})
                desc = event.get("description", "")
                if tid in tasks:
                    tasks[tid]["tool_count"] = usage.get("tool_uses", 0)
                    tasks[tid]["short_desc"] = desc
                    tasks[tid]["updated"] = time.time()
                _status()

            elif sub == "task_notification":
                tid = event.get("task_id", "")
                usage = event.get("usage", {})
                status = event.get("status", "")
                tools_n = usage.get("tool_uses", 0)
                dur_ms = usage.get("duration_ms", 0)
                task_info = tasks.pop(tid, {})
                desc = task_info.get("description", event.get("summary", "agent"))
                dur_s = dur_ms / 1000
                if status == "completed":
                    _out(f"  \u2713 {desc} ({tools_n} tools, {dur_s:.0f}s)")
                else:
                    _out(f"  \u2717 {desc} \u2014 {status}")
                _status()

            elif sub == "status":
                status = event.get("status", "")
                if status == "compacting":
                    _out("  ... compacting context")

            # init, hook_started, hook_response — skip

        # --- assistant turns ---
        elif etype == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                btype = block.get("type", "")
                if btype == "tool_use":
                    name = block.get("name", "?")
                    if name in ("Agent", "TodoWrite", "TaskOutput"):
                        continue
                    _out(f"  \u21b3 {name}")
                elif btype == "text":
                    text = block.get("text", "").strip()
                    if text and len(text) < 200:
                        _out(f"  {text}")
                # thinking — skip

        # --- rate limits ---
        elif etype == "rate_limit_event":
            info = event.get("rate_limit_info", {})
            if info.get("status") != "allowed":
                _out("  \u26a0 rate limited \u2014 waiting")

        # --- final result ---
        elif etype == "result":
            turns = event.get("num_turns", 0)
            dur = event.get("duration_ms", 0)
            is_err = event.get("is_error", False)
            err_msg = event.get("result", "")
            cost = event.get("total_cost_usd", 0)
            dur_s = f", {dur / 1000:.0f}s" if dur else ""
            cost_s = f", ${cost:.2f}" if cost else ""
            if is_err:
                _out(f"  FAILED: {err_msg} ({turns} turns{dur_s}{cost_s})")
            else:
                _out(f"  done ({turns} turns{dur_s}{cost_s})")

# Clean up any lingering status line
_clear()
