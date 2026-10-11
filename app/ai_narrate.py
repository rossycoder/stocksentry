"""AI narration layer for StockSentry.

Three providers, always labeled honestly in every response:

1. "infinisynapse" — calls the InfiniSynapse Server API
   (https://app.infinisynapse.com, SSE + message dispatch per the official
   Vibe Coding Guide) when INFINI_API_KEY is set. Used for richer
   plain-language narratives and Q&A.
2. "groq:..." / "gemini:..." — free-tier LLM (no credit card) via
   app/free_llm.py when GROQ_API_KEY or GEMINI_API_KEY is set.
   Used when no InfiniSynapse key is configured.
3. "heuristic" — offline deterministic templates. Used when no API key is
   configured, or when every API call fails. Every heuristic answer says
   which template/rule produced it.

Nothing is ever presented as AI output when it is not.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from typing import List

import urllib.request
import urllib.error

from . import free_llm
from .models import RiskItem

INFINI_BASE = os.environ.get("INFINI_BASE_URL", "https://app.infinisynapse.com")
INFINI_KEY = os.environ.get("INFINI_API_KEY", "")


def provider_name() -> str:
    if INFINI_KEY:
        return "infinisynapse"
    return free_llm.available_provider() or "heuristic"


# ---------------------------------------------------------------------------
# InfiniSynapse Server API client (per official Vibe Coding Guide)
# ---------------------------------------------------------------------------

def _infini_post(path: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        INFINI_BASE + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {INFINI_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        raise RuntimeError(f"InfiniSynapse API HTTP {e.code}: {body}")
    except Exception as e:  # network etc.
        raise RuntimeError(f"InfiniSynapse API unreachable: {e}")


def infini_narrate(items: List[RiskItem], summary: str) -> str:
    """Ask InfiniSynapse to narrate the stockout report in plain language."""
    if not INFINI_KEY:
        raise RuntimeError("INFINI_API_KEY not configured")

    top = [
        {
            "sku": i.sku, "name": i.product_name,
            "risk": i.risk_level, "days_left": i.days_of_stock,
            "suggested_order": i.suggested_order_qty,
        }
        for i in items[:8]
    ]
    prompt = (
        "You are a retail operations advisor. Here is a stockout-risk analysis "
        f"of a small shop's inventory. Summary: {summary}\n"
        f"Top at-risk items (JSON): {json.dumps(top)}\n"
        "Write a short, plain-language briefing for the shop owner: "
        "1) the 3 most urgent actions, 2) one sentence on why each matters, "
        "3) one tip to avoid this next month. Keep it under 150 words. "
        "Do not invent numbers — only use the figures given."
    )
    conn_id = str(uuid.uuid4())
    data = _infini_post("/api/ai/message", {
        "type": "newTask",
        "text": prompt,
        "connId": conn_id,
        "chatSettings": {"mode": "act"},
    })
    # The task runs async; poll the task status endpoint for completion.
    task_id = (data.get("data") or {}).get("taskId") or data.get("taskId")
    if not task_id:
        raise RuntimeError(f"InfiniSynapse did not return a taskId: {str(data)[:300]}")

    import time
    req = urllib.request.Request(
        f"{INFINI_BASE}/api/ai_task/tasks?taskId={task_id}",
        headers={"Authorization": f"Bearer {INFINI_KEY}"},
    )
    for _ in range(30):  # up to ~60s
        time.sleep(2)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                t = json.loads(resp.read().decode())
        except Exception:
            continue
        node = (t.get("data") or t)
        status = str(node.get("status", "")).lower()
        text = node.get("result") or node.get("answer") or node.get("text") or ""
        if status in ("completed", "success", "done") and text:
            return str(text).strip()
        if status in ("failed", "error"):
            raise RuntimeError(f"InfiniSynapse task failed: {str(node)[:300]}")
    raise RuntimeError("InfiniSynapse task timed out waiting for completion")


# ---------------------------------------------------------------------------
# Heuristic fallback (offline, deterministic, labeled)
# ---------------------------------------------------------------------------

def heuristic_narrate(items: List[RiskItem], summary: str) -> str:
    crit = [i for i in items if i.risk_level == "CRITICAL"][:3]
    lines = [summary, ""]
    if crit:
        lines.append("Most urgent actions (rule: lowest days-of-stock first):")
        for i in crit:
            lines.append(
                f"- Reorder {i.product_name} ({i.sku}): "
                f"{i.days_of_stock} days left, suggested order {i.suggested_order_qty:.0f} units."
            )
        lines.append(
            "Tip: set reorder alerts at 1.5x lead time so critical items never surprise you."
        )
    else:
        lines.append("No critical items. Review HIGH-risk SKUs in the table above.")
    lines.append("")
    lines.append("[Generated by StockSentry heuristic narrator — offline rules, not an LLM.]")
    return "\n".join(lines)


def free_llm_narrate(items: List[RiskItem], summary: str) -> tuple[str, str]:
    """Narrate via Groq/Gemini free tier. Returns (provider_label, narrative).

    Raises RuntimeError when no key is configured or the call fails.
    """
    if not free_llm.available_provider():
        raise RuntimeError("no free-LLM key configured (set GROQ_API_KEY or GEMINI_API_KEY)")
    top = [
        {"sku": i.sku, "name": i.product_name, "risk": i.risk_level,
         "days_left": i.days_of_stock, "suggested_order": round(i.suggested_order_qty)}
        for i in items[:8]
    ]
    system = ("You are a retail operations advisor. Write a short, plain-language briefing "
              "for a small shop owner. Do not invent numbers — only use the figures given. "
              "Keep it under 150 words.")
    user = (f"Stockout-risk analysis summary: {summary}\n"
            f"Top at-risk items (JSON): {json.dumps(top)}\n"
            "Give: 1) the 3 most urgent actions, 2) one sentence on why each matters, "
            "3) one tip to avoid this next month.")
    text, label = free_llm.chat(system, user, max_tokens=400, temperature=0.6)
    if text is None:
        raise RuntimeError(label)
    return label, text


def narrate(items: List[RiskItem], summary: str) -> tuple[str, str]:
    """Return (provider, narrative).

    Tries InfiniSynapse, then free-tier LLM, then falls back honestly
    to the offline heuristic. The provider label always says what ran.
    """
    if INFINI_KEY:
        try:
            return "infinisynapse", infini_narrate(items, summary)
        except Exception as e:
            note = f"[InfiniSynapse call failed ({e}); trying free LLM.]\n\n"
            try:
                label, text = free_llm_narrate(items, summary)
                return label, note + text
            except Exception as e2:
                return "heuristic", note + f"[Free LLM also failed ({e2}); used offline heuristic.]\n\n" + heuristic_narrate(items, summary)
    if free_llm.available_provider():
        try:
            label, text = free_llm_narrate(items, summary)
            return label, text
        except Exception as e:
            note = f"[Free-LLM call failed ({e}); used offline heuristic instead.]\n\n"
            return "heuristic", note + heuristic_narrate(items, summary)
    return "heuristic", heuristic_narrate(items, summary)


# ---------------------------------------------------------------------------
# Heuristic Q&A over the analysis (offline)
# ---------------------------------------------------------------------------

# (Heuristic Q&A uses direct regex matching inside heuristic_answer below.)


def heuristic_answer(question: str, items: List[RiskItem]) -> tuple[str, List[str]]:
    q = question.strip()
    by_sku = {i.sku.lower(): i for i in items}

    m = re.search(r"\b(sku|product)\s+([A-Za-z0-9\-_]+)", q, re.I)
    if m:
        sku = m.group(2).lower()
        item = by_sku.get(sku)
        if item:
            return (
                f"{item.product_name} ({item.sku}): {item.risk_level} risk, "
                f"{item.days_of_stock} days of stock, reorder point {item.reorder_point}, "
                f"suggested order {item.suggested_order_qty:.0f} units. {item.reason} "
                f"[rule: direct SKU lookup]",
                [item.sku],
            )
        return (
            f"SKU '{m.group(2)}' was not found in the uploaded data. "
            f"[rule: direct SKU lookup]",
            [],
        )

    crit = [i for i in items if i.risk_level == "CRITICAL"]
    if re.search(r"which.*(critical|urgent|stock ?out)", q, re.I) or re.search(
        r"how many.*critical", q, re.I
    ):
        if not crit:
            return ("No CRITICAL-risk SKUs in this data. [rule: risk filter]", [])
        names = ", ".join(f"{i.sku} ({i.days_of_stock}d)" for i in crit)
        return (
            f"{len(crit)} critical SKU(s): {names}. [rule: risk filter, sorted by days of stock]",
            [i.sku for i in crit],
        )

    if re.search(r"reorder.*first|what.*order first|priority", q, re.I):
        top = items[:3]
        names = ", ".join(
            f"{i.sku} (order {i.suggested_order_qty:.0f})" for i in top
        )
        return (
            f"Reorder priority (highest risk first): {names}. [rule: risk ranking]",
            [i.sku for i in top],
        )

    if re.search(r"total.*value|inventory.*worth|value at risk", q, re.I):
        total = sum(i.value_at_risk for i in items)
        return (
            f"Total inventory value on hand: ${total:,.2f} "
            f"(sum of on_hand × unit_cost across {len(items)} SKUs). [rule: aggregation]",
            [],
        )

    if re.search(r"which.*(low|healthy|ok|fine)", q, re.I):
        ok = [i for i in items if i.risk_level in ("OK", "LOW")][:5]
        names = ", ".join(i.sku for i in ok) if ok else "none"
        return (
            f"Healthy/low-risk SKUs: {names}. [rule: risk filter]",
            [i.sku for i in ok],
        )

    return (
        "I can answer from this data: which SKUs are critical, reorder priority, "
        "total inventory value, healthy SKUs, or details for a specific SKU "
        '(e.g. "tell me about SKU ABC-123"). [rule: fallback]',
        [],
    )
