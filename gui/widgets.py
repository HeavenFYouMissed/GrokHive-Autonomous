"""
Reusable widgets for the MiniGrok Swarm GUI.
"""
import customtkinter as ctk
from gui.theme import COLORS, FONT_FAMILY, FONT_SIZES


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ACTION BUTTON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_BTN_STYLES = {
    "primary":   {"fg_color": COLORS["accent"],
                  "hover_color": COLORS["accent_hover"],
                  "text_color": "#ffffff"},
    "secondary": {"fg_color": COLORS["bg_card"],
                  "hover_color": COLORS["bg_hover"],
                  "text_color": COLORS["text_secondary"]},
    "success":   {"fg_color": "#1a7d43",
                  "hover_color": "#2ed573",
                  "text_color": "#ffffff"},
    "danger":    {"fg_color": "#7d1a1a",
                  "hover_color": "#ff4757",
                  "text_color": "#ffffff"},
    "warning":   {"fg_color": "#7d5e1a",
                  "hover_color": "#ffa502",
                  "text_color": "#ffffff"},
}


class ActionButton(ctk.CTkButton):
    """Styled button matching the LoRA Toolkit look-and-feel."""

    def __init__(self, parent, text="", command=None,
                 style="primary", width=120, **kwargs):
        s = _BTN_STYLES.get(style, _BTN_STYLES["primary"])
        kwargs.pop("height", None)
        super().__init__(
            parent, text=text, command=command,
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            corner_radius=8, height=38, width=width,
            **s, **kwargs,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TOOLTIP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Tooltip:
    """Hover tooltip for any widget — with show delay to prevent flicker."""

    _DELAY_MS = 450  # ms before tooltip appears

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule_show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Button-1>", self._hide)

    def _schedule_show(self, _event):
        self._cancel()
        self._after_id = self.widget.after(self._DELAY_MS, self._show)

    def _show(self):
        self._cancel()
        self._destroy_tip()
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            self._tip = ctk.CTkToplevel(self.widget)
            self._tip.withdraw()
            self._tip.wm_overrideredirect(True)
            self._tip.configure(fg_color=COLORS["bg_card"])
            self._tip.wm_geometry(f"+{x}+{y}")
            self._tip.attributes("-topmost", True)
            label = ctk.CTkLabel(
                self._tip, text=self.text,
                font=(FONT_FAMILY, FONT_SIZES["small"]),
                fg_color=COLORS["bg_card"],
                text_color=COLORS["text_secondary"],
                corner_radius=6,
            )
            label.pack(padx=8, pady=5)
            self._tip.deiconify()
        except Exception:
            self._destroy_tip()

    def _hide(self, _event=None):
        self._cancel()
        self._destroy_tip()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _destroy_tip(self):
        tip = self._tip
        self._tip = None
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIRM DIALOG (for tool safety)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ConfirmDialog(ctk.CTkToplevel):
    """Modal confirmation dialog for dangerous tool actions.

    The tool thread blocks on a threading.Event while this is shown.
    """

    def __init__(self, parent, action_text: str):
        super().__init__(parent)
        self.confirmed = False

        self.title("🔧 Tool Confirmation")
        self.geometry("500x320")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg_dark"])
        self.attributes("-topmost", True)
        self.grab_set()

        # Centre on parent
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - 500) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - 320) // 2
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            inner, text="⚠️  Agent Tool Request",
            font=(FONT_FAMILY, FONT_SIZES["heading"], "bold"),
            text_color=COLORS["warning"],
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            inner,
            text="A swarm agent wants to execute the following action.\n"
                 "Review carefully before allowing.",
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            text_color=COLORS["text_secondary"],
            wraplength=450, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        # Action preview
        action_box = ctk.CTkTextbox(
            inner, height=120,
            font=(FONT_FAMILY, FONT_SIZES["body"]),
            fg_color=COLORS["bg_input"],
            text_color=COLORS["text_primary"],
            border_color=COLORS["warning"],
            border_width=1, corner_radius=8, wrap="word",
        )
        action_box.pack(fill="x", pady=(0, 15))
        action_box.insert("1.0", action_text)
        action_box.configure(state="disabled")

        # Buttons
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        ActionButton(
            btn_row, text="✅  Allow", command=self._allow,
            style="success", width=140,
        ).pack(side="left", padx=(0, 10))

        ActionButton(
            btn_row, text="❌  Deny", command=self._deny,
            style="danger", width=140,
        ).pack(side="left", padx=(0, 10))

        ActionButton(
            btn_row, text="🔒  Deny & Lock Read-Only",
            command=self._deny_and_lock,
            style="secondary", width=200,
        ).pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self._deny)

    def _allow(self):
        self.confirmed = True
        self.grab_release()
        self.destroy()

    def _deny(self):
        self.confirmed = False
        self.grab_release()
        self.destroy()

    def _deny_and_lock(self):
        """Deny + switch safety to read-only for the rest of the session."""
        from core.tools import SwarmTools, READ_ONLY
        SwarmTools.safety_level = READ_ONLY
        self.confirmed = False
        self.grab_release()
        self.destroy()
