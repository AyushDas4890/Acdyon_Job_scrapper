# DECISIONS.md

**Why this ingestion strategy over the obvious alternative?**

The obvious alternative is a plain `requests` loop with BeautifulSoup selectors. I rejected it not because it is unsophisticated but because it fails at the first detection layer — the network handshake — before a single HTML byte of meaningful data is served. Modern WAFs fingerprint TLS connections and catch standard Python HTTP clients by their JA3/JA4 hash alone, independently of any browser-level or behavioral signal. Building on a foundation that fails at layer one means all the work on selectors, pagination, and normalization is wasted. The strategy in DESIGN.md addresses all three detection layers simultaneously: network (TLS mimicry, residential proxies), browser (stealth-patched headless Chrome), and behavioral (pacing with jitter, session pre-warming). The live demo runs against the Hacker News public API precisely because the assessment requires a low-risk source — but the resilience primitives in `ingester.py` (backoff, normalization, structured error handling) are the same ones you'd wire up to a stealth session.

**One trade-off made under the time limit, and what a real week would look like.**

The most significant trade-off is that the pipeline persists data to a flat JSON file rather than a database. While I implemented in-memory deduplication and merge logic for the demo to run self-contained without external dependencies, a flat file lacks concurrent transaction safety, indexed query capabilities, and historical change tracking. With a full week, I would replace the file write with a PostgreSQL database (using `asyncpg` or SQLAlchemy) with a unique constraint on the job ID so that duplicate checks happen at the database engine level. I would also move the ingestion trigger from a simple FastAPI background task to a scheduled worker queue (Celery or APScheduler) so the pipeline runs reliably on a clock rather than on-demand.

**Where AI tools were used and how I verified the output.**

I used Antigravity (Google's agentic IDE assistant) to scaffold the initial project structure, write the frontend HTML dashboard, and help draft the documentation. I personally reviewed and modified the generated output:
- **Resilience:** Replaced the initial fixed backoff with a randomized exponential jitter formula in `ingester.py` to prevent thundering herd problems.
- **Normalization:** Checked the title parsing code in `normalize_hn_item` to ensure it robustly extracts the company name without throwing exceptions on missing or malformed separators.
- **Concurrency:** Verified that the threading lock in `main.py` prevents race conditions if multiple users hit the `/ingest` trigger simultaneously.
- **Deduplication:** Rewrote the ingestion logic to load existing listings first, performing safe key-matching deduplication before writing to disk.

