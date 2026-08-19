# ⚡ Acdyon Job Ingestion Pipeline

> **Acdyon Technologies Engineering Challenge — Part 1**  
> *Getting Data Out of a Platform That Doesn't Want You To*

A resilient job-listing ingestion pipeline built for **LinkedIn · Indeed · Naukri · Wellfound** — platforms that actively fingerprint, rate-limit, and ban automated clients. The live demo runs against the **Hacker News Jobs API** as a zero-ToS-risk proxy source that demonstrates the end-to-end pattern without burning a real account.

---

## 🚀 Live Demo

| Resource | Link |
|---|---|
| **Live Dashboard** | [acydon-scraper-demo.onrender.com](https://acydon-scraper-demo.onrender.com) |
| **API Docs (Swagger)** | [/docs](https://acydon-scraper-demo.onrender.com/docs) |
| **Health Check** | [/health](https://acydon-scraper-demo.onrender.com/health) |
| **Job Feed (JSON)** | [/jobs](https://acydon-scraper-demo.onrender.com/jobs) |

---

## 🖼️ Dashboard Preview

The dashboard shows the **real-world target platforms** (LinkedIn, Indeed, Naukri, Wellfound) with threat-level indicators, a live job feed, search & filter, and a one-click ingest trigger.

![Dashboard](./static/preview.png)

---

## 🏗️ Architecture

### Detection Layers vs. Our Countermeasures

```
┌─────────────────────────────────────────────────────────────────┐
│  Platform Defenses          Our Countermeasures                 │
│  ──────────────────         ────────────────────                │
│  Network Layer              TLS Mimicry                         │
│  TLS fingerprint · ASN  ──► Residential proxies                 │
│  Header order               Correct header order                │
│                                                                 │
│  Browser Layer              Stealth Browser                     │
│  navigator.webdriver    ──► playwright-stealth                  │
│  Canvas FP · WebGL          Patched fingerprints                │
│                                                                 │
│  Behavioral Layer           Pacing + Jitter                     │
│  Click timing           ──► Random sleep PACE_MIN–PACE_MAX      │
│  Mouse events               Session pre-warming                 │
│                                                                 │
│  Account Layer              Identity Stability                  │
│  Login IP · UA mismatch ──► Consistent IP per session           │
│  Bulk signup                Pre-aged accounts                   │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline Flow

```
Trigger (HTTP / Scheduler)
        │
        ▼
load_existing_jobs()   ← jobs.json (dedup map: {id → job})
        │
        ▼
GET /jobstories.json   ← Hacker News API (or defended target)
        │
        ▼
  For each job ID:
    ┌── Already in map? → skip (dedup_count++)
    └── New ID?
          │
          ▼
        fetch_with_retry()        ← Exponential backoff + jitter
          │
          ▼
        normalize_hn_item()       ← Schema validation + company parse
          │
          ▼
        merge into existing map   ← Idempotent accumulation
          │
          ▼
        sleep(random jitter)      ← Pacing between requests
        │
        ▼
Write merged jobs.json
        │
        ▼
FastAPI /jobs serves updated feed
```

---

## 📁 Project Structure

```
scraper-demo/
├── ingester.py          # Core pipeline: fetch · normalize · dedup · persist
├── main.py              # FastAPI app: /jobs · /health · POST /ingest
├── scraper.py           # Minimal standalone scraper (demo reference)
├── verify.py            # Quick CLI verification script
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container for self-contained deployment
├── render.yaml          # Render Blueprint (one-click deploy)
├── static/
│   └── index.html       # Premium dark-mode dashboard (no framework)
├── DESIGN.md            # Full system design + Mermaid architecture diagrams
├── DECISIONS.md         # Engineering decision log (why/trade-offs/AI usage)
└── jobs.json            # Seeded job data (auto-updated on each run)
```

---

## 🧠 Design Decisions (Summary)

Full detail in [`DECISIONS.md`](./DECISIONS.md).

**Why not `requests` + BeautifulSoup?**  
Modern WAFs fingerprint TLS connections and reject standard Python HTTP clients by JA3/JA4 hash before a single HTML byte is served. That fails at layer one — everything built on top is wasted work.

**The real strategy (for LinkedIn-class targets):**
1. **TLS Mimicry** — residential proxies + correct header order
2. **Stealth Browser** — `playwright-stealth`, patched canvas/WebGL fingerprints
3. **Pacing + Jitter** — `random.uniform(PACE_MIN, PACE_MAX)` between every request
4. **Session Pre-Warming** — browse realistically before touching data endpoints
5. **Exponential Backoff** — on 429/5xx, back off with jitter before rotating identity

**Why Hacker News for the demo?**  
The assessment explicitly scopes the live demo to a public, low-risk source. HN's job API demonstrates the full ingestion pattern end-to-end without breaching any ToS on Acdyon's behalf.

**Trade-off made:** Flat JSON persistence instead of PostgreSQL. Smart deduplication is implemented (merge by `id`) but a real week would add a proper database with unique constraints and Celery scheduling.

---

## 🛡️ Resilience Features

| Scenario | Handling |
|---|---|
| Rate-limited (429) | Exponential backoff with random jitter, up to `MAX_RETRIES` |
| Server error (5xx) | Same backoff with logging |
| Network timeout | Retry with backoff |
| Missing fields in payload | `normalize_hn_item()` returns `None`; item counted as `skipped` |
| Re-running ingestion | `load_existing_jobs()` deduplicates by `id` — accumulates, never overwrites |
| Concurrent ingest triggers | `threading.Lock()` in `main.py` prevents race conditions |
| DOM mutation (real targets) | Strategy: semantic extraction / lightweight LLM call instead of brittle CSS selectors |

---

## 🚀 Running Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed initial data
python ingester.py

# 3. Start the server
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** — the dashboard loads immediately.

### Docker

```bash
docker build -t scraper-demo .
docker run -p 8000:8000 scraper-demo
```

---

## 🔌 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Premium dashboard UI |
| `GET` | `/health` | Pipeline status, job count, last ingestion time |
| `GET` | `/jobs` | All ingested and deduplicated job listings |
| `POST` | `/ingest` | Trigger a fresh background ingestion run |
| `GET` | `/docs` | Swagger interactive API documentation |

---

## 🥚 Easter Egg

There's a hidden easter egg on the dashboard. Try entering:

```
↑ ↑ ↓ ↓ ← → ← → B A
```

---

## 📐 Ethics & Boundaries

- Only publicly visible, unauthenticated data is targeted
- Request concurrency is deliberately limited to avoid meaningful load on targets
- Pipeline exits cleanly on explicit cease-and-desist or clearly enumerated ToS prohibition
- CAPTCHA solving is noted as a capability but not implemented in this demo

---

## 📝 License

Built for the Acdyon Technologies Engineering Challenge.
