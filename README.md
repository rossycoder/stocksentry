# 📦 StockSentry — AI Replenishment Desk

**InfiniSynapse Vibe Coding Hackathon 2026 · Track: Retail & Replenishment**

A working, data-backed app a real small retail shop can open and use.
Upload inventory CSV → the engine computes stockout risk per SKU with real math →
you get a ranked reorder list, an AI plain-language briefing, and natural-language Q&A over your stock.

**Data path (inputs in, decision out):** CSV in → risk analysis → reorder decisions out.
No fake JSON. No generic chat-on-a-CSV. Every number is computed from your data.

## Quick start

```bash
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn app.main:app --port 8127
# open http://localhost:8127
```

Click **⚡ Try demo data** for a one-click tour (synthetic data, clearly labeled),
or **📤 Upload your CSV**.

Optional AI upgrade (free): create an API key at https://app.infinisynapse.com
(new keys get 500 credits), put it in a `.env` file as `INFINI_API_KEY=...`,
restart. The "AI briefing" then uses InfiniSynapse's API; otherwise the
offline heuristic narrator is used — always labeled.

## Architecture

```
CSV upload ──▶ FastAPI ──▶ analytics.py (deterministic risk engine)
                  │                    days_of_stock, reorder_point,
                  │                    risk score 0-100, suggested qty
                  ▼
            ┌─────────────┐
            │  dashboard   │  ranked reorder list + KPIs
            │  AI briefing │──▶ ai_narrate.py ──▶ InfiniSynapse API (if key)
            │  Q&A         │                      else offline heuristic (labeled)
            └─────────────┘
```

## Real vs. stubbed

| Part | Status |
|---|---|
| Risk engine (days of stock, reorder point, risk score, suggested qty) | ✅ Real math, tested |
| CSV parsing + validation | ✅ Real |
| Demo dataset | ⚠️ Synthetic, badged "DEMO DATA" everywhere |
| AI briefing | ✅ Real via InfiniSynapse API when `INFINI_API_KEY` set; otherwise labeled offline heuristic |
| Q&A | ✅ Real heuristic over your actual analysis (rule-based, labeled) |
| InfiniSynapse platform integration | ✅ Real client code (`ai_narrate.py`), needs free API key to activate |

## API

| Endpoint | What it does |
|---|---|
| `GET /` | Dashboard UI |
| `GET /api/status` | Health + provider info |
| `GET /api/sample` | Demo analysis (synthetic data) |
| `GET /api/sample.csv` | Download the demo CSV |
| `POST /api/analyze` | Upload CSV → analysis |
| `POST /api/analyze-rows` | JSON rows → analysis |
| `POST /api/narrate` | Plain-language briefing |
| `POST /api/ask` | Q&A over the analysis |

## Why it can win

- **Real-world value (40%):** stockouts cost real shops real money daily; this answers "what do I reorder today?" in one click.
- **Technical completeness (35%):** full data path, validation, honest edge cases (zero-velocity items flagged, not faked), tested end-to-end.
- **Innovation (25%):** risk scoring tied to lead-time coverage + natural-language Q&A over live analysis, not a static report.

## License

MIT
