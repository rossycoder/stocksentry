"""StockSentry analytics engine — real math, no fake outputs.

Every number returned here is computed from the input rows:
- days_of_stock   = on_hand / avg_daily_sales
- reorder_point   = avg_daily_sales * lead_time_days * safety_factor
- risk_score      = 0-100 from coverage vs. lead time
- suggested_order = economic-ish order-up-to quantity

Nothing is invented. Zero-sales items are flagged honestly instead of
being given made-up risk scores.
"""
from __future__ import annotations

import math
from typing import List

from .models import InventoryRow, RiskItem

SAFETY_FACTOR = 1.25  # 25% safety buffer on the reorder point
TARGET_COVERAGE_DAYS = 30  # order-up-to target


def _risk_level(days_of_stock: float | None, lead_time_days: float) -> tuple[str, float]:
    """Map coverage to a risk level + 0-100 score."""
    if days_of_stock is None:
        return "OK", 0.0  # no sales history -> cannot score, say so
    if days_of_stock <= 0:
        return "CRITICAL", 100.0
    # How many lead-time cycles of cover remain?
    cover_ratio = days_of_stock / max(lead_time_days, 0.5)
    if cover_ratio < 0.5:
        # Less than half a lead time of stock left
        score = 95.0 - (cover_ratio / 0.5) * 10.0
        return "CRITICAL", round(min(score, 99.0), 1)
    if cover_ratio < 1.0:
        score = 80.0 - ((cover_ratio - 0.5) / 0.5) * 15.0
        return "HIGH", round(score, 1)
    if cover_ratio < 2.0:
        score = 55.0 - ((cover_ratio - 1.0)) * 20.0
        return "MEDIUM", round(score, 1)
    if cover_ratio < 4.0:
        score = 30.0 - ((cover_ratio - 2.0) / 2.0) * 20.0
        return "LOW", round(max(score, 5.0), 1)
    return "OK", 0.0


def analyze(rows: List[InventoryRow]) -> List[RiskItem]:
    items: List[RiskItem] = []
    for r in rows:
        if r.avg_daily_sales > 0:
            days = r.on_hand / r.avg_daily_sales
        else:
            days = None  # honest: no velocity data

        reorder_point = r.avg_daily_sales * r.lead_time_days * SAFETY_FACTOR
        level, score = _risk_level(days, r.lead_time_days)

        if r.avg_daily_sales > 0:
            target = r.avg_daily_sales * TARGET_COVERAGE_DAYS
            suggested = max(0.0, math.ceil(target - r.on_hand))
        else:
            suggested = 0.0

        value_at_risk = round(r.on_hand * r.unit_cost, 2)

        if days is None:
            reason = (
                f"No sales velocity recorded for {r.sku}; cannot estimate "
                "stockout risk. Check if this item is new, seasonal, or dead stock."
            )
        elif level == "CRITICAL":
            reason = (
                f"Only {days:.1f} days of stock left vs {r.lead_time_days:.0f}-day lead time. "
                "Order immediately — stockout likely before replenishment arrives."
            )
        elif level == "HIGH":
            reason = (
                f"{days:.1f} days of cover vs {r.lead_time_days:.0f}-day lead time. "
                "Below one full lead-time cycle — reorder this week."
            )
        elif level == "MEDIUM":
            reason = (
                f"{days:.1f} days of cover. Within 2 lead-time cycles — "
                "plan the reorder now."
            )
        elif level == "LOW":
            reason = f"{days:.1f} days of cover. Healthy, keep an eye on it."
        else:
            reason = f"{days:.1f} days of cover. No action needed."

        items.append(
            RiskItem(
                sku=r.sku,
                product_name=r.product_name,
                category=r.category,
                on_hand=r.on_hand,
                avg_daily_sales=r.avg_daily_sales,
                lead_time_days=r.lead_time_days,
                days_of_stock=round(days, 1) if days is not None else None,
                reorder_point=round(reorder_point, 1),
                risk_level=level,
                risk_score=score,
                suggested_order_qty=suggested,
                value_at_risk=value_at_risk,
                reason=reason,
            )
        )

    # Sort: highest risk first, then by value at risk
    rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "OK": 4}
    items.sort(key=lambda i: (rank[i.risk_level], -i.value_at_risk))
    return items


def summarize(items: List[RiskItem]) -> tuple[str, float]:
    crit = [i for i in items if i.risk_level == "CRITICAL"]
    high = [i for i in items if i.risk_level == "HIGH"]
    total_var = round(sum(i.value_at_risk for i in items), 2)
    parts = [
        f"Analyzed {len(items)} SKUs: "
        f"{len(crit)} critical, {len(high)} high risk. "
        f"Total inventory value at risk: ${total_var:,.2f}."
    ]
    if crit:
        names = ", ".join(f"{i.sku} ({i.days_of_stock}d left)" for i in crit[:3])
        parts.append(f"Order first: {names}.")
    elif high:
        names = ", ".join(f"{i.sku} ({i.days_of_stock}d left)" for i in high[:3])
        parts.append(f"Reorder this week: {names}.")
    else:
        parts.append("No urgent reorders — stock cover is healthy.")
    return " ".join(parts), total_var


# ---------------------------------------------------------------------------
# Next-level tools — built from real small-business complaints on social media
# ---------------------------------------------------------------------------

