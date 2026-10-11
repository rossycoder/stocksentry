"""Pydantic models for StockSentry API."""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class InventoryRow(BaseModel):
    sku: str = Field(..., description="Product SKU / item code")
    product_name: str = Field(..., description="Human-readable product name")
    on_hand: float = Field(..., ge=0, description="Units currently in stock")
    avg_daily_sales: float = Field(..., ge=0, description="Average units sold per day")
    lead_time_days: float = Field(..., ge=0, description="Supplier lead time in days")
    unit_cost: float = Field(default=0.0, ge=0, description="Cost per unit (for value-at-risk)")
    category: Optional[str] = Field(default=None, description="Product category")


class RiskItem(BaseModel):
    sku: str
    product_name: str
    category: Optional[str]
    on_hand: float
    avg_daily_sales: float
    lead_time_days: float
    days_of_stock: Optional[float]
    reorder_point: float
    risk_level: str  # CRITICAL | HIGH | MEDIUM | LOW | OK
    risk_score: float  # 0-100
    suggested_order_qty: float
    value_at_risk: float
    reason: str


class AnalysisResponse(BaseModel):
    provider: str  # "stocksentry-engine" (always real math, never fake)
    item_count: int
    critical_count: int
    high_count: int
    total_value_at_risk: float
    items: List[RiskItem]
    summary: str


class QuestionRequest(BaseModel):
    question: str
    # The last analysis is kept server-side per session; for the demo we
    # re-run analysis from the uploaded rows sent alongside.
    rows: List[InventoryRow]


class QuestionResponse(BaseModel):
    provider: str  # "heuristic-qa" or "infinisynapse"
    answer: str
    citations: List[str]  # SKUs referenced
