#!/usr/bin/env python3
"""Filter claude stream-json into progress lines on stderr, log everything to file.

Usage: echo prompt | claude -p --output-format stream-json 2>&1 | python3 -u stream-progress.py <logfile>

Reads stream-json from stdin. Writes every line to the log file. Prints
human-readable progress (tool calls) to stderr so the user sees activity.

Event schema (from claude -p --output-format stream-json):
  {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Read"}}}
  {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}}
  {"type": "stream_event", "event": {"type": "content_block_stop"}}
"""
import json
import sys

if len(sys.argv) < 2:
    print("Usage: stream-progress.py <logfile>", file=sys.stderr)
    sys.exit(1)

log_path = sys.argv[1]

with open(log_path, "a") as log:
    for line in sys.stdin:
        # Always log
        log.write(line)
        log.flush()

        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            continue

        # Only process stream events
        if event.get("type") != "stream_event":
            # Check for top-level result (final summary)
            if event.get("type") == "result":
                turns = event.get("num_turns", 0)
                dur = event.get("duration_ms", 0)
                if dur:
                    print(
                        f"  done ({turns} turns, {dur / 1000:.0f}s)",
                        file=sys.stderr,
                        flush=True,
                    )
            continue

        inner = event.get("event", {})
        etype = inner.get("type", "")

        if etype == "content_block_start":
            cb = inner.get("content_block", {})
            if cb.get("type") == "tool_use":
                name = cb.get("name", "?")
                print(f"  \u21b3 {name}", file=sys.stderr, flush=True)
