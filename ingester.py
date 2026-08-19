"""
ingester.py — Core ingestion engine for the job scraper demo.

This module is the heart of the pipeline. It handles fetching, normalization,
resilience (retries with exponential backoff), and pacing. The live demo runs
against the Hacker News Jobs API because it is public, legal, and does not
require authentication — demonstrating the end-to-end pipeline without
violating any platform's terms of service.

In a production build against defended targets like LinkedIn or Indeed, this
module's fetch_with_retry() would be called through a stealth-hardened HTTP
session (see DESIGN.md for the full strategy), but the resilience primitives
here — backoff, structured errors, normalization — are identical.
"""

import json
import logging
import os
import random
import time
import datetime
from dataclasses import dataclass, asdict
from typing import Optional
import requests

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DATA_FILE = "jobs.json"
HN_JOBS_ENDPOINT = "https://hacker-news.firebaseio.com/v0/jobstories.json"
HN_ITEM_ENDPOINT = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

# How many job IDs to pull per ingestion run. Keep this low for the demo so
# we don't hammer the API unnecessarily; in production you'd paginate further.
MAX_JOBS_PER_RUN = 20

# Pacing: each request sleeps a random amount between these two bounds (seconds).
# This mimics human reading speed and avoids triggering rate-limit detection.
PACE_MIN = 0.4
PACE_MAX = 1.2

# Retry settings for the exponential backoff logic.
MAX_RETRIES = 4
BACKOFF_BASE = 2.0  # seconds; doubles on each retry


# ---------------------------------------------------------------------------
# Normalized data model
# ---------------------------------------------------------------------------

