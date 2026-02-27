"""
MiniGrok Swarm — Main GUI Application.

Single-window layout:
  Sidebar (left):  API keys · Model/Tier/Safety config · Context files
  Main (right):    Agent status bar · Streaming output · Task input
"""
import ctypes
import os
import threading
import time
import tkinter.filedialog as tkfd
import customtkinter as ctk

from config import (
    APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, SIDEBAR_WIDTH,
    GROK_MODELS, DEFAULT_MODEL, AGENT_ROLES, SAFETY_LEVELS,
)
from gui.theme import COLORS, FONT_FAMILY, FONT_SIZES
from gui.widgets import ActionButton, Tooltip, ConfirmDialog
from core.settings import load_settings, save_settings
from core.swarm import MiniGrokSwarm, list_grok_models, test_connection
from core.tools import set_confirm_callback, SwarmTools


# ── Windows 11 Mica titlebar ────────────────────────────────

def _apply_mica(window):
    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20,
            ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int),
        )
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 1029,
            ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int),
        )
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SwarmApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # ─── Window ─────────────────────────────────────────
        self.title(APP_NAME)
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(960, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color=COLORS["bg_dark"])
        self.after(100, lambda: _apply_mica(self))

        # ─── State ──────────────────────────────────────────
        self._settings = load_settings()
        self._running = False
        self._swarm: MiniGrokSwarm | None = None
        self._context_files: list[tuple[str, str]] = []  # (path, content)
        self._agent_dots: dict[str, ctk.CTkLabel] = {}
        self._first_verifier_token = True

        # ─── Layout ─────────────────────────────────────────
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()

        # ─── Tool confirmation system ───────────────────────
        set_confirm_callback(self._confirm_tool_action)

        # ─── Populate UI from saved settings ────────────────
        self._load_settings_to_ui()
        self.after(400, self._check_connection)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SIDEBAR
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(
            self, width=SIDEBAR_WIDTH, fg_color=COLORS["bg_sidebar"],
            corner_radius=0,
        )
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        # Title
        title_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        title_frame.pack(fill="x", padx=15, pady=(20, 5))

        ctk.CTkLabel(
            title_frame, text="🤖 MiniGrok",
            font=(FONT_FAMILY, 22, "bold"),
            text_color=COLORS["accent"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame, text="Agent Swarm",
            font=(FONT_FAMILY, 14),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w")

        # Dividers
        ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["accent_dim"]
                      ).pack(fill="x", padx=15, pady=(15, 4))
        ctk.CTkFrame(sidebar, height=1, fg_color=COLORS["divider"]
                      ).pack(fill="x", padx=20, pady=(0, 10))

        sb_scroll = ctk.CTkScrollableFrame(
            sidebar, fg_color="transparent",
        )
        sb_scroll.pack(fill="both", expand=True, padx=5, pady=0)

        # ── 🔑 API Keys ────────────────────────────────────
        self._section_label(sb_scroll, "🔑  API KEYS")

        ctk.CTkLabel(
            sb_scroll, text="Key 1 (required):",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", padx=10, pady=(2, 0))

        self.key1_entry = ctk.CTkEntry(
            sb_scroll, show="●",
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=8, height=32,
        )
        self.key1_entry.pack(fill="x", padx=10, pady=(2, 4))

        ctk.CTkLabel(
            sb_scroll, text="Key 2 (optional, for rate-limit split):",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", padx=10, pady=(2, 0))

        self.key2_entry = ctk.CTkEntry(
            sb_scroll, show="●",
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=8, height=32,
        )
        self.key2_entry.pack(fill="x", padx=10, pady=(2, 4))

        key_btn_row = ctk.CTkFrame(sb_scroll, fg_color="transparent")
        key_btn_row.pack(fill="x", padx=10, pady=(2, 8))

        ActionButton(
            key_btn_row, text="💾 Save Keys",
            command=self._save_keys, style="primary", width=110,
        ).pack(side="left", padx=(0, 5))

        self._key_toggle_btn = ActionButton(
            key_btn_row, text="👁", command=self._toggle_key_vis,
            style="secondary", width=35,
        )
        self._key_toggle_btn.pack(side="left", padx=(0, 5))
        Tooltip(self._key_toggle_btn, "Show / hide API keys")

        ActionButton(
            key_btn_row, text="🔌 Test",
            command=self._check_connection, style="secondary", width=70,
        ).pack(side="left")

        self._keys_visible = False

        # ── ⚙️ Configuration ───────────────────────────────
        self._section_label(sb_scroll, "⚙️  CONFIGURATION")

        # Model
        ctk.CTkLabel(
            sb_scroll, text="Model:",
            font=(FONT_FAMILY, FONT_SIZES["small"], "bold"),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", padx=10, pady=(2, 0))

        self.model_menu = ctk.CTkOptionMenu(
            sb_scroll, values=GROK_MODELS,
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=240, height=30,
        )
        self.model_menu.pack(padx=10, pady=(2, 6), anchor="w")
        Tooltip(self.model_menu,
                "Grok model to use for all agents.\n"
                "grok-3 = most capable (slower)\n"
                "grok-3-fast = balanced\n"
                "grok-3-mini = cheapest & fastest")

        # Tier
        ctk.CTkLabel(
            sb_scroll, text="Agent Tier:",
            font=(FONT_FAMILY, FONT_SIZES["small"], "bold"),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", padx=10, pady=(2, 0))

        self.tier_menu = ctk.CTkOptionMenu(
            sb_scroll,
            values=["minimum (2 agents)", "medium (4 agents)", "full (8 agents)"],
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=240, height=30,
            command=self._on_tier_change,
        )
        self.tier_menu.pack(padx=10, pady=(2, 6), anchor="w")
        Tooltip(self.tier_menu,
                "How many specialist agents to deploy.\n"
                "• Minimum: Researcher + Planner\n"
                "• Medium: + Coder + Tester\n"
                "• Full: + Optimizer + Security + Integrator + QA")

        # Safety
        ctk.CTkLabel(
            sb_scroll, text="Safety Level:",
            font=(FONT_FAMILY, FONT_SIZES["small"], "bold"),
            text_color=COLORS["text_secondary"],
        ).pack(anchor="w", padx=10, pady=(2, 0))

        self.safety_menu = ctk.CTkOptionMenu(
            sb_scroll,
            values=list(SAFETY_LEVELS.values()),
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=240, height=30,
            command=self._on_safety_change,
        )
        self.safety_menu.pack(padx=10, pady=(2, 8), anchor="w")
        Tooltip(self.safety_menu,
                "Controls what PC tools agents can use.\n"
                "• Read-Only: screenshots, OCR, file reading only\n"
                "• Confirmed: asks YOU before any write/execute\n"
                "• Full Auto: no confirmation (dangerous!)")

        # ── 📎 Context Files ───────────────────────────────
        self._section_label(sb_scroll, "📎  CONTEXT FILES")

        ctx_btn_row = ctk.CTkFrame(sb_scroll, fg_color="transparent")
        ctx_btn_row.pack(fill="x", padx=10, pady=(2, 4))

        ActionButton(
            ctx_btn_row, text="+ Add Files",
            command=self._add_context_files, style="secondary", width=110,
        ).pack(side="left", padx=(0, 5))

        ActionButton(
            ctx_btn_row, text="🗑 Clear",
            command=self._clear_context, style="danger", width=80,
        ).pack(side="left")

        self.ctx_list_frame = ctk.CTkScrollableFrame(
            sb_scroll, fg_color="transparent", height=100,
        )
        self.ctx_list_frame.pack(fill="x", padx=10, pady=(0, 8))

        self.ctx_count_label = ctk.CTkLabel(
            sb_scroll, text="No files attached",
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        )
        self.ctx_count_label.pack(anchor="w", padx=10, pady=(0, 8))

        # ── 📊 Connection Status ───────────────────────────
        self._section_label(sb_scroll, "📊  STATUS")

        self.conn_label = ctk.CTkLabel(
            sb_scroll, text="Not connected",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        self.conn_label.pack(anchor="w", padx=10, pady=(2, 10))

        # Sidebar glow line
        ctk.CTkFrame(
            self, width=1, fg_color=COLORS["accent_dim"], corner_radius=0,
        ).grid(row=0, column=0, sticky="nse")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # MAIN AREA
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)  # output expands

        # ── Agent status bar ────────────────────────────────
        status_bar = ctk.CTkFrame(
            main, fg_color=COLORS["bg_card"], corner_radius=10, height=50,
        )
        status_bar.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 5))

        self.agent_bar = ctk.CTkFrame(status_bar, fg_color="transparent")
        self.agent_bar.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(
            self.agent_bar, text="Agents:",
            font=(FONT_FAMILY, FONT_SIZES["small"], "bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 8))

        # Agent dots get built dynamically by _rebuild_agent_dots()
        self._rebuild_agent_dots()

        # ── Output panel ────────────────────────────────────
        self.output = ctk.CTkTextbox(
            main, font=("Consolas", FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=10, wrap="word",
        )
        self.output.grid(row=1, column=0, sticky="nsew", padx=15, pady=5)
        self.output.configure(state="disabled")

        # Configure text tags for coloured output
        try:
            tb = self.output._textbox
            tb.tag_configure("agent_header",
                             foreground=COLORS["accent_blue"],
                             font=("Consolas", FONT_SIZES["body"], "bold"))
            tb.tag_configure("verifier_header",
                             foreground=COLORS["accent_green"],
                             font=("Consolas", FONT_SIZES["body"], "bold"))
            tb.tag_configure("verifier_text",
                             foreground=COLORS["accent_green"])
            tb.tag_configure("error",
                             foreground=COLORS["error"])
            tb.tag_configure("system",
                             foreground=COLORS["text_muted"])
            tb.tag_configure("tool",
                             foreground=COLORS["accent_yellow"])
        except Exception:
            pass

        # Welcome message
        self._append_output(
            "🤖 MiniGrok Swarm — Ready\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1. Paste your Grok API key in the sidebar and click Save\n"
            "2. Choose model, tier, and safety level\n"
            "3. (Optional) Attach context files\n"
            "4. Type your task below and hit Run Swarm!\n\n"
            "Agents run in TRUE parallel — all working simultaneously.\n"
            "A Verifier agent synthesises the final answer.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
            tag="system",
        )

        # ── Input bar ───────────────────────────────────────
        input_frame = ctk.CTkFrame(
            main, fg_color=COLORS["bg_card"], corner_radius=10,
        )
        input_frame.grid(row=2, column=0, sticky="ew", padx=15, pady=(5, 12))

        input_inner = ctk.CTkFrame(input_frame, fg_color="transparent")
        input_inner.pack(fill="x", padx=12, pady=10)

        self.task_input = ctk.CTkTextbox(
            input_inner, height=60,
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=8, wrap="word",
        )
        self.task_input.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.task_input.bind("<Return>", self._on_enter)
        self.task_input.bind("<Shift-Return>", lambda e: None)

        btn_col = ctk.CTkFrame(input_inner, fg_color="transparent")
        btn_col.pack(side="right")

        self.btn_run = ActionButton(
            btn_col, text="🚀 Run Swarm",
            command=self._run_swarm, style="success", width=130,
        )
        self.btn_run.pack(pady=(0, 4))
        Tooltip(self.btn_run, "Launch all agents in parallel on your task")

        self.btn_stop = ActionButton(
            btn_col, text="⏹ Stop",
            command=self._stop_swarm, style="danger", width=130,
        )
        self.btn_stop.pack()
        self.btn_stop.configure(state="disabled")

        # Counter
        self.counter_label = ctk.CTkLabel(
            input_frame, text="",
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        )
        self.counter_label.pack(padx=12, pady=(0, 6), anchor="w")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # HELPERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _section_label(self, parent, text):
        """Small uppercase section header for the sidebar."""
        ctk.CTkLabel(
            parent, text=f"  {text}",
            font=(FONT_FAMILY, FONT_SIZES["tiny"], "bold"),
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", padx=5, pady=(12, 3))

    def _get_tier_key(self) -> str:
        """Extract tier key from the dropdown text."""
        val = self.tier_menu.get()
        if val.startswith("minimum"):
            return "minimum"
        elif val.startswith("full"):
            return "full"
        return "medium"

    def _get_safety_key(self) -> str:
        """Extract safety key from the dropdown text."""
        val = self.safety_menu.get()
        if "Read-Only" in val:
            return "read_only"
        elif "Full Auto" in val:
            return "full_auto"
        return "confirmed"

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # API KEYS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _save_keys(self):
        self._settings["grok_api_key_1"] = self.key1_entry.get().strip()
        self._settings["grok_api_key_2"] = self.key2_entry.get().strip()
        save_settings(self._settings)
        self.conn_label.configure(
            text="Keys saved ✓", text_color=COLORS["accent_green"],
        )
        self.after(500, self._check_connection)

    def _toggle_key_vis(self):
        self._keys_visible = not self._keys_visible
        show = "" if self._keys_visible else "●"
        self.key1_entry.configure(show=show)
        self.key2_entry.configure(show=show)
        self._key_toggle_btn.configure(
            text="🙈" if self._keys_visible else "👁",
        )

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # CONNECTION
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _check_connection(self):
        key = self.key1_entry.get().strip()
        if not key:
            self.conn_label.configure(
                text="No API key", text_color=COLORS["text_muted"],
            )
            return

        self.conn_label.configure(
            text="Testing connection...", text_color=COLORS["text_muted"],
        )

        def _bg():
            ok, msg = test_connection(key)
            models = list_grok_models(key) if ok else []

            def _done():
                if ok:
                    self.conn_label.configure(
                        text=f"✅ Connected — {msg}",
                        text_color=COLORS["accent_green"],
                    )
                    if models:
                        self.model_menu.configure(values=models)
                        pref = self._settings.get("model", DEFAULT_MODEL)
                        if pref in models:
                            self.model_menu.set(pref)
                        elif models:
                            self.model_menu.set(models[0])
                else:
                    self.conn_label.configure(
                        text=f"❌ {msg}", text_color=COLORS["error"],
                    )
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TIER / SAFETY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_tier_change(self, _value=None):
        self._rebuild_agent_dots()
        self._save_config()

    def _on_safety_change(self, _value=None):
        key = self._get_safety_key()
        SwarmTools.safety_level = key
        self._save_config()

    def _save_config(self):
        self._settings["model"] = self.model_menu.get()
        self._settings["tier"] = self._get_tier_key()
        self._settings["safety_level"] = self._get_safety_key()
        save_settings(self._settings)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # AGENT STATUS DOTS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _rebuild_agent_dots(self):
        """Recreate agent status indicators for the current tier."""
        # Clear existing dots
        for w in list(self.agent_bar.winfo_children()):
            if isinstance(w, ctk.CTkLabel) and w.cget("text") != "Agents:":
                w.destroy()
        self._agent_dots.clear()

        tier = self._get_tier_key()
        roles = AGENT_ROLES.get(tier, AGENT_ROLES["medium"])

        for role_name, _ in roles:
            dot = ctk.CTkLabel(
                self.agent_bar,
                text=f"● {role_name}",
                font=(FONT_FAMILY, FONT_SIZES["small"]),
                text_color=COLORS["text_muted"],
            )
            dot.pack(side="left", padx=(0, 10))
            self._agent_dots[role_name] = dot

        # Verifier (always present)
        vdot = ctk.CTkLabel(
            self.agent_bar,
            text="● ✅ Verifier",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        vdot.pack(side="left", padx=(0, 10))
        self._agent_dots["✅ Verifier"] = vdot

    def _update_agent_dot(self, role, status):
        """Update an agent's dot colour based on status."""
        def _ui():
            dot = self._agent_dots.get(role)
            if not dot:
                return
            if "Working" in status or "⏳" in status:
                dot.configure(text_color=COLORS["accent_yellow"])
            elif "Done" in status or "✅" in status:
                dot.configure(text_color=COLORS["accent_green"])
            elif "ERROR" in status:
                dot.configure(text_color=COLORS["error"])
            elif "🔧" in status:
                dot.configure(text_color=COLORS["accent_orange"])
            else:
                dot.configure(text_color=COLORS["text_muted"])
        self.after(0, _ui)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # CONTEXT FILES
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _add_context_files(self):
        paths = tkfd.askopenfilenames(
            title="Select context files",
            filetypes=[
                ("All files", "*.*"),
                ("Text", "*.txt *.md *.py *.js *.ts *.json *.xml *.csv"),
                ("Code", "*.py *.js *.ts *.c *.cpp *.h *.java *.rs"),
            ],
        )
        for path in paths:
            if any(p == path for p, _ in self._context_files):
                continue  # skip duplicates
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()[:30000]   # cap per file
                self._context_files.append((path, content))
            except Exception:
                continue

        self._refresh_context_list()

    def _clear_context(self):
        self._context_files.clear()
        self._refresh_context_list()

    def _refresh_context_list(self):
        for w in self.ctx_list_frame.winfo_children():
            w.destroy()

        for path, content in self._context_files:
            name = os.path.basename(path)
            wc = len(content.split())
            row = ctk.CTkFrame(self.ctx_list_frame, fg_color=COLORS["bg_card"],
                               corner_radius=6)
            row.pack(fill="x", pady=1)

            ctk.CTkLabel(
                row, text=f"📄 {name[:30]}  ({wc:,}w)",
                font=(FONT_FAMILY, FONT_SIZES["small"]),
                text_color=COLORS["text_primary"], anchor="w",
            ).pack(fill="x", padx=6, pady=3)

        total = len(self._context_files)
        tw = sum(len(c.split()) for _, c in self._context_files)
        self.ctx_count_label.configure(
            text=f"{total} file{'s' if total != 1 else ''}  •  "
                 f"{tw:,} words" if total else "No files attached",
        )

    def _build_context_string(self) -> str:
        """Concatenate all context files into one string for agents."""
        if not self._context_files:
            return ""
        parts = []
        for i, (path, content) in enumerate(self._context_files, 1):
            name = os.path.basename(path)
            parts.append(f"──── File {i}: {name} ────\n{content}")
        return "\n\n".join(parts)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SWARM EXECUTION
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_enter(self, event):
        self._run_swarm()
        return "break"

    def _run_swarm(self):
        if self._running:
            return

        task = self.task_input.get("1.0", "end-1c").strip()
        if not task:
            return

        key1 = self.key1_entry.get().strip()
        if not key1:
            self._append_output(
                "\n⚠️  No API key! Paste your Grok key in the sidebar.\n",
                tag="error",
            )
            return

        # Clear + show task
        self.task_input.delete("1.0", "end")
        self._append_output(f"\n{'━' * 50}\n", tag="system")
        self._append_output(f"📝 TASK: {task}\n", tag="system")
        tier_key = self._get_tier_key()
        n_agents = len(AGENT_ROLES.get(tier_key, []))
        self._append_output(
            f"⚙️  Model: {self.model_menu.get()}  •  "
            f"Tier: {tier_key} ({n_agents} agents)  •  "
            f"Safety: {self._get_safety_key()}\n",
            tag="system",
        )
        self._append_output(f"{'━' * 50}\n\n", tag="system")

        # Reset dots
        for dot in self._agent_dots.values():
            dot.configure(text_color=COLORS["text_muted"])

        # Update safety level on tools
        SwarmTools.safety_level = self._get_safety_key()

        # Build swarm
        self._running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._first_verifier_token = True

        key2 = self.key2_entry.get().strip()
        context = self._build_context_string()

        self._swarm = MiniGrokSwarm(
            api_key_1=key1,
            api_key_2=key2,
            model=self.model_menu.get(),
            tier=tier_key,
        )

        swarm = self._swarm

        def _bg():
            result = swarm.run(
                task=task,
                context=context,
                on_agent_status=self._on_agent_status,
                on_agent_done=self._on_agent_done,
                on_verifier_token=self._on_verifier_token,
            )

            def _done():
                self._running = False
                self.btn_run.configure(state="normal")
                self.btn_stop.configure(state="disabled")
                self._swarm = None

                elapsed = result.get("elapsed", 0)
                n = len(result.get("agent_outputs", {}))

                if result["success"]:
                    self._append_output(
                        f"\n\n{'━' * 50}\n"
                        f"✅ DONE — {n} agents • {elapsed:.1f}s\n"
                        f"{'━' * 50}\n",
                        tag="system",
                    )
                    self.counter_label.configure(
                        text=f"{n} agents  •  {elapsed:.1f}s  •  "
                             f"{len(result.get('final_output', '').split())} words",
                    )
                else:
                    self._append_output(
                        f"\n\n❌ ERROR: {result.get('error', 'Unknown')}\n",
                        tag="error",
                    )
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _stop_swarm(self):
        if self._swarm:
            self._swarm.cancel()
            self._append_output("\n⏹ Stopping swarm...\n", tag="system")

    # ── Swarm callbacks (called from background threads) ────

    def _on_agent_status(self, role, status):
        self._update_agent_dot(role, status)
        if "🔧" in status:
            # Tool usage
            self.after(0, lambda: self._append_output(
                f"  {role} → {status}\n", tag="tool",
            ))

    def _on_agent_done(self, role, output):
        def _ui():
            self._append_output(f"\n──── {role} ────\n", tag="agent_header")
            self._append_output(f"{output}\n")
        self.after(0, _ui)

    def _on_verifier_token(self, token):
        def _ui():
            if self._first_verifier_token:
                self._first_verifier_token = False
                self._append_output(
                    "\n──── ✅ Verifier (Final Output) ────\n",
                    tag="verifier_header",
                )
            self._append_output(token, tag="verifier_text")
        self.after(0, _ui)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # TOOL CONFIRMATION (thread-safe)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _confirm_tool_action(self, action: str) -> bool:
        """Show a confirmation dialog from a background tool thread.

        Uses threading.Event to block the tool thread while the user
        decides in the GUI. The main thread stays responsive.
        """
        result = [False]
        event = threading.Event()

        def _show():
            dialog = ConfirmDialog(self, action)
            self.wait_window(dialog)
            result[0] = dialog.confirmed
            event.set()

        self.after(0, _show)
        event.wait(timeout=120)
        return result[0]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # OUTPUT DISPLAY
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _append_output(self, text, tag=None):
        """Append text to the output panel (optionally with a tag)."""
        self.output.configure(state="normal")
        if tag:
            # Insert with tag
            start = self.output.index("end-1c")
            self.output.insert("end", text)
            end = self.output.index("end-1c")
            try:
                self.output._textbox.tag_add(tag, start, end)
            except Exception:
                pass
        else:
            self.output.insert("end", text)
        self.output.configure(state="disabled")
        self.output.see("end")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SETTINGS PERSISTENCE
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _load_settings_to_ui(self):
        """Populate all UI widgets from saved settings."""
        s = self._settings

        # Keys
        self.key1_entry.delete(0, "end")
        self.key1_entry.insert(0, s.get("grok_api_key_1", ""))
        self.key2_entry.delete(0, "end")
        self.key2_entry.insert(0, s.get("grok_api_key_2", ""))

        # Model
        model = s.get("model", DEFAULT_MODEL)
        if model in GROK_MODELS:
            self.model_menu.set(model)

        # Tier
        tier = s.get("tier", "medium")
        tier_map = {
            "minimum": "minimum (2 agents)",
            "medium": "medium (4 agents)",
            "full": "full (8 agents)",
        }
        self.tier_menu.set(tier_map.get(tier, tier_map["medium"]))
        self._rebuild_agent_dots()

        # Safety
        safety = s.get("safety_level", "confirmed")
        safety_labels = {
            "read_only": SAFETY_LEVELS["read_only"],
            "confirmed": SAFETY_LEVELS["confirmed"],
            "full_auto": SAFETY_LEVELS["full_auto"],
        }
        self.safety_menu.set(safety_labels.get(safety, safety_labels["confirmed"]))
        SwarmTools.safety_level = safety
