"""StockSentry — AI replenishment desk for small retail shops.

InfiniSynapse Vibe Coding Hackathon 2026 · Track: Retail & Replenishment

Data path: CSV upload (or one-click demo data) -> risk engine (real math)
-> ranked reorder list + AI narration -> natural-language Q&A over results.

Run:  uvicorn app.main:app --port 8127
"""
from __future__ import annotations

import csv
import io
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import analytics
from .ai_narrate import heuristic_answer, narrate, provider_name
from .models import AnalysisResponse, InventoryRow, QuestionRequest, QuestionResponse
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
    items = analytics.analyze(q.rows)
    answer, citations = heuristic_answer(q.question, items)
    return QuestionResponse(
        provider="heuristic-qa",
        answer=answer,
        citations=citations,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


app.mount("/static", StaticFiles(directory="static"), name="static")
