import requests
import json
import os
import time

DATA_FILE = "jobs.json"
HN_JOBS_API = "https://hacker-news.firebaseio.com/v0/jobstories.json"
HN_ITEM_API = "https://hacker-news.firebaseio.com/v0/item/{}.json"

def fetch_hn_jobs():
    """
    Ingests job listings from the Hacker News public API.
    This acts as our 'safe source' to demonstrate the pipeline architecture
    without getting blocked by heavily defended platforms like LinkedIn.
    """
    try:
        print("Fetching job stories from Hacker News...")
        response = requests.get(HN_JOBS_API)
        response.raise_for_status()
        job_ids = response.json()[:20] # Limit to 20 for demo
        
        jobs = []
        for job_id in job_ids:
            print(f"Fetching details for job {job_id}...")
            item_resp = requests.get(HN_ITEM_API.format(job_id))
            if item_resp.status_code == 200:
                jobs.append(item_resp.json())
            # Simulated pacing
            time.sleep(0.5)
            
        with open(DATA_FILE, "w") as f:
            json.dump(jobs, f, indent=4)
        print(f"Successfully ingested {len(jobs)} jobs.")
    except Exception as e:
        print(f"Error fetching jobs: {e}")

if __name__ == "__main__":
    fetch_hn_jobs()
