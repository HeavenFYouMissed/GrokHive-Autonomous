"""
PC Automation Tools — Safe tools for Grok swarm agents.

Safety tiers:
  • read_only  — screenshots, OCR, file reading, directory listing
  • confirmed  — write/execute tools ask the user via GUI dialog first
  • full_auto  — no confirmation (dangerous!)

The GUI registers a confirmation callback via set_confirm_callback().
Tool threads block on a threading.Event until the user responds.
"""
import os
import re
import subprocess
import json
import threading

# Optional heavy deps — tools degrade gracefully if missing
try:
    import pyautogui
    pyautogui.FAILSAFE = True          # mouse to top-left = emergency stop
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

try:
    import pytesseract
    from PIL import ImageGrab
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


# ── Safety constants ────────────────────────────────────────
READ_ONLY = "read_only"
CONFIRMED = "confirmed"
FULL_AUTO = "full_auto"


# ── Confirmation system (set by GUI) ───────────────────────
_confirm_callback = None          # GUI sets this → callable(action_str) -> bool
_confirm_lock = threading.Lock()  # serialise confirmation dialogs


def set_confirm_callback(callback):
    """Register the GUI's confirmation callback. Must be thread-safe."""
    global _confirm_callback
    _confirm_callback = callback


def _request_confirmation(action: str) -> bool:
    """Ask the user for permission before a dangerous tool runs."""
    with _confirm_lock:
        if _confirm_callback:
            return _confirm_callback(action)
    return False


# ── PowerShell Blocklist (NEVER allow these) ───────────────

_PS_BLOCKLIST = [
    ("uninstall",               "Cannot uninstall software"),
    ("remove-appxpackage",      "Cannot remove Windows apps"),
    ("remove-windowsfeature",   "Cannot remove Windows features"),
    ("remove-windowsoptionalfeature", "Cannot remove Windows features"),
    ("format-volume",           "Cannot format drives"),
    ("format c:",               "Cannot format drives"),
    ("format d:",               "Cannot format drives"),
    ("stop-computer",           "Cannot shut down computer"),
    ("restart-computer",        "Cannot restart computer"),
    ("shutdown",                "Cannot shut down computer"),
    ("clear-recyclebin",        "Cannot clear recycle bin"),
    ("bcdedit",                 "Cannot modify boot configuration"),
    ("diskpart",                "Cannot modify disk partitions"),
    ("reg delete",              "Cannot delete registry keys"),
    ("set-executionpolicy unrestricted", "Cannot change execution policy"),
    ("remove-item c:\\windows",  "Cannot delete Windows system files"),
    ("remove-item c:\\program",  "Cannot delete Program Files"),
    ("remove-item -recurse c:\\","Cannot recursively delete C: drive"),
    ("del /s c:\\windows",       "Cannot delete Windows system files"),
    ("rmdir /s c:\\windows",     "Cannot delete Windows system folders"),
    ("system32",                "Cannot touch System32"),
    ("new-service",             "Cannot create Windows services"),
    ("remove-service",          "Cannot remove Windows services"),
]


def _check_powershell_blocklist(cmd: str) -> str | None:
    """Return block reason if cmd matches blocklist, else None."""
    cmd_lower = cmd.lower().replace("/", "\\").strip()
    for pattern, reason in _PS_BLOCKLIST:
        if pattern in cmd_lower:
            return reason
    return None


# ── Tool implementations ───────────────────────────────────

