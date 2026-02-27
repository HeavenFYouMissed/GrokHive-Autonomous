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
import ssl
import time
import urllib.error
import urllib.request

from config import GROK_API_URL, GROK_MODELS_URL, GROK_MODELS, AGENT_ROLES, DEFAULT_MODEL
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
               max_tool_rounds=5):
    """Run one agent with an iterative tool-calling loop.

    The agent can call tools up to *max_tool_rounds* times.
    Each tool result is fed back so the agent can continue reasoning.
    """
    system_prompt = (
        f"You are a Grok Swarm Agent — role: {role_name}\n"
        f"Specialty: {role_focus}\n\n"
        "You have access to PC automation tools (listed below). "
        "Use them ONLY when the task genuinely requires it. "
        "Be thorough, precise, and produce actionable output.\n"
        "If you use a tool, briefly explain what you did and why."
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

                tool_result = execute_tool(func_name, func_args)

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
                 max_tool_rounds=5, timeout=180):
        # Accept list of keys; filter out empty strings
        keys = [k for k in (api_keys or []) if k.strip()]
        if not keys:
            raise ValueError("At least one API key is required")
        self.api_keys = keys
        self.model = model
        self.tier = tier
        self.max_tool_rounds = max_tool_rounds
        self.timeout = timeout
        self.roles = AGENT_ROLES.get(tier, AGENT_ROLES["medium"])
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self, task, context="",
            on_agent_status=None, on_agent_done=None,
            on_verifier_token=None):
        """Execute the full swarm pipeline.

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

        verifier_messages = [
            {
                "role": "system",
                "content": (
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
                ),
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
