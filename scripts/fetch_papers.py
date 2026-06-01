#!/usr/bin/env python3
"""
Fetch the latest arXiv papers from selected cs categories.

Output: data/papers_<date>.json
  {
    "date": "2026-06-01",
    "fetched_at": "ISO timestamp",
    "categories": ["cs.AI","cs.LG","cs.CL","cs.CV"],
    "count": N,
    "papers": [
      {
        "id": "2506.01234",
        "title": "...",
        "authors": ["Alice","Bob"],
        "abstract": "...",
        "categories": ["cs.AI","cs.LG"],
        "primary_category": "cs.AI",
        "published": "2026-06-01T17:00:00Z",
        "url": "https://arxiv.org/abs/2506.01234",
        "pdf_url": "https://arxiv.org/pdf/2506.01234"
      }
    ]
  }

Design notes:
  - Hits arXiv's free export API once per category, then merges + dedupes.
  - Targets ~30 raw papers (last 24h), LLM will down-select to top 10.
  - No external deps (urllib stdlib only).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# arXiv requires polite pauses between requests; 3s is the documented minimum
ARXIV_API = "https://export.arxiv.org/api/query"
CATEGORIES = ["cs.AI", "cs.LG", "cs.CL", "cs.CV"]
PER_CATEGORY = 20  # raw fetch per category; LLM will pick top 10 globally
NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def _http_get(url: str, timeout: int = 30) -> bytes:
    """urllib GET with retry on transient failure."""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "arxiv-daily/1.0 (hermes-agent)"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"arxiv fetch failed after 3 attempts: {last_err}")


def fetch_category(cat: str, n: int) -> list[dict]:
    """Fetch the n most recent papers in a single category."""
    url = (
        f"{ARXIV_API}?search_query=cat:{cat}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={n}"
    )
    print(f"  fetch {cat} (n={n}) ...", file=sys.stderr)
    raw = _http_get(url)
    root = ET.fromstring(raw)

    papers: list[dict] = []
    for entry in root.findall("a:entry", NS):
        raw_id = entry.findtext("a:id", "", NS).strip().split("/abs/")[-1]
        arxiv_id = raw_id.rstrip("v")  # drop version for canonical id
        title = " ".join(entry.findtext("a:title", "", NS).split())
        abstract = " ".join(entry.findtext("a:summary", "", NS).split())
        published = entry.findtext("a:published", "", NS)
        authors = [
            a.findtext("a:name", "", NS)
            for a in entry.findall("a:author", NS)
        ]
        categories = [c.get("term", "") for c in entry.findall("a:category", NS)]
        primary = entry.find("arxiv:primary_category", NS)
        primary_cat = primary.get("term", "") if primary is not None else (categories[0] if categories else "")

        papers.append(
            {
                "id": arxiv_id,
                "title": title,
                "authors": [a for a in authors if a],
                "abstract": abstract,
                "categories": [c for c in categories if c],
                "primary_category": primary_cat,
                "published": published,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            }
        )
    return papers


def main() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"papers_{today}.json"

    all_papers: dict[str, dict] = {}  # dedupe by arxiv id
    for cat in CATEGORIES:
        papers = fetch_category(cat, PER_CATEGORY)
        for p in papers:
            if p["id"] not in all_papers:
                all_papers[p["id"]] = p
        time.sleep(3.1)  # arXiv rate limit: ~1 req/3s

    papers_list = sorted(
        all_papers.values(),
        key=lambda p: p["published"],
        reverse=True,
    )

    payload = {
        "date": today,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "categories": CATEGORIES,
        "count": len(papers_list),
        "papers": papers_list,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n✓ {len(papers_list)} unique papers → {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
