#!/usr/bin/env bash
# End-to-end run: fetch → analyze → render → publish.
# Usage: ./run.sh [--no-publish]
set -euo pipefail
cd "$(dirname "$0")"

echo "▶ [1/3] fetch arxiv papers"
python3 scripts/fetch_papers.py

echo "▶ [2/3] analyze with LLM (filter top 10 + Chinese analysis)"
python3 scripts/analyze.py

echo "▶ [3/3] render html"
python3 scripts/render_html.py

if [[ "${1:-}" != "--no-publish" ]]; then
  echo "▶ [4/4] publish to github pages"
  python3 scripts/publish.py
fi

echo "✓ done"
