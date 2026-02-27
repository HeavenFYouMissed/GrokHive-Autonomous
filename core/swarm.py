"""
Grok Swarm Engine — Parallel agent orchestration via xAI's Grok API.

Architecture (inspired by kyegomez/swarms HeavySwarm):
  1. N specialised agents run in TRUE parallel (ThreadPoolExecutor)
  2. Each agent has its own role / system-prompt / tool access
  3. Agents may call PC tools → tool results feed back into conversation
  4. After all agents finish, a Verifier agent synthesises everything
  5. Verifier output streams token-by-token to the GUI

Uses pure urllib (no requests dependency) + OpenAI-compatible API.
"""
import concurrent.futures
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request

from config import GROK_API_URL, GROK_MODELS_URL, GROK_MODELS, AGENT_ROLES, DEFAULT_MODEL, OLLAMA_API_URL
from core.tools import TOOL_SCHEMAS, execute_tool

_SSL_CTX = ssl.create_default_context()

_HEADERS_BASE = {
    "Content-Type": "application/json",
    "User-Agent": "MiniGrokSwarm/1.0",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOW-LEVEL API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _call_grok(messages, model, api_key, tools=None,
               stream=False, on_token=None):
    """Call the Grok API (OpenAI-compatible).

    Returns dict:
      success + reply   → normal text response
      success + tool_calls → agent wants to execute tools
      success=False + error → something broke
    """
    headers = {**_HEADERS_BASE, "Authorization": f"Bearer {api_key}"}

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        GROK_API_URL, data=data, headers=headers, method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, context=_SSL_CTX, timeout=180)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:500]
        return {"success": False, "error": f"HTTP {e.code}: {body}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    # ── Streaming response ──────────────────────────────────
    if stream and on_token:
        full_text: list[str] = []
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            payload_str = line[6:]
            if payload_str == "[DONE]":
                break
            try:
                chunk = json.loads(payload_str)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    on_token(content)
                    full_text.append(content)
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
        resp.close()
        return {"success": True, "reply": "".join(full_text)}

    # ── Non-streaming response ──────────────────────────────
    body = resp.read().decode("utf-8")
    resp.close()
    try:
        data = json.loads(body)
        message = data["choices"][0]["message"]
        if message.get("tool_calls"):
            return {
                "success": True,
                "tool_calls": message["tool_calls"],
                "content": message.get("content", ""),
            }
        return {"success": True, "reply": message.get("content", "")}
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        return {"success": False, "error": f"Parse error: {e}\n{body[:500]}"}


def _call_ollama(messages, model, base_url=None,
                 stream=False, on_token=None):
    """Call local Ollama model (used for uncensored verifier).

    Ollama API: POST {base_url}/api/chat
    """
    base_url = (base_url or OLLAMA_API_URL).rstrip("/")
    url = f"{base_url}/api/chat"

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=300)
    except Exception as e:
        return {"success": False, "error": f"Ollama error: {e}"}

    if stream and on_token:
        full_text: list[str] = []
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content", "")
                if content:
                    on_token(content)
                    full_text.append(content)
                if chunk.get("done"):
                    break
            except json.JSONDecodeError:
                continue
        resp.close()
        return {"success": True, "reply": "".join(full_text)}

    # Non-streaming
    body = resp.read().decode("utf-8")
    resp.close()
    try:
        data = json.loads(body)
        content = data.get("message", {}).get("content", "")
        return {"success": True, "reply": content}
    except (json.JSONDecodeError, KeyError) as e:
        return {"success": False, "error": f"Ollama parse error: {e}"}


def list_grok_models(api_key: str) -> list[str]:
    """Fetch available models from the xAI API (fallback to static list)."""
    try:
        req = urllib.request.Request(
            GROK_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}",
                     "User-Agent": "MiniGrokSwarm/1.0"},
        )
        resp = urllib.request.urlopen(req, context=_SSL_CTX, timeout=10)
        data = json.loads(resp.read().decode())
        resp.close()
        models = [m["id"] for m in data.get("data", [])]
        return sorted(models) if models else list(GROK_MODELS)
    except Exception:
        return list(GROK_MODELS)