@dataclass
class JobListing:
    """
    A clean, normalized representation of a job listing.

    We separate raw API fields from our schema so that if the upstream changes
    its payload shape, only the normalization function needs updating — the
    rest of the pipeline and API remain stable.
    """
    id: int
    title: str
    company: Optional[str]
    url: Optional[str]
    posted_by: str
    posted_at_unix: int
    posted_at_iso: str
    source: str = "hacker_news"

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_hn_item(raw: dict) -> Optional[JobListing]:
    """
    Converts a raw Hacker News API item dict into a JobListing.

    Returns None if the item is missing required fields, rather than raising
    an exception — the caller can decide whether to skip or retry.
    """
    item_id = raw.get("id")
    title = raw.get("title")
    posted_by = raw.get("by")
    posted_at_unix = raw.get("time")

    if not all([item_id, title, posted_by, posted_at_unix]):
        log.warning("Skipping item %s — missing required fields.", item_id)
        return None

    posted_at_iso = datetime.datetime.fromtimestamp(
        posted_at_unix, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    # HN job posts sometimes embed the company name in the title as "Title | Company"
    # or "Title (Company)". We do a best-effort parse without being brittle about it.
    company = None
    if " | " in title:
        parts = title.rsplit(" | ", 1)
        company = parts[-1].strip()
    elif title.endswith(")") and "(" in title:
        # e.g. "Senior Engineer (Acme Corp)"
        company = title[title.rfind("(") + 1 : -1].strip()

    return JobListing(
        id=item_id,
        title=title,
        company=company,
        url=raw.get("url"),
        posted_by=posted_by,
        posted_at_unix=posted_at_unix,
        posted_at_iso=posted_at_iso,
    )


# ---------------------------------------------------------------------------
# HTTP primitives with resilience
# ---------------------------------------------------------------------------

def build_session() -> requests.Session:
    """
    Creates an HTTP session with sensible defaults.

    In a stealth build, this function would additionally:
      - Set a realistic User-Agent and Accept-Language header that matches
        the targeted browser's exact TLS fingerprint order.
      - Attach a residential proxy from the rotation pool.
      - Load pre-warmed cookies from a cached identity store.
    For this demo, we use plain defaults since HN doesn't require any of that.
    """
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def fetch_with_retry(session: requests.Session, url: str) -> Optional[dict]:
    """
    Fetches a URL and returns the parsed JSON body.

    Retries up to MAX_RETRIES times with exponential backoff on any transient
    failure (network error, 5xx, 429). Returns None only after all retries are
    exhausted, so the caller can decide whether to skip the item or abort the run.

    The jitter added to the backoff sleep prevents all concurrent workers from
    thundering-herding back onto the server at the same moment — a meaningful
    detail even on a single-machine demo.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=10)

            if resp.status_code == 429:
                # Rate limited. Back off significantly and rotate identity in production.
                wait = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                log.warning("Rate limited on %s. Waiting %.1fs before retry %d.", url, wait, attempt)
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                wait = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                log.warning("Server error %d on %s. Waiting %.1fs.", resp.status_code, url, wait)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.Timeout:
            wait = BACKOFF_BASE ** attempt
            log.warning("Timeout on %s. Waiting %.1fs before retry %d.", url, wait, attempt)
            time.sleep(wait)

        except requests.exceptions.ConnectionError as exc:
            wait = BACKOFF_BASE ** attempt
            log.warning("Connection error on %s (%s). Waiting %.1fs.", url, exc, wait)
            time.sleep(wait)

        except Exception as exc:
            log.error("Unexpected error fetching %s: %s", url, exc)
            return None

    log.error("All %d retries exhausted for %s. Skipping.", MAX_RETRIES, url)
    return None


# ---------------------------------------------------------------------------
# Ingestion run
# ---------------------------------------------------------------------------

def load_existing_jobs() -> dict[int, dict]:
    """
    Loads the existing jobs from DATA_FILE into a dict keyed by id.

    Returns an empty dict if the file does not exist or is malformed.
    This is the foundation of the deduplication logic: any new item
    whose id is already in this dict is skipped rather than overwritten.
    """
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {j["id"]: j for j in data.get("jobs", []) if "id" in j}
    except Exception as exc:
        log.warning("Could not parse existing data file (%s). Starting fresh.", exc)
        return {}


def run_ingestion() -> list[dict]:
    """
    Executes a single full ingestion run with smart deduplication.

    Fetches the list of current job story IDs from Hacker News, then retrieves
    and normalizes each item, pacing itself between requests. New items are
    merged into the existing DATA_FILE by id — re-running the ingester
    accumulates unique listings rather than overwriting them.

    The pacing here (random sleep between PACE_MIN and PACE_MAX) is intentional
    and meaningful: on a real target, a predictable fixed delay is itself a
    detection signal. Jittered delays look more human.
    """
    session = build_session()
    log.info("Starting ingestion run. Fetching job IDs from Hacker News...")

    # Load existing jobs for deduplication before hitting the network.
    existing: dict[int, dict] = load_existing_jobs()
    log.info("Loaded %d existing job(s) from cache for deduplication.", len(existing))

    raw_ids = fetch_with_retry(session, HN_JOBS_ENDPOINT)
    if not raw_ids:
        log.error("Could not fetch job ID list. Aborting run.")
        return list(existing.values())

    job_ids = raw_ids[:MAX_JOBS_PER_RUN]
    log.info("Got %d job IDs. Fetching details...", len(job_ids))

    new_count = 0
    dedup_count = 0
    skipped = 0

    for job_id in job_ids:
        # Deduplication check: skip items we already have.
        if job_id in existing:
            dedup_count += 1
            log.debug("  [DUP] %d already in store. Skipping.", job_id)
            continue

        url = HN_ITEM_ENDPOINT.format(item_id=job_id)
        raw = fetch_with_retry(session, url)

        if raw is None:
            skipped += 1
            continue

        listing = normalize_hn_item(raw)
        if listing:
            existing[listing.id] = listing.to_dict()
            new_count += 1
            log.info("  [NEW] %s", listing.title[:72])
        else:
            skipped += 1

        # Pacing: jittered sleep between requests.
        time.sleep(random.uniform(PACE_MIN, PACE_MAX))

    merged_jobs = list(existing.values())
    ingested_at = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    output = {
        "ingested_at": ingested_at,
        "total": len(merged_jobs),
        "skipped": skipped,
        "jobs": merged_jobs,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    log.info(
        "Ingestion complete. %d new, %d deduplicated, %d skipped. Total store: %d.",
        new_count, dedup_count, skipped, len(merged_jobs),
    )
    return merged_jobs


if __name__ == "__main__":
    run_ingestion()
