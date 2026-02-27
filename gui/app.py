"""
MiniGrok Swarm — Main GUI Application (v2 — Tabbed Layout).

Three-tab layout:
  🚀 Swarm     — Agent status bar, streaming output, task input
  🔑 API Keys  — 8 key slots with per-key status indicators
  ⚙️ Settings  — Model, tier, safety, behaviour, appearance
"""
import ctypes
import json
import os
import threading
import time
import tkinter as tk
import tkinter.filedialog as tkfd
import customtkinter as ctk

from config import (
    APP_NAME, WINDOW_WIDTH, WINDOW_HEIGHT, MAX_API_KEYS,
    GROK_MODELS, DEFAULT_MODEL, AGENT_ROLES, SAFETY_LEVELS,
)
from gui.theme import COLORS, FONT_FAMILY, FONT_SIZES
from gui.widgets import ActionButton, Tooltip, ConfirmDialog
from core.settings import load_settings, save_settings
from core.swarm import MiniGrokSwarm, list_grok_models, test_connection
from core.tools import set_confirm_callback, SwarmTools, READ_ONLY
from core.logger import ToolLogger


# ── Windows 11 Mica titlebar ────────────────────────────────

def _apply_mica(window):
    """Apply dark Mica titlebar on Windows 11+."""
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
        self._migrate_keys()
        self._running = False
        self._swarm: MiniGrokSwarm | None = None
        self._context_files: list[tuple[str, str]] = []
        self._agent_dots: dict[str, ctk.CTkLabel] = {}
        self._first_verifier_token = True

        # ─── Layout ─────────────────────────────────────────
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_nav_bar()
        self._pages: dict[str, ctk.CTkFrame] = {}
        self._build_swarm_page()
        self._build_keys_page()
        self._build_settings_page()
        self._build_log_page()
        self._switch_page("swarm")

        # ─── Tool confirmation system ───────────────────────
        set_confirm_callback(self._confirm_tool_action)

        # ─── Tool activity logger callback ──────────────────
        ToolLogger.set_callback(self._on_log_entry)

        # ─── Populate UI from saved settings ────────────────
        self._load_settings_to_ui()
        self.after(400, self._auto_check_keys)

    # ─────────────────────────────────────────────────────────
    # Migration: old key_1/key_2 → new api_keys list
    # ─────────────────────────────────────────────────────────
    def _migrate_keys(self):
        s = self._settings
        if "grok_api_key_1" in s:
            keys = s.get("api_keys", [""] * MAX_API_KEYS)
            if s["grok_api_key_1"]:
                keys[0] = s["grok_api_key_1"]
            if s.get("grok_api_key_2"):
                keys[1] = s["grok_api_key_2"]
            s["api_keys"] = keys
            s.pop("grok_api_key_1", None)
            s.pop("grok_api_key_2", None)
            save_settings(s)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # NAVIGATION BAR
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_nav_bar(self):
        nav = ctk.CTkFrame(self, fg_color=COLORS["bg_sidebar"],
                           corner_radius=0, height=56)
        nav.grid(row=0, column=0, sticky="ew")
        nav.grid_propagate(False)

        # Logo
        ctk.CTkLabel(
            nav, text="🤖 MiniGrok Swarm",
            font=(FONT_FAMILY, 18, "bold"),
            text_color=COLORS["accent"],
        ).pack(side="left", padx=(20, 40))

        # Tab buttons
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        tabs = [
            ("swarm",    "🚀  Swarm"),
            ("keys",     "🔑  API Keys"),
            ("settings", "⚙️  Settings"),
            ("log",      "📋  Log"),
        ]
        for key, label in tabs:
            btn = ctk.CTkButton(
                nav, text=label,
                font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
                fg_color="transparent",
                hover_color=COLORS["bg_hover"],
                text_color=COLORS["text_secondary"],
                corner_radius=8, height=40, width=125,
                command=lambda k=key: self._switch_page(k),
            )
            btn.pack(side="left", padx=3, pady=8)
            self._nav_btns[key] = btn

        # Right side — quick status summary
        self._nav_status = ctk.CTkLabel(
            nav, text="",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        self._nav_status.pack(side="right", padx=20)

    def _switch_page(self, page_name: str):
        for frame in self._pages.values():
            frame.grid_forget()
        self._pages[page_name].grid(row=1, column=0, sticky="nsew")

        for name, btn in self._nav_btns.items():
            if name == page_name:
                btn.configure(fg_color=COLORS["accent_dim"],
                              text_color=COLORS["accent"])
            else:
                btn.configure(fg_color="transparent",
                              text_color=COLORS["text_secondary"])

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 1 — 🚀 SWARM
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_swarm_page(self):
        page = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"],
                            corner_radius=0)
        self._pages["swarm"] = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        # ── Agent status bar ────────────────────────────────
        status_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"],
                                   corner_radius=10, height=50)
        status_card.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 5))

        self._agent_bar = ctk.CTkFrame(status_card, fg_color="transparent")
        self._agent_bar.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(
            self._agent_bar, text="Agents:",
            font=(FONT_FAMILY, FONT_SIZES["small"], "bold"),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", padx=(0, 8))

        self._rebuild_agent_dots()

        # ── Output panel ────────────────────────────────────
        self.output = ctk.CTkTextbox(
            page, font=("Consolas", FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=10, wrap="word",
        )
        self.output.grid(row=1, column=0, sticky="nsew", padx=15, pady=5)
        self.output.configure(state="disabled")

        # Text tags for coloured output
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
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "1. Go to 🔑 API Keys tab → paste at least one Grok API key\n"
            "2. Go to ⚙️ Settings tab → choose model, tier, safety level\n"
            "3. Come back here → type your task → hit 🚀 Run Swarm\n\n"
            "Tip: Add one key per agent for maximum rate-limit splitting.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
            tag="system",
        )

        # ── Input bar ───────────────────────────────────────
        input_card = ctk.CTkFrame(page, fg_color=COLORS["bg_card"],
                                  corner_radius=10)
        input_card.grid(row=2, column=0, sticky="ew", padx=15, pady=(5, 12))

        input_inner = ctk.CTkFrame(input_card, fg_color="transparent")
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
            command=self._run_swarm, style="success", width=140)
        self.btn_run.pack(pady=(0, 4))

        self.btn_research = ActionButton(
            btn_col, text="🔬 Research",
            command=self._run_research, style="primary", width=140)
        self.btn_research.pack(pady=(0, 4))

        self.btn_stop = ActionButton(
            btn_col, text="⏹ Stop",
            command=self._stop_swarm, style="danger", width=140)
        self.btn_stop.pack()
        self.btn_stop.configure(state="disabled")

        # Bottom info row
        info_row = ctk.CTkFrame(input_card, fg_color="transparent")
        info_row.pack(fill="x", padx=12, pady=(0, 6))

        self._counter_label = ctk.CTkLabel(
            info_row, text="",
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        )
        self._counter_label.pack(side="left")

        self._ctx_info_label = ctk.CTkLabel(
            info_row, text="",
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        )
        self._ctx_info_label.pack(side="right")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 2 — 🔑 API KEYS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_keys_page(self):
        page = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"],
                            corner_radius=0)
        self._pages["keys"] = page

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=15)

        # Header
        hdr = ctk.CTkFrame(scroll, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            hdr, text="🔑  API Keys",
            font=(FONT_FAMILY, FONT_SIZES["title"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left")

        ctk.CTkLabel(
            hdr,
            text="Add up to 8 xAI keys — one per agent for max rate-limit distribution",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        ).pack(side="left", padx=(15, 0))

        # ── Key slots card ──────────────────────────────────
        self._key_entries: list[ctk.CTkEntry] = []
        self._key_status_labels: list[ctk.CTkLabel] = []
        self._keys_visible = False

        keys_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                 corner_radius=12)
        keys_card.pack(fill="x", pady=(0, 10))

        for i in range(MAX_API_KEYS):
            row = ctk.CTkFrame(keys_card, fg_color="transparent")
            row.pack(fill="x", padx=15, pady=(10 if i == 0 else 3, 3))

            # Label with role hint
            role_hint = ""
            tier = self._settings.get("tier", "medium")
            roles = AGENT_ROLES.get(tier, AGENT_ROLES["medium"])
            if i < len(roles):
                role_hint = f"  →  {roles[i][0]}"

            ctk.CTkLabel(
                row, text=f"Key {i + 1}{role_hint}",
                font=(FONT_FAMILY, FONT_SIZES["small"], "bold"),
                text_color=COLORS["text_secondary"],
                width=200, anchor="w",
            ).pack(side="left")

            # Entry (masked)
            entry = ctk.CTkEntry(
                row, show="●",
                font=(FONT_FAMILY, FONT_SIZES["body"]),
                fg_color=COLORS["bg_input"],
                text_color=COLORS["text_primary"],
                border_color=COLORS["border"],
                border_width=1, corner_radius=8, height=34,
            )
            entry.pack(side="left", fill="x", expand=True, padx=(5, 8))
            self._key_entries.append(entry)

            # Status indicator
            status_lbl = ctk.CTkLabel(
                row, text="  ○  empty",
                font=(FONT_FAMILY, FONT_SIZES["small"]),
                text_color=COLORS["text_muted"],
                width=100, anchor="w",
            )
            status_lbl.pack(side="left")
            self._key_status_labels.append(status_lbl)

        # ── Button row ──────────────────────────────────────
        btn_row = ctk.CTkFrame(keys_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=15, pady=(10, 15))

        ActionButton(
            btn_row, text="💾  Save All Keys",
            command=self._save_keys, style="success", width=160,
        ).pack(side="left", padx=(0, 8))

        ActionButton(
            btn_row, text="🔌  Test All",
            command=self._test_all_keys, style="primary", width=120,
        ).pack(side="left", padx=(0, 8))

        self._show_hide_btn = ActionButton(
            btn_row, text="👁  Show Keys",
            command=self._toggle_key_vis, style="secondary", width=130,
        )
        self._show_hide_btn.pack(side="left", padx=(0, 8))

        ActionButton(
            btn_row, text="🗑  Clear Empty",
            command=self._compact_keys, style="secondary", width=130,
        ).pack(side="left")

        # Summary label
        self._keys_summary = ctk.CTkLabel(
            scroll, text="",
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            text_color=COLORS["text_muted"],
        )
        self._keys_summary.pack(anchor="w", pady=(5, 0))

        # ── Info card ───────────────────────────────────────
        info_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                 corner_radius=12)
        info_card.pack(fill="x", pady=(10, 0))

        info_text = (
            "💡  How API key distribution works:\n\n"
            "• Each parallel agent gets assigned a key round-robin\n"
            "• Key 1 → Agent 1 (Researcher),   "
            "Key 2 → Agent 2 (Planner),   etc.\n"
            "• If you have fewer keys than agents, keys are reused "
            "(still works fine)\n"
            "• More unique keys = less rate-limiting = faster swarm runs\n"
            "• The Verifier agent always uses Key 1\n\n"
            "Get keys from:  console.x.ai  →  API Keys  →  Create API Key"
        )
        ctk.CTkLabel(
            info_card, text=info_text,
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_secondary"],
            justify="left", anchor="w",
        ).pack(padx=20, pady=15, anchor="w")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 3 — ⚙️ SETTINGS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_settings_page(self):
        page = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"],
                            corner_radius=0)
        self._pages["settings"] = page

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=15)

        ctk.CTkLabel(
            scroll, text="⚙️  Settings",
            font=(FONT_FAMILY, FONT_SIZES["title"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", pady=(0, 15))

        # ────── Model & Agent Configuration ─────────────────
        cfg_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                corner_radius=12)
        cfg_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            cfg_card, text="🤖  Model & Agent Configuration",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=20, pady=(15, 10))

        cfg = ctk.CTkFrame(cfg_card, fg_color="transparent")
        cfg.pack(fill="x", padx=20, pady=(0, 15))
        cfg.grid_columnconfigure(1, weight=1)

        # Model selector
        ctk.CTkLabel(
            cfg, text="Model:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 15))

        self.model_menu = ctk.CTkOptionMenu(
            cfg, values=GROK_MODELS,
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=350, height=34,
            command=lambda _: self._update_nav_status(),
        )
        self.model_menu.grid(row=0, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            cfg,
            text=("grok-4-0709 = most capable  |  "
                  "grok-4-fast = balanced  |  grok-3-mini = cheapest"),
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 6))

        # Tier selector
        ctk.CTkLabel(
            cfg, text="Agent Tier:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=2, column=0, sticky="w", pady=6, padx=(0, 15))

        self.tier_menu = ctk.CTkOptionMenu(
            cfg,
            values=["minimum (2 agents)",
                    "medium (4 agents)",
                    "full (8 agents)"],
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=350, height=34,
            command=self._on_tier_change,
        )
        self.tier_menu.grid(row=2, column=1, sticky="w", pady=6)

        self._tier_detail = ctk.CTkLabel(
            cfg, text="",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
            justify="left",
        )
        self._tier_detail.grid(row=3, column=0, columnspan=2,
                               sticky="w", pady=(0, 6))

        # ────── Safety & Tool Access ────────────────────────
        safety_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                   corner_radius=12)
        safety_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            safety_card, text="🛡️  Safety & Tool Access",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=20, pady=(15, 10))

        safety_inner = ctk.CTkFrame(safety_card, fg_color="transparent")
        safety_inner.pack(fill="x", padx=20, pady=(0, 15))

        self.safety_menu = ctk.CTkOptionMenu(
            safety_inner,
            values=list(SAFETY_LEVELS.values()),
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=450, height=34,
            command=self._on_safety_change,
        )
        self.safety_menu.pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            safety_inner,
            text=(
                "🔒 Read-Only:  Agents can only take screenshots, "
                "OCR, read files, list dirs\n"
                "⚠️  Confirmed:  Write/execute tools show a confirmation "
                "dialog — you approve each one\n"
                "🔓 Full Auto:   No confirmation — agents execute "
                "all tools freely (dangerous!)"
            ),
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
            justify="left",
        ).pack(anchor="w")

        # ────── Verifier Backend ────────────────────────────
        verifier_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                     corner_radius=12)
        verifier_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            verifier_card, text="🧪  Verifier Backend",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=20, pady=(15, 10))

        vf = ctk.CTkFrame(verifier_card, fg_color="transparent")
        vf.pack(fill="x", padx=20, pady=(0, 15))
        vf.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            vf, text="Backend:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 15))

        self.verifier_menu = ctk.CTkOptionMenu(
            vf, values=["Ollama (Local)", "Grok (API)"],
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=350, height=34,
        )
        self.verifier_menu.grid(row=0, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            vf, text="Ollama Model:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 15))

        self.ollama_model_entry = ctk.CTkEntry(
            vf, font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=8, height=34, width=350,
            placeholder_text="qwen3-vl:4b-instruct",
        )
        self.ollama_model_entry.grid(row=1, column=1, sticky="w", pady=6)

        ctk.CTkLabel(
            vf, text="Ollama URL:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=2, column=0, sticky="w", pady=6, padx=(0, 15))

        self.ollama_url_entry = ctk.CTkEntry(
            vf, font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=8, height=34, width=350,
            placeholder_text="http://localhost:11434",
        )
        self.ollama_url_entry.grid(row=2, column=1, sticky="w", pady=6)

        test_row = ctk.CTkFrame(vf, fg_color="transparent")
        test_row.grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        ActionButton(
            test_row, text="🔌 Test Ollama",
            command=self._test_ollama, style="primary", width=140,
        ).pack(side="left", padx=(0, 10))

        self._ollama_status = ctk.CTkLabel(
            test_row, text="",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        self._ollama_status.pack(side="left")

        ctk.CTkLabel(
            vf,
            text=("Ollama = local uncensored verifier (no content refusals)\n"
                  "Grok = uses your API key (faster but may refuse some content)"),
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # ────── Swarm Behaviour ─────────────────────────────
        behav_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                  corner_radius=12)
        behav_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            behav_card, text="🧠  Swarm Behaviour",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=20, pady=(15, 10))

        behav = ctk.CTkFrame(behav_card, fg_color="transparent")
        behav.pack(fill="x", padx=20, pady=(0, 15))
        behav.grid_columnconfigure(1, weight=1)

        # Max tool rounds
        ctk.CTkLabel(
            behav, text="Max Tool Rounds:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 15))

        self.tool_rounds_slider = ctk.CTkSlider(
            behav, from_=1, to=15, number_of_steps=14,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=300,
            command=self._on_tool_rounds_change,
        )
        self.tool_rounds_slider.grid(row=0, column=1, sticky="w", pady=6)

        self._tool_rounds_label = ctk.CTkLabel(
            behav, text="5",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["accent"], width=30,
        )
        self._tool_rounds_label.grid(row=0, column=2, padx=(10, 0), pady=6)

        ctk.CTkLabel(
            behav,
            text=("How many times each agent can call PC tools per run. "
                  "Higher = more thorough but slower."),
            font=(FONT_FAMILY, FONT_SIZES["tiny"]),
            text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # Request timeout
        ctk.CTkLabel(
            behav, text="Request Timeout:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=2, column=0, sticky="w", pady=6, padx=(0, 15))

        self.timeout_slider = ctk.CTkSlider(
            behav, from_=30, to=600, number_of_steps=19,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=300,
            command=self._on_timeout_change,
        )
        self.timeout_slider.grid(row=2, column=1, sticky="w", pady=6)

        self._timeout_label = ctk.CTkLabel(
            behav, text="180s",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["accent"], width=45,
        )
        self._timeout_label.grid(row=2, column=2, padx=(10, 0), pady=6)

        # ────── Context Files ───────────────────────────────
        ctx_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                corner_radius=12)
        ctx_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            ctx_card, text="📎  Context Files",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            ctx_card,
            text=("Attach files to include as context for all agents "
                  "(code, docs, data, etc.)"),
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        ).pack(anchor="w", padx=20, pady=(0, 8))

        ctx_btns = ctk.CTkFrame(ctx_card, fg_color="transparent")
        ctx_btns.pack(fill="x", padx=20, pady=(0, 5))

        ActionButton(
            ctx_btns, text="+ Add Files",
            command=self._add_context_files, style="primary", width=130,
        ).pack(side="left", padx=(0, 8))

        ActionButton(
            ctx_btns, text="🗑 Clear All",
            command=self._clear_context, style="danger", width=110,
        ).pack(side="left")

        self._ctx_list_frame = ctk.CTkScrollableFrame(
            ctx_card, fg_color="transparent", height=100)
        self._ctx_list_frame.pack(fill="x", padx=20, pady=(0, 5))

        self._ctx_count_label = ctk.CTkLabel(
            ctx_card, text="No files attached",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        self._ctx_count_label.pack(anchor="w", padx=20, pady=(0, 15))

        # ────── Appearance ──────────────────────────────────
        appear_card = ctk.CTkFrame(scroll, fg_color=COLORS["bg_card"],
                                   corner_radius=12)
        appear_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            appear_card, text="🎨  Appearance",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(anchor="w", padx=20, pady=(15, 10))

        appear = ctk.CTkFrame(appear_card, fg_color="transparent")
        appear.pack(fill="x", padx=20, pady=(0, 15))
        appear.grid_columnconfigure(1, weight=1)

        # Opacity slider
        ctk.CTkLabel(
            appear, text="Window Opacity:",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["text_secondary"],
        ).grid(row=0, column=0, sticky="w", pady=6, padx=(0, 15))

        self.opacity_slider = ctk.CTkSlider(
            appear, from_=0.5, to=1.0, number_of_steps=10,
            fg_color=COLORS["bg_input"],
            progress_color=COLORS["accent"],
            button_color=COLORS["accent"],
            button_hover_color=COLORS["accent_hover"],
            width=300,
            command=self._on_opacity_change,
        )
        self.opacity_slider.grid(row=0, column=1, sticky="w", pady=6)

        self._opacity_label = ctk.CTkLabel(
            appear, text="97%",
            font=(FONT_FAMILY, FONT_SIZES["body"], "bold"),
            text_color=COLORS["accent"], width=40,
        )
        self._opacity_label.grid(row=0, column=2, padx=(10, 0), pady=6)

        # Always on top checkbox
        self._aot_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            appear, text="Always on top",
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            text_color=COLORS["text_secondary"],
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            variable=self._aot_var,
            command=self._on_aot_change,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=6)

        # ────── Save All ────────────────────────────────────
        save_row = ctk.CTkFrame(scroll, fg_color="transparent")
        save_row.pack(fill="x", pady=(5, 20))

        ActionButton(
            save_row, text="💾  Save All Settings",
            command=self._save_all_settings, style="success", width=200,
        ).pack(side="left")

        self._settings_status = ctk.CTkLabel(
            save_row, text="",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        self._settings_status.pack(side="left", padx=(15, 0))

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # PAGE 4 — 📋 LOG
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _build_log_page(self):
        page = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"],
                            corner_radius=0)
        self._pages["log"] = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        # ── Header bar ──────────────────────────────────────
        hdr = ctk.CTkFrame(page, fg_color=COLORS["bg_card"],
                           corner_radius=10, height=50)
        hdr.grid(row=0, column=0, sticky="ew", padx=15, pady=(12, 5))

        ctk.CTkLabel(
            hdr, text="📋  Tool Activity Log",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["text_primary"],
        ).pack(side="left", padx=15, pady=10)

        self._log_count_label = ctk.CTkLabel(
            hdr, text="0 entries",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        self._log_count_label.pack(side="left", padx=(10, 0))

        ActionButton(
            hdr, text="💾 Export",
            command=self._export_log, style="primary", width=100,
        ).pack(side="right", padx=(5, 15), pady=10)

        ActionButton(
            hdr, text="🗑 Clear",
            command=self._clear_log, style="danger", width=90,
        ).pack(side="right", padx=5, pady=10)

        # ── Log output textbox ──────────────────────────────
        self._log_output = ctk.CTkTextbox(
            page, font=("Consolas", FONT_SIZES["small"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["border"],
            border_width=1, corner_radius=10, wrap="word",
        )
        self._log_output.grid(row=1, column=0, sticky="nsew",
                              padx=15, pady=(5, 12))
        self._log_output.configure(state="disabled")

        # Text tags
        try:
            tb = self._log_output._textbox
            tb.tag_configure("log_success",
                             foreground=COLORS["accent_green"])
            tb.tag_configure("log_blocked",
                             foreground=COLORS["error"])
            tb.tag_configure("log_error",
                             foreground=COLORS["accent_yellow"])
            tb.tag_configure("log_tool",
                             foreground=COLORS["accent"])
        except Exception:
            pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LOG HELPERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_log_entry(self, entry: dict):
        """Callback from ToolLogger — append entry to log tab."""
        text = ToolLogger.format_entry(entry) + "\n"
        tag = None
        if entry.get("blocked"):
            tag = "log_blocked"
        elif entry.get("success"):
            tag = "log_success"
        else:
            tag = "log_error"

        def _ui():
            self._log_output.configure(state="normal")
            if tag:
                start = self._log_output.index("end-1c")
                self._log_output.insert("end", text)
                end = self._log_output.index("end-1c")
                try:
                    self._log_output._textbox.tag_add(tag, start, end)
                except Exception:
                    pass
            else:
                self._log_output.insert("end", text)
            self._log_output.configure(state="disabled")
            self._log_output.see("end")
            self._log_count_label.configure(
                text=f"{ToolLogger.entry_count()} entries")
        self.after(0, _ui)

    def _export_log(self):
        path = tkfd.asksaveasfilename(
            title="Export Tool Log",
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("JSON", "*.json")],
            initialfile=f"grokhive_log_{time.strftime('%Y%m%d_%H%M%S')}.txt",
        )
        if path:
            if path.endswith(".json"):
                ToolLogger.save_to_file(path)
            else:
                ToolLogger.export_readable(path)
            self._append_output(
                f"\n📋 Log exported → {path}\n", tag="system")

    def _clear_log(self):
        ToolLogger.clear()
        self._log_output.configure(state="normal")
        self._log_output.delete("1.0", "end")
        self._log_output.configure(state="disabled")
        self._log_count_label.configure(text="0 entries")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # OLLAMA TEST
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _test_ollama(self):
        url = (self.ollama_url_entry.get().strip()
               or "http://localhost:11434")
        model = (self.ollama_model_entry.get().strip()
                 or "qwen3-vl:4b-instruct")
        self._ollama_status.configure(
            text="⏳ Testing...", text_color=COLORS["text_muted"])

        def _bg():
            try:
                import urllib.request as _ur
                req = _ur.Request(f"{url}/api/tags")
                resp = _ur.urlopen(req, timeout=5)
                data = json.loads(resp.read().decode())
                resp.close()
                names = [m["name"] for m in data.get("models", [])]
                found = model in names or any(
                    model in n for n in names)

                def _done():
                    if found:
                        self._ollama_status.configure(
                            text=f"✅ Connected — {model} available",
                            text_color=COLORS["accent_green"])
                    else:
                        short = ", ".join(names[:5])
                        self._ollama_status.configure(
                            text=f"⚠️ Connected but '{model}' "
                                 f"not found. Available: {short}",
                            text_color=COLORS["accent_yellow"])
                self.after(0, _done)
            except Exception as e:
                def _err():
                    self._ollama_status.configure(
                        text=f"❌ {e}",
                        text_color=COLORS["error"])
                self.after(0, _err)

        threading.Thread(target=_bg, daemon=True).start()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # API KEY LOGIC
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _save_keys(self):
        keys = [e.get().strip() for e in self._key_entries]
        self._settings["api_keys"] = keys
        save_settings(self._settings)
        self._update_key_statuses()
        n = sum(1 for k in keys if k)
        self._keys_summary.configure(
            text=f"✅ {n} key{'s' if n != 1 else ''} saved",
            text_color=COLORS["accent_green"],
        )
        self._update_nav_status()

    def _test_all_keys(self):
        self._keys_summary.configure(
            text="⏳ Testing keys...", text_color=COLORS["text_muted"])

        def _bg():
            results = []
            for i, entry in enumerate(self._key_entries):
                key = entry.get().strip()
                if not key:
                    results.append((i, None, ""))
                    continue
                ok, msg = test_connection(key)
                results.append((i, ok, msg))

            def _done():
                good = 0
                for idx, ok, msg in results:
                    lbl = self._key_status_labels[idx]
                    if ok is None:
                        lbl.configure(text="  ○  empty",
                                      text_color=COLORS["text_muted"])
                    elif ok:
                        lbl.configure(text="  ✅ valid",
                                      text_color=COLORS["accent_green"])
                        good += 1
                    else:
                        lbl.configure(text="  ❌ invalid",
                                      text_color=COLORS["error"])

                self._keys_summary.configure(
                    text=f"Test complete: {good} valid "
                         f"key{'s' if good != 1 else ''}",
                    text_color=(COLORS["accent_green"]
                                if good > 0 else COLORS["error"]),
                )
                self._update_nav_status()

                # Refresh model list from first valid key
                first_key = next(
                    (e.get().strip() for e in self._key_entries
                     if e.get().strip()), "")
                if first_key:
                    models = list_grok_models(first_key)
                    if models:
                        self.model_menu.configure(values=models)
                        pref = self._settings.get("model", DEFAULT_MODEL)
                        if pref in models:
                            self.model_menu.set(pref)

            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _toggle_key_vis(self):
        self._keys_visible = not self._keys_visible
        show_char = "" if self._keys_visible else "●"
        for e in self._key_entries:
            e.configure(show=show_char)
        self._show_hide_btn.configure(
            text="🙈  Hide Keys" if self._keys_visible
            else "👁  Show Keys",
        )

    def _compact_keys(self):
        keys = [e.get().strip() for e in self._key_entries]
        filled = [k for k in keys if k]
        padded = filled + [""] * (MAX_API_KEYS - len(filled))
        for i, e in enumerate(self._key_entries):
            e.delete(0, "end")
            if padded[i]:
                e.insert(0, padded[i])
        self._update_key_statuses()

    def _update_key_statuses(self):
        for i, entry in enumerate(self._key_entries):
            lbl = self._key_status_labels[i]
            if entry.get().strip():
                lbl.configure(text="  ●  set",
                              text_color=COLORS["accent_yellow"])
            else:
                lbl.configure(text="  ○  empty",
                              text_color=COLORS["text_muted"])

    def _auto_check_keys(self):
        self._update_key_statuses()
        self._update_nav_status()
        # Auto-test first key in background
        keys = [e.get().strip() for e in self._key_entries]
        first_key = next((k for k in keys if k), "")
        if not first_key:
            return

        def _bg():
            ok, msg = test_connection(first_key)
            models = list_grok_models(first_key) if ok else []

            def _done():
                if ok:
                    for i, e in enumerate(self._key_entries):
                        if e.get().strip() == first_key:
                            self._key_status_labels[i].configure(
                                text="  ✅ valid",
                                text_color=COLORS["accent_green"],
                            )
                            break
                    self._update_nav_status()
                    if models:
                        self.model_menu.configure(values=models)
                        pref = self._settings.get("model", DEFAULT_MODEL)
                        if pref in models:
                            self.model_menu.set(pref)
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _update_nav_status(self):
        keys = self._get_active_keys()
        n_keys = len(keys)
        tier = self._get_tier_key()
        n_agents = len(AGENT_ROLES.get(tier, []))
        model = (self.model_menu.get()
                 if hasattr(self, "model_menu") else "—")
        self._nav_status.configure(
            text=f"🔑 {n_keys} keys  •  "
                 f"👥 {n_agents} agents  •  🤖 {model}",
        )

    def _get_active_keys(self) -> list[str]:
        return [e.get().strip()
                for e in self._key_entries if e.get().strip()]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # SETTINGS LOGIC
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _get_tier_key(self) -> str:
        val = (self.tier_menu.get()
               if hasattr(self, "tier_menu") else "medium")
        if val.startswith("minimum"):
            return "minimum"
        if val.startswith("full"):
            return "full"
        return "medium"

    def _get_safety_key(self) -> str:
        val = (self.safety_menu.get()
               if hasattr(self, "safety_menu") else "confirmed")
        if "Read-Only" in val:
            return "read_only"
        if "Full Auto" in val:
            return "full_auto"
        return "confirmed"

    def _on_tier_change(self, _v=None):
        self._rebuild_agent_dots()
        self._update_tier_detail()
        self._update_nav_status()

    def _update_tier_detail(self):
        tier = self._get_tier_key()
        roles = AGENT_ROLES.get(tier, [])
        names = ", ".join(r[0] for r in roles)
        self._tier_detail.configure(text=f"Agents: {names}  +  ✅ Verifier")

    def _on_safety_change(self, _v=None):
        SwarmTools.safety_level = self._get_safety_key()

    def _on_tool_rounds_change(self, value):
        self._tool_rounds_label.configure(text=str(int(value)))

    def _on_timeout_change(self, value):
        self._timeout_label.configure(text=f"{int(value)}s")

    def _on_opacity_change(self, value):
        v = round(value, 2)
        self._opacity_label.configure(text=f"{int(v * 100)}%")
        self.attributes("-alpha", v)

    def _on_aot_change(self):
        self.attributes("-topmost", self._aot_var.get())

    def _save_all_settings(self):
        self._settings["model"] = self.model_menu.get()
        self._settings["tier"] = self._get_tier_key()
        self._settings["safety_level"] = self._get_safety_key()
        self._settings["max_tool_rounds"] = int(self.tool_rounds_slider.get())
        self._settings["request_timeout"] = int(self.timeout_slider.get())
        self._settings["window_opacity"] = round(self.opacity_slider.get(), 2)
        self._settings["always_on_top"] = self._aot_var.get()
        self._settings["api_keys"] = [e.get().strip()
                                      for e in self._key_entries]
        # Verifier
        vb = self.verifier_menu.get()
        self._settings["verifier_backend"] = (
            "ollama" if "Ollama" in vb else "grok")
        self._settings["ollama_model"] = (
            self.ollama_model_entry.get().strip()
            or "qwen3-vl:4b-instruct")
        self._settings["ollama_url"] = (
            self.ollama_url_entry.get().strip()
            or "http://localhost:11434")
        save_settings(self._settings)
        self._settings_status.configure(
            text="✅ Settings saved!",
            text_color=COLORS["accent_green"],
        )
        self._update_nav_status()
        self.after(3000, lambda: self._settings_status.configure(text=""))

    def _load_settings_to_ui(self):
        s = self._settings

        # Keys
        keys = s.get("api_keys", [""] * MAX_API_KEYS)
        for i, entry in enumerate(self._key_entries):
            entry.delete(0, "end")
            if i < len(keys) and keys[i]:
                entry.insert(0, keys[i])

        # Model
        model = s.get("model", DEFAULT_MODEL)
        if model in GROK_MODELS:
            self.model_menu.set(model)

        # Tier
        tier = s.get("tier", "medium")
        tier_map = {
            "minimum": "minimum (2 agents)",
            "medium":  "medium (4 agents)",
            "full":    "full (8 agents)",
        }
        self.tier_menu.set(tier_map.get(tier, tier_map["medium"]))
        self._rebuild_agent_dots()
        self._update_tier_detail()

        # Safety
        safety = s.get("safety_level", "confirmed")
        self.safety_menu.set(
            SAFETY_LEVELS.get(safety, SAFETY_LEVELS["confirmed"]))
        SwarmTools.safety_level = safety

        # Behaviour sliders
        self.tool_rounds_slider.set(s.get("max_tool_rounds", 5))
        self._tool_rounds_label.configure(
            text=str(s.get("max_tool_rounds", 5)))
        self.timeout_slider.set(s.get("request_timeout", 180))
        self._timeout_label.configure(
            text=f"{s.get('request_timeout', 180)}s")

        # Appearance
        opacity = s.get("window_opacity", 0.97)
        self.opacity_slider.set(opacity)
        self._opacity_label.configure(text=f"{int(opacity * 100)}%")
        self.attributes("-alpha", opacity)

        aot = s.get("always_on_top", False)
        self._aot_var.set(aot)
        self.attributes("-topmost", aot)

        # Verifier
        vb = s.get("verifier_backend", "ollama")
        self.verifier_menu.set(
            "Ollama (Local)" if vb == "ollama" else "Grok (API)")
        om = s.get("ollama_model", "qwen3-vl:4b-instruct")
        self.ollama_model_entry.delete(0, "end")
        self.ollama_model_entry.insert(0, om)
        ou = s.get("ollama_url", "http://localhost:11434")
        self.ollama_url_entry.delete(0, "end")
        self.ollama_url_entry.insert(0, ou)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # AGENT STATUS DOTS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _rebuild_agent_dots(self):
        for w in list(self._agent_bar.winfo_children()):
            if isinstance(w, ctk.CTkLabel) and w.cget("text") != "Agents:":
                w.destroy()
        self._agent_dots.clear()

        tier = self._get_tier_key()
        roles = AGENT_ROLES.get(tier, AGENT_ROLES["medium"])

        for role_name, _ in roles:
            dot = ctk.CTkLabel(
                self._agent_bar, text=f"● {role_name}",
                font=(FONT_FAMILY, FONT_SIZES["small"]),
                text_color=COLORS["text_muted"],
            )
            dot.pack(side="left", padx=(0, 10))
            self._agent_dots[role_name] = dot

        # Verifier dot
        vdot = ctk.CTkLabel(
            self._agent_bar, text="● ✅ Verifier",
            font=(FONT_FAMILY, FONT_SIZES["small"]),
            text_color=COLORS["text_muted"],
        )
        vdot.pack(side="left", padx=(0, 10))
        self._agent_dots["✅ Verifier"] = vdot

    def _update_agent_dot(self, role: str, status: str):
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
                continue
            try:
                with open(path, "r", encoding="utf-8",
                          errors="replace") as f:
                    content = f.read()[:30000]
                self._context_files.append((path, content))
            except Exception:
                continue
        self._refresh_context_list()

    def _clear_context(self):
        self._context_files.clear()
        self._refresh_context_list()

    def _refresh_context_list(self):
        for w in self._ctx_list_frame.winfo_children():
            w.destroy()

        for path, content in self._context_files:
            name = os.path.basename(path)
            wc = len(content.split())
            row = ctk.CTkFrame(self._ctx_list_frame,
                               fg_color=COLORS["bg_input"], corner_radius=6)
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                row, text=f"📄 {name[:40]}  ({wc:,}w)",
                font=(FONT_FAMILY, FONT_SIZES["small"]),
                text_color=COLORS["text_primary"], anchor="w",
            ).pack(fill="x", padx=8, pady=3)

        total = len(self._context_files)
        tw = sum(len(c.split()) for _, c in self._context_files)
        txt = (f"{total} file{'s' if total != 1 else ''}  •  "
               f"{tw:,} words") if total else "No files attached"
        self._ctx_count_label.configure(text=txt)
        self._ctx_info_label.configure(
            text=f"📎 {total} context files" if total else "",
        )

    def _build_context_string(self) -> str:
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

        keys = self._get_active_keys()
        if not keys:
            self._append_output(
                "\n⚠️  No API keys! Go to the 🔑 API Keys tab "
                "and add at least one.\n",
                tag="error",
            )
            self._switch_page("keys")
            return

        self._switch_page("swarm")
        self.task_input.delete("1.0", "end")

        tier_key = self._get_tier_key()
        n_agents = len(AGENT_ROLES.get(tier_key, []))
        model = self.model_menu.get()

        self._append_output(f"\n{'━' * 65}\n", tag="system")
        self._append_output(f"📝 TASK: {task}\n", tag="system")
        self._append_output(
            f"⚙️  Model: {model}  •  Tier: {tier_key} ({n_agents} "
            f"agents)  •  Safety: {self._get_safety_key()}"
            f"  •  Keys: {len(keys)}\n",
            tag="system",
        )
        vb = self._settings.get("verifier_backend", "ollama")
        vb_display = (f"Ollama ({self._settings.get('ollama_model', 'qwen3-vl:4b-instruct')})"
                      if vb == "ollama" else "Grok API")
        self._append_output(
            f"🧪 Verifier: {vb_display}\n",
            tag="system",
        )
        self._append_output(f"{'━' * 65}\n\n", tag="system")

        # Reset dots
        for dot in self._agent_dots.values():
            dot.configure(text_color=COLORS["text_muted"])

        SwarmTools.safety_level = self._get_safety_key()
        self._running = True
        self.btn_run.configure(state="disabled")
        self.btn_research.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._first_verifier_token = True

        context = self._build_context_string()

        self._swarm = MiniGrokSwarm(
            api_keys=keys,
            model=model,
            tier=tier_key,
            max_tool_rounds=int(self.tool_rounds_slider.get()),
            timeout=int(self.timeout_slider.get()),
            verifier_backend=self._settings.get(
                "verifier_backend", "ollama"),
            ollama_model=self._settings.get(
                "ollama_model", "qwen3-vl:4b-instruct"),
            ollama_url=self._settings.get(
                "ollama_url", "http://localhost:11434"),
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
                self.btn_research.configure(state="normal")
                self.btn_stop.configure(state="disabled")
                self._swarm = None

                elapsed = result.get("elapsed", 0)
                n = len(result.get("agent_outputs", {}))

                if result["success"]:
                    self._append_output(
                        f"\n\n{'━' * 65}\n"
                        f"✅ DONE — {n} agents • {elapsed:.1f}s\n"
                        f"{'━' * 65}\n",
                        tag="system",
                    )
                    out = result.get("final_output", "")
                    self._counter_label.configure(
                        text=f"{n} agents  •  {elapsed:.1f}s  •  "
                             f"{len(out.split())} words",
                    )
                else:
                    self._append_output(
                        f"\n\n❌ ERROR: "
                        f"{result.get('error', 'Unknown')}\n",
                        tag="error",
                    )
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _stop_swarm(self):
        if self._swarm:
            self._swarm.cancel()
            self._append_output("\n⏹ Stopping swarm...\n", tag="system")

    def _run_research(self):
        """Launch autonomous research loop — overnight browser scraping."""
        if self._running:
            return

        topic = self.task_input.get("1.0", "end-1c").strip()
        if not topic:
            return

        keys = self._get_active_keys()
        if not keys:
            self._append_output(
                "\n⚠️  No API keys! Go to the 🔑 API Keys tab "
                "and add at least one.\n",
                tag="error",
            )
            self._switch_page("keys")
            return

        self._switch_page("swarm")
        self.task_input.delete("1.0", "end")

        # Research output folder
        output_dir = os.path.join(
            os.path.expanduser("~"), "Documents", "GrokHive_Research",
            topic[:40].replace(" ", "_").replace("/", "_"),
        )

        tier_key = self._get_tier_key()
        model = self.model_menu.get()
        max_rounds = int(self._settings.get("max_tool_rounds", 5)) * 4

        self._append_output(f"\n{'━' * 65}\n", tag="system")
        self._append_output(
            f"🔬 RESEARCH MODE: {topic}\n", tag="system")
        self._append_output(
            f"📁 Output: {output_dir}\n", tag="system")
        self._append_output(
            f"🔄 Max rounds: {max_rounds}  •  Model: {model}  •  "
            f"Agents: {tier_key}\n", tag="system")
        self._append_output(
            f"⏹ Press Stop to end early — all findings saved.\n",
            tag="system")
        self._append_output(f"{'━' * 65}\n\n", tag="system")

        for dot in self._agent_dots.values():
            dot.configure(text_color=COLORS["text_muted"])

        SwarmTools.safety_level = self._get_safety_key()
        self._running = True
        self.btn_run.configure(state="disabled")
        self.btn_research.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._first_verifier_token = True

        self._swarm = MiniGrokSwarm(
            api_keys=keys,
            model=model,
            tier=tier_key,
            max_tool_rounds=int(self.tool_rounds_slider.get()),
            timeout=int(self.timeout_slider.get()),
            verifier_backend=self._settings.get(
                "verifier_backend", "ollama"),
            ollama_model=self._settings.get(
                "ollama_model", "qwen3-vl:4b-instruct"),
            ollama_url=self._settings.get(
                "ollama_url", "http://localhost:11434"),
        )
        swarm = self._swarm

        def _on_round(num, total, subtopic):
            def _ui():
                self._first_verifier_token = True
                self._append_output(
                    f"\n{'─' * 50}\n"
                    f"🔄 Round {num}/{total}: {subtopic}\n"
                    f"{'─' * 50}\n\n",
                    tag="system",
                )
                self._counter_label.configure(
                    text=f"🔬 Research round {num}/{total}",
                )
                for dot in self._agent_dots.values():
                    dot.configure(text_color=COLORS["text_muted"])
            self.after(0, _ui)

        def _bg():
            result = swarm.run_research_loop(
                topic=topic,
                output_dir=output_dir,
                max_rounds=max_rounds,
                on_round=_on_round,
                on_agent_status=self._on_agent_status,
                on_agent_done=self._on_agent_done,
                on_verifier_token=self._on_verifier_token,
            )

            def _done():
                self._running = False
                self.btn_run.configure(state="normal")
                self.btn_research.configure(state="normal")
                self.btn_stop.configure(state="disabled")
                self._swarm = None

                n = result.get("total_rounds", 0)
                elapsed = result.get("elapsed", 0)
                files = result.get("files_created", [])

                self._append_output(
                    f"\n\n{'━' * 65}\n"
                    f"🔬 RESEARCH COMPLETE — {n} rounds • "
                    f"{elapsed / 60:.1f} min • "
                    f"{len(files)} files saved\n"
                    f"📁 {output_dir}\n"
                    f"{'━' * 65}\n",
                    tag="system",
                )
                self._counter_label.configure(
                    text=f"🔬 {n} rounds  •  {elapsed / 60:.1f} min  •  "
                         f"{len(files)} files",
                )
            self.after(0, _done)

        threading.Thread(target=_bg, daemon=True).start()

    def _on_agent_status(self, role: str, status: str):
        self._update_agent_dot(role, status)
        if "🔧" in status:
            self.after(0, lambda: self._append_output(
                f"  {role} → {status}\n", tag="tool",
            ))

    def _on_agent_done(self, role: str, output: str):
        def _ui():
            self._append_output(f"\n──── {role} ────\n",
                                tag="agent_header")
            self._append_output(f"{output}\n")
        self.after(0, _ui)

    def _on_verifier_token(self, token: str):
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
    # OUTPUT HELPERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _append_output(self, text: str, tag: str | None = None):
        self.output.configure(state="normal")
        if tag:
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
