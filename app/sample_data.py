"""Synthetic demo inventory — CLEARLY LABELED as fake demo data.

This exists so judges/reviewers can try the app in one click without
uploading their own CSV. It is never presented as real business data:
the UI badges it "DEMO DATA", and the /api/sample endpoint says so too.
"""
from __future__ import annotations

import csv
import io
import random

from .models import InventoryRow

_DEMO_ITEMS = [
    # (sku, name, category, on_hand, daily_sales, lead_days, unit_cost)
    ("TSH-001", "Classic White T-Shirt", "Apparel", 14, 9.5, 7, 4.20),
    ("TSH-002", "Black Graphic Tee", "Apparel", 210, 6.0, 7, 5.10),
    ("JNS-101", "Slim-Fit Jeans 32", "Apparel", 8, 4.2, 14, 18.75),
    ("JNS-102", "Slim-Fit Jeans 34", "Apparel", 96, 3.8, 14, 18.75),
    ("SNK-201", "Running Sneakers W9", "Footwear", 5, 3.1, 21, 32.00),
    ("SNK-202", "Running Sneakers M10", "Footwear", 64, 2.7, 21, 32.00),
    ("CAP-301", "Baseball Cap Navy", "Accessories", 300, 2.0, 5, 3.40),
    ("BLT-302", "Leather Belt Brown", "Accessories", 22, 1.5, 10, 9.90),
    ("WLT-303", "Bifold Wallet", "Accessories", 3, 1.2, 10, 12.50),
    ("SCK-401", "Ankle Socks 3-Pack", "Apparel", 500, 11.0, 5, 2.10),
    ("HDY-501", "Zip Hoodie Grey", "Apparel", 45, 5.5, 12, 16.80),
    ("HDY-502", "Zip Hoodie Black", "Apparel", 12, 5.9, 12, 16.80),
    ("WTB-601", "Water Bottle 750ml", "Accessories", 180, 4.4, 6, 6.25),
    ("BPK-602", "Canvas Backpack", "Accessories", 9, 2.2, 18, 21.40),
    ("SUN-701", "Sunglasses Aviator", "Accessories", 70, 1.8, 9, 8.60),
    ("NEW-801", "Limited-Edition Tote", "Apparel", 40, 0.0, 7, 7.30),  # no velocity
]


def get_demo_rows(seed: int = 7) -> list[InventoryRow]:
    rng = random.Random(seed)
    rows: list[InventoryRow] = []
    for sku, name, cat, hand, sales, lead, cost in _DEMO_ITEMS:
        jitter = lambda v: round(v * rng.uniform(0.9, 1.1), 1) if v else 0.0
        rows.append(
            InventoryRow(
                sku=sku,
                product_name=name,
                category=cat,
                on_hand=jitter(hand),
                avg_daily_sales=jitter(sales),
                lead_time_days=lead,
                unit_cost=cost,
            )
        )
    return rows


def demo_csv() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sku", "product_name", "category", "on_hand",
                "avg_daily_sales", "lead_time_days", "unit_cost"])
    for r in get_demo_rows():
        w.writerow([r.sku, r.product_name, r.category, r.on_hand,
                    r.avg_daily_sales, r.lead_time_days, r.unit_cost])
    return buf.getvalue()