class SwarmTools:
    """Stateless tool functions with safety-level checks."""

    safety_level = CONFIRMED  # default; GUI updates this

    # ─── Read-only tools (always allowed) ───────────────────

    @staticmethod
    def take_screenshot(region=None):
        """Capture the screen (or a region)."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        try:
            img = pyautogui.screenshot(region=region)
            # Return confirmation (image not serialisable)
            w, h = img.size
            return {"success": True, "message": f"Screenshot captured ({w}x{h})"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def ocr_screenshot(region=None):
        """Screenshot → OCR → text."""
        if not HAS_OCR:
            return {"success": False, "error": "pytesseract/Pillow not installed"}
        try:
            img = ImageGrab.grab(bbox=region)
            text = pytesseract.image_to_string(img).strip()
            return {"success": True, "text": text[:15000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def read_file(path):
        """Read a file (text, read-only)."""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {"success": True, "content": content[:50000],
                    "length": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def list_directory(path="."):
        """List directory contents."""
        try:
            items = os.listdir(path)
            dirs = sorted(d + "/" for d in items
                          if os.path.isdir(os.path.join(path, d)))
            files = sorted(f for f in items
                           if os.path.isfile(os.path.join(path, f)))
            return {"success": True, "directories": dirs, "files": files}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_clipboard():
        """Get current clipboard text."""
        try:
            import tkinter as _tk
            root = _tk.Tk()
            root.withdraw()
            text = root.clipboard_get()
            root.destroy()
            return {"success": True, "text": text[:10000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─── Write / Execute tools (need confirmation) ──────────

    @staticmethod
    def run_powershell(cmd):
        """Execute a PowerShell command."""
        # ── Hard blocklist — NEVER allow these regardless of safety level ──
        block_reason = _check_powershell_blocklist(cmd)
        if block_reason:
            return {"success": False, "error": f"BLOCKED: {block_reason}",
                    "blocked": True, "block_reason": block_reason}
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        if SwarmTools.safety_level == CONFIRMED:
            if not _request_confirmation(f"Run PowerShell command:\n\n{cmd}"):
                return {"success": False, "error": "Denied by user"}
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True, text=True, timeout=30,
            )
            return {
                "success": True,
                "stdout": result.stdout[:10000],
                "stderr": result.stderr[:5000],
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timed out (30 s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def write_file(path, content):
        """Write text to a file."""
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        if SwarmTools.safety_level == CONFIRMED:
            preview = content[:300] + ("..." if len(content) > 300 else "")
            if not _request_confirmation(
                    f"Write file:\n{path}\n\nPreview:\n{preview}"):
                return {"success": False, "error": "Denied by user"}
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True,
                    "message": f"Wrote {len(content):,} chars → {path}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def type_text(text):
        """Simulate keyboard typing into the focused window."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        if SwarmTools.safety_level == CONFIRMED:
            if not _request_confirmation(
                    f"Type text into focused window:\n\n{text[:300]}"):
                return {"success": False, "error": "Denied by user"}
        try:
            pyautogui.typewrite(text, interval=0.02)
            return {"success": True, "message": f"Typed {len(text)} chars"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def open_in_vscode(path):
        """Open a file or folder in VS Code."""
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        if SwarmTools.safety_level == CONFIRMED:
            if not _request_confirmation(f"Open in VS Code:\n{path}"):
                return {"success": False, "error": "Denied by user"}
        try:
            subprocess.Popen(["code", path], shell=True)
            return {"success": True, "message": f"Opened {path} in VS Code"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def press_keys(keys):
        """Press a keyboard shortcut (comma-separated, e.g. 'ctrl,s')."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        key_list = [k.strip() for k in keys.split(",")]
        if SwarmTools.safety_level == CONFIRMED:
            if not _request_confirmation(
                    f"Press keys: {'+'.join(key_list)}"):
                return {"success": False, "error": "Denied by user"}
        try:
            pyautogui.hotkey(*key_list)
            return {"success": True, "message": f"Pressed {'+'.join(key_list)}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def click(x, y, button="left"):
        """Click at screen coordinates."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        if SwarmTools.safety_level == CONFIRMED:
            if not _request_confirmation(
                    f"Mouse click at ({x}, {y}) [{button}]"):
                return {"success": False, "error": "Denied by user"}
        try:
            pyautogui.click(int(x), int(y), button=button)
            return {"success": True, "message": f"Clicked ({x}, {y})"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ——— Browser / Navigation tools ———————————————————————

    @staticmethod
    def open_url(url):
        """Open a URL in Microsoft Edge (the user's default browser)."""
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        if SwarmTools.safety_level == CONFIRMED:
            if not _request_confirmation(f"Open URL in Edge:\n{url}"):
                return {"success": False, "error": "Denied by user"}
        try:
            subprocess.Popen(["start", "msedge", url], shell=True)
            return {"success": True, "message": f"Opened {url} in Edge"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def scroll(direction="down", amount=5):
        """Scroll the mouse wheel up or down."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        try:
            clicks = int(amount)
            if direction == "up":
                clicks = abs(clicks)
            else:
                clicks = -abs(clicks)
            pyautogui.scroll(clicks)
            return {"success": True, "message": f"Scrolled {direction} {abs(clicks)} clicks"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def wait(seconds=2):
        """Wait/pause for a number of seconds (e.g. for page loads)."""
        import time
        secs = min(float(seconds), 30)  # cap at 30s
        time.sleep(secs)
        return {"success": True, "message": f"Waited {secs:.1f}s"}

    @staticmethod
    def mouse_move(x, y):
        """Move the mouse to specific screen coordinates (without clicking)."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        try:
            pyautogui.moveTo(int(x), int(y), duration=0.3)
            return {"success": True, "message": f"Moved mouse to ({x}, {y})"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def screenshot_region(x, y, width, height):
        """Screenshot a specific region of the screen and OCR it."""
        if not HAS_OCR:
            return {"success": False, "error": "pytesseract/Pillow not installed"}
        try:
            bbox = (int(x), int(y), int(x) + int(width), int(y) + int(height))
            img = ImageGrab.grab(bbox=bbox)
            text = pytesseract.image_to_string(img).strip()
            return {"success": True, "text": text[:15000],
                    "region": f"{x},{y} {width}x{height}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def close_browser_tab():
        """Close the current browser tab (Ctrl+W)."""
        if not HAS_PYAUTOGUI:
            return {"success": False, "error": "pyautogui not installed"}
        if SwarmTools.safety_level == READ_ONLY:
            return {"success": False, "error": "Blocked — safety is Read-Only"}
        try:
            pyautogui.hotkey('ctrl', 'w')
            import time
            time.sleep(0.3)
            return {"success": True, "message": "Closed current browser tab"}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ── Tool schemas for Grok function calling (OpenAI format) ─

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Take a screenshot of the entire screen.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ocr_screenshot",
            "description": "Screenshot the screen and extract all visible text via OCR.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the text contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Absolute or relative file path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and sub-directories in a folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Directory path (default '.')"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_clipboard",
            "description": "Get the current clipboard text.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_powershell",
            "description": "Execute a PowerShell command and return stdout/stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string",
                            "description": "PowerShell command to run"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write text content to a file (creates dirs if needed).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path":    {"type": "string",
                                "description": "File path to write to"},
                    "content": {"type": "string",
                                "description": "Text content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": "Simulate keyboard typing into the currently focused window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string",
                             "description": "Text to type"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_in_vscode",
            "description": "Open a file or folder in Visual Studio Code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "File or folder path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_keys",
            "description": "Press a keyboard shortcut (e.g. 'ctrl,s' or 'alt,tab').",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "string",
                             "description": "Comma-separated key names"},
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Click at specific screen coordinates.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x":      {"type": "integer", "description": "X coordinate"},
                    "y":      {"type": "integer", "description": "Y coordinate"},
                    "button": {"type": "string",
                               "description": "Mouse button: left, right, middle",
                               "default": "left"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open a URL in Microsoft Edge browser. Use this to navigate to websites, Google searches, documentation, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string",
                            "description": "Full URL to open (e.g. https://google.com or https://www.google.com/search?q=query)"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Scroll the mouse wheel up or down on the current window. Use to scroll through web pages, documents, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string",
                                  "description": "Scroll direction: 'up' or 'down'",
                                  "default": "down"},
                    "amount":    {"type": "integer",
                                  "description": "Number of scroll clicks (1-20)",
                                  "default": 5},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait",
            "description": "Pause/wait for a number of seconds. Use after opening URLs or clicking to let pages load.",
            "parameters": {
                "type": "object",
                "properties": {
                    "seconds": {"type": "number",
                                "description": "Seconds to wait (max 30)",
                                "default": 2},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mouse_move",
            "description": "Move the mouse cursor to specific screen coordinates without clicking. Use to hover over elements.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X coordinate"},
                    "y": {"type": "integer", "description": "Y coordinate"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_region",
            "description": "Take a screenshot of a specific rectangular region on screen and OCR it to extract text. Useful for reading specific parts of a webpage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x":      {"type": "integer", "description": "Top-left X coordinate"},
                    "y":      {"type": "integer", "description": "Top-left Y coordinate"},
                    "width":  {"type": "integer", "description": "Width in pixels"},
                    "height": {"type": "integer", "description": "Height in pixels"},
                },
                "required": ["x", "y", "width", "height"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "close_browser_tab",
            "description": "Close the current browser tab (Ctrl+W). Use after finishing with a webpage to keep things tidy.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


# ── Tool dispatcher ─────────────────────────────────────────

_TOOL_MAP = {
    "take_screenshot": lambda a: SwarmTools.take_screenshot(),
    "ocr_screenshot":  lambda a: SwarmTools.ocr_screenshot(),
    "read_file":       lambda a: SwarmTools.read_file(a.get("path", "")),
    "list_directory":  lambda a: SwarmTools.list_directory(a.get("path", ".")),
    "get_clipboard":   lambda a: SwarmTools.get_clipboard(),
    "run_powershell":  lambda a: SwarmTools.run_powershell(a.get("cmd", "")),
    "write_file":      lambda a: SwarmTools.write_file(
                            a.get("path", ""), a.get("content", "")),
    "type_text":       lambda a: SwarmTools.type_text(a.get("text", "")),
    "open_in_vscode":  lambda a: SwarmTools.open_in_vscode(a.get("path", "")),
    "press_keys":      lambda a: SwarmTools.press_keys(a.get("keys", "")),
    "click":           lambda a: SwarmTools.click(
                            a.get("x", 0), a.get("y", 0),
                            a.get("button", "left")),
    "open_url":        lambda a: SwarmTools.open_url(a.get("url", "")),
    "scroll":          lambda a: SwarmTools.scroll(
                            a.get("direction", "down"),
                            a.get("amount", 5)),
    "wait":            lambda a: SwarmTools.wait(a.get("seconds", 2)),
    "mouse_move":      lambda a: SwarmTools.mouse_move(
                            a.get("x", 0), a.get("y", 0)),
    "screenshot_region": lambda a: SwarmTools.screenshot_region(
                            a.get("x", 0), a.get("y", 0),
                            a.get("width", 800), a.get("height", 600)),
    "close_browser_tab": lambda a: SwarmTools.close_browser_tab(),
}


def execute_tool(name: str, args: dict, agent_role: str = "") -> dict:
    """Execute a tool by name. Returns a JSON-serialisable dict."""
    from core.logger import ToolLogger

    func = _TOOL_MAP.get(name)
    if not func:
        result = {"success": False, "error": f"Unknown tool: {name}"}
        ToolLogger.log(name, args, result, agent_role=agent_role)
        return result
    try:
        result = func(args)
        # Ensure serialisable
        if isinstance(result, dict):
            result.pop("image", None)
        blocked = result.get("blocked", False) if isinstance(result, dict) else False
        block_reason = result.get("block_reason", "") if isinstance(result, dict) else ""
        ToolLogger.log(name, args, result, agent_role=agent_role,
                       blocked=blocked, block_reason=block_reason)
        return result
    except Exception as e:
        result = {"success": False, "error": str(e)}
        ToolLogger.log(name, args, result, agent_role=agent_role)
        return result
