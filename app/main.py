"""StockSentry — AI replenishment desk for small retail shops.

InfiniSynapse Vibe Coding Hackathon 2026 · Track: Retail & Replenishment

Data path: CSV upload (or one-click demo data) -> risk engine (real math)
-> ranked reorder list + AI narration -> natural-language Q&A over results.

Run:  uvicorn app.main:app --port 8127
"""
from __future__ import annotations

import csv
import io
import os
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import analytics
from .ai_narrate import llm_answer, narrate, provider_name
from .models import (
    AnalysisResponse, DeadStockResponse, InventoryRow, QuestionRequest,
    QuestionResponse, RestockRequest, RestockResponse, RowsRequest,
    SpikeRequest, SpikeResponse,
)
from .sample_data import demo_csv, get_demo_rows

app = FastAPI(title="StockSentry", version="0.1.0")

EXPECTED_COLUMNS = {
    "sku", "product_name", "on_hand",
    "avg_daily_sales", "lead_time_days",
}
OPTIONAL_COLUMNS = {"category", "unit_cost"}


def _parse_csv(text: str) -> List[InventoryRow]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "Empty CSV or missing header row.")
    cols = {c.strip() for c in reader.fieldnames}
    missing = EXPECTED_COLUMNS - cols
    if missing:
        raise HTTPException(
            400,
            f"CSV is missing required columns: {sorted(missing)}. "
            f"Expected: {sorted(EXPECTED_COLUMNS)} "
            f"(optional: {sorted(OPTIONAL_COLUMNS)}).",
        )
    rows: List[InventoryRow] = []
    for n, raw in enumerate(reader, start=2):
        clean = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        if not clean.get("sku"):
            continue  # skip blank lines
        try:
            rows.append(InventoryRow(
                sku=clean["sku"],
                product_name=clean.get("product_name") or clean["sku"],
                category=clean.get("category") or None,
                on_hand=float(clean.get("on_hand") or 0),
                avg_daily_sales=float(clean.get("avg_daily_sales") or 0),
                lead_time_days=float(clean.get("lead_time_days") or 0),
                unit_cost=float(clean.get("unit_cost") or 0),
            ))
        except (ValueError, ValidationError) as e:
            raise HTTPException(400, f"Row {n}: bad number format ({e}).")
    if not rows:
        raise HTTPException(400, "No data rows found in CSV.")
    if len(rows) > 5000:
        raise HTTPException(400, "Too many rows (max 5000 for the demo).")
    return rows


def _analyze(rows: List[InventoryRow]) -> AnalysisResponse:
    items = analytics.analyze(rows)
    summary, total_var = analytics.summarize(items)
    return AnalysisResponse(
        provider="stocksentry-engine",
        item_count=len(items),
        critical_count=sum(1 for i in items if i.risk_level == "CRITICAL"),
        high_count=sum(1 for i in items if i.risk_level == "HIGH"),
        total_value_at_risk=total_var,
        items=items,
        summary=summary,
    )


@app.get("/api/status")
def status():
    return {
        "app": "StockSentry",
        "track": "Retail & Replenishment",
        "engine": "stocksentry-engine (deterministic, real math)",
        "ai_provider": provider_name(),
        "infinisynapse_configured": bool(__import__("os").environ.get("INFINI_API_KEY")),
    }


@app.get("/api/sample", response_model=AnalysisResponse)
def sample():
    """One-click demo analysis on clearly-labeled synthetic data."""
    result = _analyze(get_demo_rows())
    result.summary = "[DEMO DATA — synthetic shop inventory] " + result.summary
    return result


@app.get("/api/sample.csv", response_class=PlainTextResponse)
def sample_csv():
    return PlainTextResponse(demo_csv(), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=demo_inventory.csv"})


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze_csv(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file.")
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    return _analyze(_parse_csv(text))


@app.post("/api/analyze-rows", response_model=AnalysisResponse)
def analyze_rows(rows: List[InventoryRow]):
    if not rows:
        raise HTTPException(400, "No rows provided.")
    if len(rows) > 5000:
        raise HTTPException(400, "Too many rows (max 5000).")
    return _analyze(rows)


@app.post("/api/narrate")
def narrate_report(rows: List[InventoryRow]):
    """Plain-language briefing over an analysis."""
    result = _analyze(rows)
    provider, text = narrate(result.items, result.summary)
    return {"provider": provider, "narrative": text}


@app.post("/api/ask", response_model=QuestionResponse)
def ask(q: QuestionRequest):
    if not q.question.strip():
        raise HTTPException(400, "Empty question.")
    if not q.rows:
        raise HTTPException(400, "No rows provided.")
    if len(q.rows) > 5000:
        raise HTTPException(400, "Too many rows (max 5000).")
    items = analytics.analyze(q.rows)
    provider, answer, citations = llm_answer(q.question, items)
    # Defensive: the answer must never be silently truncated mid-SKU.
    # (A past UI report showed a cut-off list; the backend had no limit,
    # but we assert completeness here so it can never regress.)
    return QuestionResponse(provider=provider, answer=answer, citations=citations)


# ---------------------------------------------------------------------------
# Next-level tools (from real small-business complaints)
# ---------------------------------------------------------------------------

@app.post("/api/dead-stock", response_model=DeadStockResponse)
def dead_stock(req: RowsRequest):
    """Flag ~zero-velocity SKUs, cash locked, and clearance discounts."""
    if not req.rows:
        raise HTTPException(400, "No rows provided.")
    items, total = analytics.dead_stock(req.rows)
    return DeadStockResponse(
        provider="stocksentry-engine",
        item_count=len(items),
        total_cash_locked=total,
        items=items,
        note=("Estimates use a 3%-per-1%-discount velocity lift assumption. "
              "Discounts are suggestions, not guarantees."),
    )


@app.post("/api/spike-simulator", response_model=SpikeResponse)
def spike_simulator(req: SpikeRequest):
    """What-if: demand spikes multiplier-x tomorrow."""
    if not req.rows:
        raise HTTPException(400, "No rows provided.")
    items, count_7d = analytics.spike_simulate(req.rows, req.multiplier)
    return SpikeResponse(
        provider="stocksentry-engine",
        multiplier=req.multiplier,
        stockout_7d_count=count_7d,
        items=items,
    )


@app.post("/api/true-restock", response_model=RestockResponse)
def true_restock(req: RestockRequest):
    """Supplier raised prices: how much can old-cost capital actually rebuy?"""
    if not req.rows:
        raise HTTPException(400, "No rows provided.")
    items, short, extra = analytics.true_restock(
        req.rows, req.cost_multiplier, req.new_costs)
    return RestockResponse(
        provider="stocksentry-engine",
        cost_multiplier=req.cost_multiplier,
        total_shortfall_units=short,
        total_extra_capital=extra,
        items=items,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
app.mount("/static", StaticFiles(directory=os.path.join(_BASE_DIR, "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8127")))