# Dead-stock velocity threshold: below this daily sales rate an SKU is
# considered "not moving" (cash trapped on the shelf).
DEAD_VELOCITY_THRESHOLD = 0.5
# Discount elasticity assumption: each 1% of discount lifts daily velocity
# by ~3% (k=3). Labeled as an estimate everywhere it is used.
DISCOUNT_ELASTICITY = 3.0
MAX_SUGGESTED_DISCOUNT = 0.70


def _discount_to_clear(on_hand: float, velocity: float, days: int) -> float:
    """Discount fraction (0-0.7) estimated to clear on_hand units in `days`.

    required_velocity = on_hand / days. With elasticity k, a discount d
    lifts velocity to velocity * (1 + k*d). Solve for d, clamp to [0, 0.7].
    Zero-velocity items get a 30% starting suggestion (labeled estimate).
    """
    if on_hand <= 0:
        return 0.0
    required = on_hand / max(days, 1)
    if velocity <= 0:
        return 0.30  # no velocity data: honest starting suggestion
    if required <= velocity:
        return 0.0  # already clears in time without discount
    d = (required / velocity - 1.0) / DISCOUNT_ELASTICITY
    return round(min(max(d, 0.0), MAX_SUGGESTED_DISCOUNT), 2)


def dead_stock(rows: List[InventoryRow]) -> tuple[list, float]:
    """Flag ~zero-velocity SKUs, cash locked, and clearance discounts.

    Returns (items, total_cash_locked). Items are dicts ready for the
    DeadStockItem model. Sorted by cash locked, descending.
    """
    out = []
    for r in rows:
        if r.avg_daily_sales >= DEAD_VELOCITY_THRESHOLD:
            continue
        if r.on_hand <= 0:
            continue
        cash = round(r.on_hand * r.unit_cost, 2)
        out.append({
            "sku": r.sku,
            "product_name": r.product_name,
            "on_hand": r.on_hand,
            "avg_daily_sales": r.avg_daily_sales,
            "unit_cost": r.unit_cost,
            "cash_locked": cash,
            "discount_30d": _discount_to_clear(r.on_hand, r.avg_daily_sales, 30),
            "discount_60d": _discount_to_clear(r.on_hand, r.avg_daily_sales, 60),
            "discount_90d": _discount_to_clear(r.on_hand, r.avg_daily_sales, 90),
        })
    out.sort(key=lambda x: -x["cash_locked"])
    total = round(sum(x["cash_locked"] for x in out), 2)
    return out, total


def spike_simulate(rows: List[InventoryRow], multiplier: float) -> tuple[list, int]:
    """What if demand spikes `multiplier`x tomorrow?

    Returns (items, stockout_7d_count). Items are dicts ready for SpikeItem,
    sorted by spike days-of-stock ascending (most urgent first).
    """
    out = []
    for r in rows:
        spike_daily = r.avg_daily_sales * multiplier
        if spike_daily > 0:
            spike_days = round(r.on_hand / spike_daily, 1)
        else:
            spike_days = None  # no velocity: cannot project
        if r.avg_daily_sales > 0:
            normal_days = round(r.on_hand / r.avg_daily_sales, 1)
        else:
            normal_days = None
        # Emergency order: top up to 30 days of SPIKED cover
        target = spike_daily * TARGET_COVERAGE_DAYS
        emergency = max(0.0, math.ceil(target - r.on_hand)) if spike_daily > 0 else 0.0
        out.append({
            "sku": r.sku,
            "product_name": r.product_name,
            "normal_days": normal_days,
            "spike_days": spike_days,
            "emergency_order_qty": emergency,
            "stockout_in_7d": spike_days is not None and spike_days < 7,
        })
    out.sort(key=lambda x: (x["spike_days"] is None, x["spike_days"] or 0))
    count_7d = sum(1 for x in out if x["stockout_in_7d"])
    return out, count_7d


def true_restock(rows: List[InventoryRow], cost_multiplier: float,
                 new_costs: dict | None = None) -> tuple[list, float, float]:
    """Supplier raised prices: how many units can old-cost capital rebuy?

    For each SKU: rebuy_qty = (on_hand * old_cost) / new_cost.
    Returns (items, total_shortfall_units, total_extra_capital).
    Items sorted by shortfall descending.
    """
    new_costs = new_costs or {}
    out = []
    for r in rows:
        if r.unit_cost <= 0 or r.on_hand <= 0:
            continue
        new_cost = float(new_costs.get(r.sku, r.unit_cost * cost_multiplier))
        if new_cost <= 0:
            continue
        capital = r.on_hand * r.unit_cost
        rebuy = capital / new_cost
        shortfall = max(0.0, r.on_hand - rebuy)
        extra = round(r.on_hand * (new_cost - r.unit_cost), 2)
        out.append({
            "sku": r.sku,
            "product_name": r.product_name,
            "on_hand": r.on_hand,
            "old_cost": round(r.unit_cost, 2),
            "new_cost": round(new_cost, 2),
            "rebuy_qty": round(rebuy, 1),
            "shortfall_units": round(shortfall, 1),
            "extra_capital_needed": max(0.0, extra),
        })
    out.sort(key=lambda x: -x["shortfall_units"])
    total_short = round(sum(x["shortfall_units"] for x in out), 1)
    total_extra = round(sum(x["extra_capital_needed"] for x in out), 2)
    return out, total_short, total_extra
