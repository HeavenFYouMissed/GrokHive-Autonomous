"""
MiniGrok Swarm — Configuration constants.
"""
import os

APP_NAME = "MiniGrok Swarm"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 850
MAX_API_KEYS = 8

# ── Grok API ────────────────────────────────────────────────
GROK_API_URL = "https://api.x.ai/v1/chat/completions"
GROK_MODELS_URL = "https://api.x.ai/v1/models"

GROK_MODELS = [
    "grok-4-0709",
    "grok-4-fast-reasoning",
    "grok-4-fast-non-reasoning",
    "grok-4-1-fast-reasoning",
    "grok-4-1-fast-non-reasoning",
    "grok-3",
    "grok-3-mini",
    "grok-code-fast-1",
]
DEFAULT_MODEL = "grok-4-0709"

# ── Agent Roles (tiered) ───────────────────────────────────
AGENT_ROLES = {
    "minimum": [
        ("🔍 Researcher", "Deep research — facts, references, vulnerability analysis, documentation lookup"),
        ("📋 Planner",    "Architecture planning — steps, edge cases, project structure, dependencies"),
    ],
    "medium": [
        ("🔍 Researcher", "Deep research — facts, references, vulnerability analysis, documentation lookup"),
        ("📋 Planner",    "Architecture planning — steps, edge cases, project structure, dependencies"),
        ("💻 Coder",      "Code generation — scripts, implementations, algorithms, clean production code"),
        ("🧪 Tester",     "Testing & QA — simulate edge cases, find flaws, adversarial testing, validation"),
    ],
    "full": [
        ("🔍 Researcher", "Deep research — facts, references, vulnerability analysis, documentation lookup"),
        ("📋 Planner",    "Architecture planning — steps, edge cases, project structure, dependencies"),
        ("💻 Coder",      "Code generation — scripts, implementations, algorithms, clean production code"),
        ("🧪 Tester",     "Testing & QA — simulate edge cases, find flaws, adversarial testing, validation"),
        ("⚡ Optimizer",  "Performance optimization — efficiency improvements, complexity reduction, caching"),
        ("🛡️ Security",   "Security audit — vulnerability scanning, hardening, evasion detection, safe defaults"),
        ("🔗 Integrator", "System integration — merge components, resolve conflicts, ensure compatibility"),
        ("✅ QA",         "Final quality assurance — documentation, polish, completeness, standards compliance"),
    ],
}

# ── Safety Levels ───────────────────────────────────────────
SAFETY_LEVELS = {
    "read_only":  "🔒 Read-Only (screenshots, OCR, file reading)",
    "confirmed":  "⚠️ Confirmed (asks before write/execute)",
    "full_auto":  "🔓 Full Auto (no confirmation — dangerous!)",
}
