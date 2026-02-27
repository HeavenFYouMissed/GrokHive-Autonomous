# 🤖 MiniGrok Swarm

**Tiered parallel agent swarm powered by xAI's Grok API with PC automation tools.**

Inspired by [kyegomez/swarms](https://github.com/kyegomez/swarms) HeavySwarm architecture — multiple specialist AI agents work **simultaneously** on your task, then a Verifier agent synthesises the best answer.

![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

| Feature | Description |
|---|---|
| **Parallel Agents** | 2 / 4 / 8 specialist agents run in TRUE parallel via `ThreadPoolExecutor` |
| **Verifier Synthesis** | Final agent cross-checks all outputs and merges into one polished response |
| **PC Automation Tools** | Screenshots, OCR, PowerShell, file I/O, keyboard/mouse, VS Code control |
| **Safety Tiers** | Read-Only → Confirmed → Full Auto — you choose the risk level |
| **Streaming Output** | Verifier output streams token-by-token; agent progress shows in real-time |
| **Dual API Keys** | Split rate-limit pressure across two xAI API keys |
| **Dark OLED GUI** | CustomTkinter dark theme with Windows 11 Mica titlebar effect |
| **Context Files** | Attach local files as context — contents are fed to every agent |

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│                    MiniGrok Swarm                       │
│                                                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │🔍Research │  │📋Planner │  │💻 Coder  │  │🧪Tester│ │
│  │  Agent   │  │  Agent   │  │  Agent   │  │ Agent  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───┬────┘ │
│       │              │              │             │      │
│       │  ┌───────────┴──────────────┴─────┐      │      │
│       └──┤       PC Automation Tools      ├──────┘      │
│          │  screenshot · OCR · PowerShell  │             │
│          │  file I/O · keyboard · mouse    │             │
│          └───────────┬─────────────────────┘             │
│                      │                                   │
│              ┌───────┴────────┐                          │
│              │ ✅ Verifier    │ ← streams final output   │
│              │    Agent       │                          │
│              └────────────────┘                          │
└────────────────────────────────────────────────────────┘
```

### Agent Tiers

| Tier | Agents | Roles |
|------|--------|-------|
| **Minimum** | 2 | Researcher, Planner |
| **Medium** | 4 | + Coder, Tester |
| **Full** | 8 | + Optimizer, Security, Integrator, QA |

---

## 🔐 Safety Levels

| Level | Behaviour |
|-------|-----------|
| **🔒 Read-Only** | Agents can only take screenshots, OCR, read files, list directories |
| **⚠️ Confirmed** | Write/execute tools show a GUI confirmation dialog — you approve each one |
| **🔓 Full Auto** | No confirmation — agents execute all tools freely (**dangerous!**) |

The confirmation dialog lets you **Allow**, **Deny**, or **Deny & Lock Read-Only** (downgrades safety for the rest of the session).

---

## 📦 Setup

### 1. Clone

```bash
git clone https://github.com/HeavenFYouMissed/GrokHive-Autonomous.git
cd GrokHive-Autonomous
```

### 2. Create virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. (Optional) Install Tesseract OCR

For the `ocr_screenshot` tool, install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) and ensure it's in your PATH.

### 5. Run

```bash
python main.py
```

### 6. Configure

1. Paste your [xAI API key](https://console.x.ai/) in the sidebar
2. (Optional) Add a second key for rate-limit splitting
3. Choose model, tier, and safety level
4. Type your task and hit **🚀 Run Swarm**!

---

## 🔧 PC Automation Tools

All tools use proper OpenAI function-calling schemas so Grok can invoke them natively.

| Tool | Safety | Description |
|------|--------|-------------|
| `take_screenshot` | Read-Only | Capture the full screen |
| `ocr_screenshot` | Read-Only | Screenshot + Tesseract OCR |
| `read_file` | Read-Only | Read a local file |
| `list_directory` | Read-Only | List files in a directory |
| `get_clipboard` | Read-Only | Get clipboard text |
| `run_powershell` | Confirmed | Execute a PowerShell command |
| `write_file` | Confirmed | Write content to a file |
| `type_text` | Confirmed | Type text via keyboard simulation |
| `open_in_vscode` | Confirmed | Open file/folder in VS Code |
| `press_keys` | Confirmed | Press keyboard shortcuts |
| `click` | Confirmed | Click at screen coordinates |

---

## 📁 Project Structure

```
MiniGrokSwarm/
├── main.py              # Entry point
├── config.py            # Constants & configuration
├── requirements.txt     # pip dependencies
├── core/
│   ├── settings.py      # JSON settings persistence
│   ├── tools.py         # PC automation tools + safety system
│   └── swarm.py         # Grok API + parallel swarm engine
└── gui/
    ├── theme.py         # Dark OLED colour palette
    ├── widgets.py       # ActionButton, Tooltip, ConfirmDialog
    └── app.py           # Main GUI application
```

---

## 🛠️ Tech Stack

- **Python 3.12+** — pure stdlib networking (no `requests`)
- **CustomTkinter** — modern dark GUI
- **xAI Grok API** — OpenAI-compatible chat + function calling
- **pyautogui** — PC automation (screenshot, keyboard, mouse)
- **pytesseract + Pillow** — OCR
- **ThreadPoolExecutor** — true parallel agent execution

---

## 📄 License

MIT — do whatever you want with it.
