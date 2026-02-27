"""
Tool Activity Logger — records every tool call with full detail.

Stores an in-memory list + auto-saves to data/tool_log.json.
GUI can read entries in real-time and export the full log.
"""
import json
import os
import threading
import time

from config import DATA_DIR

LOG_PATH = os.path.join(DATA_DIR, "tool_log.json")
_lock = threading.Lock()


class ToolLogger:
    """Singleton-style tool activity logger."""

    _entries: list[dict] = []
    _on_entry_callback = None  # GUI sets this for real-time display
    _session_start: float = time.time()

    @classmethod
    def set_callback(cls, callback):
        """Register a callback(entry_dict) for real-time GUI updates."""
        cls._on_entry_callback = callback

    @classmethod
    def clear(cls):
        """Clear the in-memory log (start fresh for a new session)."""
        with _lock:
            cls._entries.clear()
            cls._session_start = time.time()

    @classmethod
    def log(cls, tool_name: str, args: dict, result: dict,
            agent_role: str = "", blocked: bool = False,
            block_reason: str = ""):
        """Log a single tool call."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed": round(time.time() - cls._session_start, 1),
            "agent": agent_role,
            "tool": tool_name,
            "args": _safe_truncate(args),
            "result": _safe_truncate(result),
            "success": result.get("success", False) if isinstance(result, dict) else False,
            "blocked": blocked,
            "block_reason": block_reason,
        }

        with _lock:
            cls._entries.append(entry)

        # Notify GUI
        if cls._on_entry_callback:
            try:
                cls._on_entry_callback(entry)
            except Exception:
                pass

    @classmethod
    def get_entries(cls) -> list[dict]:
        """Get a copy of all log entries."""
        with _lock:
            return list(cls._entries)

    @classmethod
    def entry_count(cls) -> int:
        with _lock:
            return len(cls._entries)

    @classmethod
    def save_to_file(cls, path: str | None = None):
        """Save the full log to a JSON file."""
        path = path or LOG_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            entries = list(cls._entries)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False, default=str)
        return path

    @classmethod
    def export_readable(cls, path: str) -> str:
        """Export the log as a human-readable text file."""
        with _lock:
            entries = list(cls._entries)

        lines = [
            f"GrokHive Tool Log — {len(entries)} entries",
            f"Session start: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cls._session_start))}",
            "=" * 70,
            "",
        ]
        for e in entries:
            status = "✅" if e["success"] else ("🚫 BLOCKED" if e["blocked"] else "❌")
            lines.append(f"[{e['timestamp']}] +{e['elapsed']}s  {status}")
            lines.append(f"  Agent: {e['agent'] or '(unknown)'}")
            lines.append(f"  Tool:  {e['tool']}")
            lines.append(f"  Args:  {json.dumps(e['args'], default=str)}")
            if e["blocked"]:
                lines.append(f"  Block: {e['block_reason']}")
            else:
                result_str = json.dumps(e["result"], default=str)
                if len(result_str) > 500:
                    result_str = result_str[:500] + "..."
                lines.append(f"  Result: {result_str}")
            lines.append("")

        text = "\n".join(lines)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    @classmethod
    def format_entry(cls, entry: dict) -> str:
        """Format a single entry for display."""
        status = "✅" if entry["success"] else (
            "🚫" if entry["blocked"] else "❌")
        agent = entry.get("agent", "")
        tool = entry.get("tool", "")
        args_str = json.dumps(entry.get("args", {}), default=str)
        if len(args_str) > 200:
            args_str = args_str[:200] + "..."

        line = f"[+{entry['elapsed']}s] {status} {agent} → {tool}({args_str})"

        if entry.get("blocked"):
            line += f"\n    🚫 {entry['block_reason']}"
        elif not entry.get("success"):
            err = entry.get("result", {})
            if isinstance(err, dict):
                err = err.get("error", str(err))
            line += f"\n    ❌ {str(err)[:200]}"

        return line


def _safe_truncate(obj, max_len=2000):
    """Truncate large values in dicts for log storage."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > max_len:
                out[k] = v[:max_len] + f"... ({len(v)} chars)"
            else:
                out[k] = v
        return out
    return obj
