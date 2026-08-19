import urllib.request, json
d = json.loads(urllib.request.urlopen('http://localhost:8000/jobs').read())
print(f"total={d['total']}, skipped={d['skipped']}, ingested_at={d['ingested_at']}")
for i, j in enumerate(d['jobs'][:5]):
    print(f"  [{i+1}] {j['title'][:60]} | company={j['company']}")
