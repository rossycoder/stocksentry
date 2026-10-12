"""Pydantic models for StockSentry API."""
from __future__ import annotations

from typing import Dict, List, Optional
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
    provider: str  # "pollinations" | "groq:..." | "gemini:..." | "heuristic-qa"
    answer: str
    citations: List[str]  # SKUs referenced


# ---------------------------------------------------------------------------
# Next-level tools (built from real small-business complaints)
# ---------------------------------------------------------------------------

class RowsRequest(BaseModel):
    rows: List[InventoryRow]


class DeadStockItem(BaseModel):
    sku: str
    product_name: str
    on_hand: float
    avg_daily_sales: float
    unit_cost: float
    cash_locked: float
    discount_30d: float  # suggested % off to clear stock in 30 days
    discount_60d: float
    discount_90d: float


class DeadStockResponse(BaseModel):
    provider: str  # "stocksentry-engine"
    item_count: int
    total_cash_locked: float
    items: List[DeadStockItem]
    note: str


class SpikeRequest(BaseModel):
    rows: List[InventoryRow]
    multiplier: float = Field(default=10.0, gt=1, le=100)


class SpikeItem(BaseModel):
    sku: str
    product_name: str
    normal_days: Optional[float]
    spike_days: Optional[float]
    emergency_order_qty: float
    stockout_in_7d: bool


class SpikeResponse(BaseModel):
    provider: str  # "stocksentry-engine"
    multiplier: float
    stockout_7d_count: int
    items: List[SpikeItem]


class RestockRequest(BaseModel):
    rows: List[InventoryRow]
    cost_multiplier: float = Field(default=1.25, gt=1, le=10,
                                   description="Supplier price increase, e.g. 1.25 = +25%")
    new_costs: Optional[Dict[str, float]] = Field(
        default=None, description="Optional per-SKU override of the new unit cost")


class RestockItem(BaseModel):
    sku: str
    product_name: str
    on_hand: float
    old_cost: float
    new_cost: float
    rebuy_qty: float  # how many units the old-cost capital can rebuy at new cost
    shortfall_units: float
    extra_capital_needed: float


class RestockResponse(BaseModel):
    provider: str  # "stocksentry-engine"
    cost_multiplier: float
    total_shortfall_units: float
    total_extra_capital: float
    items: List[RestockItem]