def test_connection(api_key: str) -> tuple[bool, str]:
    """Quick connectivity test. Returns (ok, message)."""
    if not api_key:
        return False, "No API key"
    try:
        models = list_grok_models(api_key)
        return True, f"{len(models)} models available"
    except Exception as e:
        return False, str(e)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SINGLE AGENT WITH TOOL LOOP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _run_agent(role_name, role_focus, task, context,
               model, api_key, tools, on_status=None,
               max_tool_rounds=20):
    """Run one agent with an iterative tool-calling loop.

    The agent can call tools up to *max_tool_rounds* times.
    Each tool result is fed back so the agent can continue reasoning.
    """
    system_prompt = (
        f"You are a Grok Swarm Agent — role: {role_name}\n"
        f"Specialty: {role_focus}\n\n"
        "You have FULL PC automation — you control this Windows computer like a human.\n\n"
        "BROWSER WORKFLOW — NAVIGATION (use OCR to see where to click):\n"
        "1. open_url('https://www.google.com/search?q=your+search+query') — opens Edge\n"
        "2. wait(3) — let the page load\n"
        "3. ocr_screenshot() — read the screen to see links/buttons/layout\n"
        "4. click(x, y) — click search results, links, buttons\n"
        "5. scroll('down', 5) — scroll to see more content\n\n"
        "RAW DATA EXTRACTION (use clipboard — NOT OCR — for actual data):\n"
        "1. Once on a good page with useful content:\n"
        "2. press_keys('ctrl,a') — select ALL text on the page\n"
        "3. press_keys('ctrl,c') — copy it\n"
        "4. get_clipboard() — retrieve the raw text\n"
        "5. append_file(path, raw_text) — dump it into the data file VERBATIM\n"
        "6. close_browser_tab() — close the tab, move to next page\n"
        "7. Repeat for every useful page you find\n\n"
        "DATA RULES:\n"
        "• NEVER summarise, rewrite, or paraphrase scraped content\n"
        "• Paste the EXACT raw text from the clipboard into the file\n"
        "• Add a header line before each dump: \n"
        "  ═══ SOURCE: <url or page title> ═══\n"
        "• Use append_file() to keep adding to ONE file (not write_file which overwrites)\n"
        "• Use ocr_screenshot() ONLY for navigation (finding where to click)\n"
        "• Use get_clipboard() for actual data extraction (much higher quality than OCR)\n\n"
        "IMPORTANT:\n"
        "• You ARE the mouse and keyboard — navigate exactly like a person would\n"
        "• After opening a URL, ALWAYS wait() then ocr_screenshot() to see the page\n"
        "• Use screenshot coordinates to know WHERE to click\n"
        "• Be thorough — visit multiple pages, scroll, grab everything useful\n"
        "• ALWAYS close_browser_tab() after extracting data from a page\n"
        "• NEVER visit guidedhacking.com (owner's paid subscription site)\n"
    )

    messages = [{"role": "system", "content": system_prompt}]

    if context:
        messages.append({
            "role": "system",
            "content": f"Attached context files:\n\n{context}",
        })

    messages.append({"role": "user", "content": task})

    for _round in range(max_tool_rounds):
        result = _call_grok(messages, model, api_key, tools=tools)

        if not result["success"]:
            return f"[{role_name} ERROR] {result['error']}"

        # ── Agent wants to use tools ────────────────────────
        if "tool_calls" in result:
            # Add the assistant message (with tool_calls) to history
            assistant_msg = {
                "role": "assistant",
                "content": result.get("content") or None,
                "tool_calls": result["tool_calls"],
            }
            messages.append(assistant_msg)

            # Execute each tool call
            for tc in result["tool_calls"]:
                func_name = tc["function"]["name"]
                try:
                    func_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    func_args = {}

                if on_status:
                    on_status(f"🔧 Using: {func_name}")

                tool_result = execute_tool(func_name, func_args, agent_role=role_name)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(tool_result, default=str),
                })

            continue  # next round — Grok processes tool results

        # ── Normal text response — agent is done ────────────
        return result.get("reply", "")

    # Exhausted tool rounds
    return result.get("reply", result.get("content", "[Max tool rounds]"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SWARM ORCHESTRATOR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class MiniGrokSwarm:
    """Tiered parallel Grok agent swarm with PC automation tools.

    Inspired by kyegomez/swarms HeavySwarm architecture:
      • Specialised agents run concurrently (ThreadPoolExecutor)
      • Each agent may call local PC tools (screenshot, OCR, PowerShell…)
      • A Verifier agent synthesises all outputs into a final answer
      • Dual API-key support distributes rate-limit pressure

    Callbacks (all optional, called from background threads):
      on_agent_status(role, status_str) — progress updates
      on_agent_done(role, output_str)   — agent finished
      on_verifier_token(token_str)      — streaming verifier output
    """

    def __init__(self, api_keys: list[str] | None = None,
                 model=DEFAULT_MODEL, tier="medium",
                 max_tool_rounds=15, timeout=180,
                 verifier_backend="ollama",
                 ollama_model="huihui_ai/qwen3-abliterated:14b",
                 ollama_url=None):
        # Accept list of keys; filter out empty strings
        keys = [k for k in (api_keys or []) if k.strip()]
        if not keys:
            raise ValueError("At least one API key is required")
        self.api_keys = keys
        self.model = model
        self.tier = tier
        self.max_tool_rounds = max_tool_rounds
        self.timeout = timeout
        self.verifier_backend = verifier_backend
        self.ollama_model = ollama_model
        self.ollama_url = ollama_url or OLLAMA_API_URL
        self.roles = AGENT_ROLES.get(tier, AGENT_ROLES["medium"])
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self, task, context="",
            on_agent_status=None, on_agent_done=None,
            on_verifier_token=None,
            verifier_system=None):
        """Execute the full swarm pipeline.

        Args:
          verifier_system: Optional custom system prompt for the verifier.
                           If None, uses the default synthesis prompt.

        Returns dict with:
          success, final_output, agent_outputs, elapsed
        """
        self._cancelled = False
        t0 = time.time()
        tools = TOOL_SCHEMAS
        keys = self.api_keys
        agent_outputs: dict[str, str] = {}

        # ── Phase 1: Parallel agent execution ───────────────
        def _run_single(i, role_name, role_focus):
            if self._cancelled:
                return role_name, "[Cancelled]"

            key = keys[i % len(keys)]

            if on_agent_status:
                on_agent_status(role_name, "⏳ Working...")

            def _tool_status(msg):
                if on_agent_status:
                    on_agent_status(role_name, msg)

            try:
                output = _run_agent(
                    role_name=role_name,
                    role_focus=role_focus,
                    task=task,
                    context=context,
                    model=self.model,
                    api_key=key,
                    tools=tools,
                    on_status=_tool_status,
                    max_tool_rounds=self.max_tool_rounds,
                )
            except Exception as e:
                output = f"[{role_name} ERROR] {e}"

            if on_agent_status:
                on_agent_status(role_name, "✅ Done")
            if on_agent_done:
                on_agent_done(role_name, output)

            return role_name, output

        workers = max(len(self.roles), 2)
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers) as executor:
            futures = [
                executor.submit(_run_single, i, name, focus)
                for i, (name, focus) in enumerate(self.roles)
            ]
            for future in concurrent.futures.as_completed(futures):
                if self._cancelled:
                    break
                try:
                    name, output = future.result(timeout=300)
                    agent_outputs[name] = output
                except Exception as e:
                    pass   # individual agent failure ≠ swarm failure

        if self._cancelled:
            return {"success": False, "error": "Cancelled",
                    "agent_outputs": agent_outputs,
                    "elapsed": time.time() - t0}

        # ── Phase 2: Verifier synthesis (streaming) ─────────
        if on_agent_status:
            on_agent_status("✅ Verifier", "⏳ Synthesising...")

        merged = "\n\n".join(
            f"──── {role} ────\n{out}"
            for role, out in agent_outputs.items()
        )

        default_verifier = (
            "You are the Verifier Agent — the final authority.\n\n"
            "You receive outputs from multiple specialist agents "
            "that all worked on the same task in parallel.\n\n"
            "Your job:\n"
            "1. Cross-check all outputs for accuracy & consistency\n"
            "2. Merge the best parts into one coherent, actionable response\n"
            "3. Flag any contradictions or errors\n"
            "4. Produce a polished final output that fully addresses "
            "the original task\n\n"
            "Quality over quantity. Be thorough but concise."
        )

        verifier_messages = [
            {
                "role": "system",
                "content": verifier_system or default_verifier,
            },
            {
                "role": "user",
                "content": (
                    f"ORIGINAL TASK:\n{task}\n\n"
                    f"AGENT OUTPUTS ({len(agent_outputs)} agents):\n\n"
                    f"{merged}"
                ),
            },
        ]

        # Route to Ollama (local uncensored) or Grok (API)
        if self.verifier_backend == "ollama":
            result = _call_ollama(
                verifier_messages, self.ollama_model,
                self.ollama_url,
                stream=True, on_token=on_verifier_token,
            )
        else:
            result = _call_grok(
                verifier_messages, self.model, self.api_keys[0],
                stream=True, on_token=on_verifier_token,
            )

        elapsed = time.time() - t0

        if on_agent_status:
            on_agent_status("✅ Verifier", "✅ Done")

        if result["success"]:
            return {
                "success": True,
                "final_output": result["reply"],
                "agent_outputs": agent_outputs,
                "elapsed": elapsed,
            }
        return {
            "success": False,
            "error": result.get("error", "Verifier failed"),
            "agent_outputs": agent_outputs,
            "elapsed": elapsed,
        }

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # RESEARCH LOOP — autonomous overnight research
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def run_research_loop(self, topic, output_dir,
                          max_rounds=20, on_round=None,
                          on_agent_status=None, on_agent_done=None,
                          on_verifier_token=None):
        """Run continuous autonomous research on a topic.

        Uses a SINGLE scraper agent per round (no parallel agents)
        to avoid multiple agents fighting over one browser/keyboard.

        Each round:
          1. One scraper agent opens browser, grabs raw page data
          2. Lightweight verifier catalogs what was collected
          3. NEXT topics extracted for the following round

        Files saved to output_dir:
          raw_data_round_01.txt, raw_data_round_02.txt, ... (actual page text)
          round_01_<subtopic>.md, round_02_<subtopic>.md, ... (catalog)
          research_index.md — master index

        Returns dict with total_rounds, files_created, elapsed.
        """
        self._cancelled = False
        os.makedirs(output_dir, exist_ok=True)
        t0 = time.time()
        files_created = []
        current_task = topic
        all_summaries = []
        tools = TOOL_SCHEMAS

        for round_num in range(1, max_rounds + 1):
            if self._cancelled:
                break

            if on_round:
                on_round(round_num, max_rounds, current_task)

            # ── Single scraper agent (no parallel contention) ───
            raw_file = os.path.join(
                output_dir,
                f"raw_data_round_{round_num:02d}.txt",
            )

            scraper_task = (
                f"RESEARCH ROUND {round_num}/{max_rounds}\n"
                f"MAIN TOPIC: {topic}\n"
                f"CURRENT SUB-TASK: {current_task}\n\n"
                "YOUR MISSION — RAW DATA COLLECTION:\n"
                "You are the ONLY agent. You have full control of the browser.\n\n"
                "STEP-BY-STEP WORKFLOW (follow this exactly):\n"
                "1. open_url('https://www.google.com/search?q=<your search query>')\n"
                "2. wait(3)\n"
                "3. ocr_screenshot() — read the search results to find good links\n"
                "4. click(x, y) — click a promising search result\n"
                "5. wait(3)\n"
                "6. press_keys('ctrl,a') — select ALL text on the page\n"
                "7. press_keys('ctrl,c') — copy it\n"
                "8. get_clipboard() — retrieve the raw text\n"
                "9. append_file(path, '═══ SOURCE: <url> ═══\\n' + raw_text + '\\n\\n')\n"
                "10. close_browser_tab() — close this tab\n"
                "11. REPEAT steps 4-10 for the next search result (visit 3-5 total pages)\n\n"
                "CRITICAL RULES:\n"
                "• Use append_file() — NOT write_file() — so you build up one file\n"
                "• Paste the EXACT clipboard text — NEVER summarise or rewrite\n"
                "• Use ocr_screenshot() ONLY for navigation (seeing links/buttons)\n"
                "• Use get_clipboard() for data extraction (much better than OCR)\n"
                "• ALWAYS close_browser_tab() after extracting each page\n"
                "• NEVER visit guidedhacking.com\n\n"
                f"APPEND ALL RAW DATA TO: {raw_file}\n\n"
                "After visiting all pages, end with a brief list of what you collected\n"
                "and suggest follow-up topics:\n"
                "NEXT: <follow-up topic 1>\n"
                "NEXT: <follow-up topic 2>\n"
                "NEXT: <follow-up topic 3>\n"
            )

            if on_agent_status:
                on_agent_status("🔍 Scraper", "⏳ Browsing...")

            def _scraper_status(msg):
                if on_agent_status:
                    on_agent_status("🔍 Scraper", msg)

            key = self.api_keys[round_num % len(self.api_keys)]

            try:
                scraper_output = _run_agent(
                    role_name="🔍 Scraper",
                    role_focus="Raw data collection — browse, copy, save verbatim",
                    task=scraper_task,
                    context="",
                    model=self.model,
                    api_key=key,
                    tools=tools,
                    on_status=_scraper_status,
                    max_tool_rounds=25,
                )
            except Exception as e:
                scraper_output = f"[Scraper ERROR] {e}"

            if on_agent_status:
                on_agent_status("🔍 Scraper", "✅ Done")
            if on_agent_done:
                on_agent_done("🔍 Scraper", scraper_output)

            if self._cancelled:
                break

            # ── Lightweight verifier pass (catalog only, no browser) ──
            if on_agent_status:
                on_agent_status("✅ Verifier", "⏳ Cataloging...")

            # Check what was actually saved
            raw_size = 0
            if os.path.exists(raw_file):
                raw_size = os.path.getsize(raw_file)

            verifier_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the Research Catalog Agent. Respond ONLY in English.\n\n"
                        "A scraper agent just browsed the web and saved raw page text.\n"
                        "Your ONLY job is to produce a brief catalog:\n\n"
                        "1. List the URLs / sources that were scraped\n"
                        "2. One line per source: what kind of content (paper, repo, forum, etc.)\n"
                        "3. Note the raw data file path and size\n"
                        "4. Flag if scraping failed or data is empty\n\n"
                        "DO NOT rewrite or summarise the raw data. It's already saved.\n\n"
                        "End with 1-3 follow-up topics:\n"
                        "NEXT: <topic>\n"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"TOPIC: {current_task}\n\n"
                        f"SCRAPER REPORT:\n{scraper_output}\n\n"
                        f"RAW DATA FILE: {raw_file} ({raw_size:,} bytes)\n"
                    ),
                },
            ]

            if self.verifier_backend == "ollama":
                result = _call_ollama(
                    verifier_messages, self.ollama_model,
                    self.ollama_url,
                    stream=True, on_token=on_verifier_token,
                )
            else:
                result = _call_grok(
                    verifier_messages, self.model, self.api_keys[0],
                    stream=True, on_token=on_verifier_token,
                )

            if on_agent_status:
                on_agent_status("✅ Verifier", "✅ Done")

            output_text = result.get("reply", "") if result["success"] else scraper_output
            # Strip leaked chain-of-thought tags
            output_text = re.sub(r'</?think>', '', output_text).strip()

            # Save round catalog
            safe_name = re.sub(r'[^\w\s-]', '', current_task)[:50].strip()
            safe_name = re.sub(r'\s+', '_', safe_name)
            filename = f"round_{round_num:02d}_{safe_name}.md"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# Research Round {round_num}: {current_task}\n\n")
                f.write(output_text)
            files_created.append(filepath)

            # Count the raw data file too
            if os.path.exists(raw_file) and raw_size > 0:
                files_created.append(raw_file)

            all_summaries.append(
                f"## Round {round_num}: {current_task}\n\n"
                f"Raw data: {raw_size:,} bytes\n"
                f"{output_text[:500]}...\n"
            )

            # Extract next sub-topic
            next_topics = re.findall(
                r'NEXT:\s*(.+)', output_text, re.IGNORECASE)
            if next_topics:
                current_task = next_topics[0].strip()
            else:
                current_task = f"{topic} — deeper dive round {round_num + 1}"

            # Reset verifier token flag for next round
            self._first_verifier_token_flag = True

        # Write master index
        index_path = os.path.join(output_dir, "research_index.md")
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(f"# Research Index: {topic}\n\n")
            f.write(f"Total rounds: {len(files_created)}\n")
            f.write(f"Elapsed: {time.time() - t0:.0f}s\n\n")
            for fp in files_created:
                name = os.path.basename(fp)
                f.write(f"- [{name}]({name})\n")
            f.write("\n\n---\n\n")
            f.write("\n".join(all_summaries))
        files_created.append(index_path)

        return {
            "success": not self._cancelled,
            "total_rounds": len([f for f in files_created
                                 if os.path.basename(f).startswith("round_")]),
            "files_created": files_created,
            "elapsed": time.time() - t0,
        }
