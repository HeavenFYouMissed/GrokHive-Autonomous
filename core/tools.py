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
}


def execute_tool(name: str, args: dict) -> dict:
    """Execute a tool by name. Returns a JSON-serialisable dict."""
    func = _TOOL_MAP.get(name)
    if not func:
        return {"success": False, "error": f"Unknown tool: {name}"}
    try:
        result = func(args)
        # Ensure serialisable
        if isinstance(result, dict):
            result.pop("image", None)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}
