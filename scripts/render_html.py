#!/usr/bin/env python3
"""
Render arxiv papers JSON into a self-contained HTML report.

Design:
  - 暗色为默认，浅色随系统切换
  - 零外部资源（无 CDN / 字体）
  - 响应式、移动友好
  - 首页 index.html：当日 top 10
  - archive.html：历史索引
  - reports/<date>.html：单日报告
"""
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"
SITE = PROJECT / "site"
REPORTS = SITE / "reports"


def fmt_authors(authors: list[str]) -> str:
    if not authors:
        return "—"
    if len(authors) <= 3:
        return " · ".join(authors)
    return " · ".join(authors[:3]) + " · et al."


def fmt_primary_cat(cat: str) -> str:
    return cat.replace("cs.", "") if cat else "—"


def badge_html(category: str) -> str:
    return f'<span class="cat">{category}</span>'


# ========== Template ==========
HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="arxiv-daily">
<meta name="description" content="arXiv 每日精选论文 · {date}，AI/ML 主流方向 top 10，附中文核心解读。">
<title>arXiv 每日精选 · {date}</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #0d1117;
    --bg-elev: #161b22;
    --bg-card: #1c2129;
    --bg-soft: #20262d;
    --border: #30363d;
    --border-soft: #21262d;
    --fg: #e6edf3;
    --fg-muted: #8b949e;
    --fg-dim: #6e7681;
    --accent: #58a6ff;
    --accent-2: #d2a8ff;
    --accent-3: #7ee787;
    --warn: #f0883e;
    --rank: #f0883e;
    --shadow: 0 1px 0 rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.18);
    --radius: 12px;
    --radius-sm: 6px;
    --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{
      --bg: #ffffff;
      --bg-elev: #f6f8fa;
      --bg-card: #ffffff;
      --bg-soft: #f3f5f8;
      --border: #d0d7de;
      --border-soft: #eaeef2;
      --fg: #1f2328;
      --fg-muted: #59636e;
      --fg-dim: #818b98;
      --accent: #0969da;
      --accent-2: #8250df;
      --accent-3: #1a7f37;
      --warn: #bc4c00;
    }}
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; padding: 24px 20px 80px; }}
  header {{
    border-bottom: 1px solid var(--border-soft);
    padding-bottom: 20px;
    margin-bottom: 32px;
  }}
  h1 {{
    font-size: 28px;
    margin: 0 0 6px;
    letter-spacing: -0.02em;
  }}
  .subtitle {{
    color: var(--fg-muted);
    font-size: 14px;
    margin: 0;
  }}
  .meta {{
    color: var(--fg-dim);
    font-size: 13px;
    margin-top: 8px;
  }}
  .stats {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 16px 0 0;
  }}
  .stat {{
    background: var(--bg-soft);
    border: 1px solid var(--border-soft);
    color: var(--fg-muted);
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
  }}
  .stat strong {{ color: var(--fg); font-weight: 600; }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border-soft);
    border-radius: var(--radius);
    padding: 20px 22px;
    margin-bottom: 18px;
    box-shadow: var(--shadow);
    transition: border-color 0.2s, transform 0.2s;
  }}
  .card:hover {{
    border-color: var(--border);
  }}
  .card-head {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 8px;
    flex-wrap: wrap;
  }}
  .rank {{
    background: linear-gradient(135deg, var(--rank), var(--accent-2));
    color: #fff;
    font-weight: 700;
    font-size: 14px;
    width: 32px;
    height: 32px;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }}
  .cat {{
    background: var(--bg-soft);
    color: var(--accent);
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 500;
    border: 1px solid var(--border-soft);
  }}
  .primary-cat {{
    color: var(--fg-dim);
    font-size: 12px;
    font-family: var(--mono);
  }}
  h2 {{
    font-size: 18px;
    margin: 4px 0 4px;
    line-height: 1.4;
    font-weight: 600;
  }}
  h2 a {{
    color: var(--fg);
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color 0.2s, color 0.2s;
  }}
  h2 a:hover {{
    color: var(--accent);
    border-bottom-color: var(--accent);
  }}
  .authors {{
    color: var(--fg-muted);
    font-size: 13px;
    margin: 0 0 12px;
  }}
  .highlight {{
    color: var(--accent-2);
    font-size: 14px;
    font-weight: 500;
    margin: 0 0 10px;
    padding-left: 10px;
    border-left: 3px solid var(--accent-2);
  }}
  .brief {{
    color: var(--fg);
    font-size: 14px;
    margin: 8px 0 12px;
  }}
  .section-label {{
    color: var(--fg-dim);
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 10px 0 4px;
  }}
  .advantages, .scenarios {{
    margin: 0;
    padding: 0;
    list-style: none;
  }}
  .advantages li, .scenarios li {{
    padding: 3px 0 3px 18px;
    position: relative;
    font-size: 13px;
    color: var(--fg);
  }}
  .advantages li::before {{
    content: "✦";
    color: var(--accent-3);
    position: absolute;
    left: 0;
    top: 3px;
  }}
  .scenarios li::before {{
    content: "→";
    color: var(--accent);
    position: absolute;
    left: 0;
    top: 3px;
  }}
  .why {{
    background: var(--bg-soft);
    border-left: 3px solid var(--warn);
    padding: 10px 14px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    color: var(--fg-muted);
    margin-top: 10px;
  }}
  .links {{
    margin-top: 14px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .links a {{
    color: var(--accent);
    text-decoration: none;
    font-size: 12px;
    padding: 4px 10px;
    background: var(--bg-soft);
    border: 1px solid var(--border-soft);
    border-radius: 999px;
    transition: border-color 0.2s;
  }}
  .links a:hover {{
    border-color: var(--accent);
  }}
  footer {{
    text-align: center;
    color: var(--fg-dim);
    font-size: 12px;
    margin-top: 48px;
    padding-top: 24px;
    border-top: 1px solid var(--border-soft);
  }}
  footer a {{
    color: var(--fg-muted);
    text-decoration: none;
  }}
  footer a:hover {{ color: var(--accent); }}
  @media (max-width: 600px) {{
    .wrap {{ padding: 16px 12px 60px; }}
    h1 {{ font-size: 22px; }}
    h2 {{ font-size: 16px; }}
    .card {{ padding: 16px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>arXiv 每日精选</h1>
    <p class="subtitle">AI / ML / CV / NLP 主线方向 · {date}</p>
    <p class="meta">从 {total_candidates} 篇最新论文中精选 {selected_count} 篇 · 由 MiniMax-M3 分析</p>
    <div class="stats">
      <span class="stat"><strong>{selected_count}</strong> 篇精选</span>
      <span class="stat">从 <strong>{total_candidates}</strong> 篇候选</span>
      <span class="stat">{category_stats}</span>
    </div>
  </header>

  {cards}

  <footer>
    <p>
      数据来源：<a href="https://arxiv.org/" target="_blank" rel="noopener">arXiv.org</a> (cs.AI · cs.LG · cs.CL · cs.CV) ·
      分析：<a href="https://github.com/MiniMax-AI" target="_blank" rel="noopener">MiniMax-M3</a>
    </p>
    <p>自动生成于 {generated_at} · <a href="archive.html">历史归档</a></p>
  </footer>
</div>
</body>
</html>
"""


def render_card(p: dict) -> str:
    a = p.get("analysis") or {}
    arxiv_id = p["id"].rstrip("v")  # canonical id
    abs_url = f"https://arxiv.org/abs/{arxiv_id}"
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    html_url = f"https://arxiv.org/html/{arxiv_id}"

    advantages = a.get("advantages") or []
    scenarios = a.get("scenarios") or []

    adv_html = "\n".join(f"<li>{x}</li>" for x in advantages)
    scen_html = "\n".join(f"<li>{x}</li>" for x in scenarios)

    return f"""  <article class="card">
    <div class="card-head">
      <span class="rank">#{p['rank']}</span>
      {badge_html(a.get('category', '其他'))}
      <span class="primary-cat">{fmt_primary_cat(p.get('primary_category',''))}</span>
    </div>
    <h2><a href="{abs_url}" target="_blank" rel="noopener">{p['title']}</a></h2>
    <p class="authors">{fmt_authors(p.get('authors', []))}</p>
    <p class="highlight">{p.get('highlight', '')}</p>
    <p class="brief">{a.get('brief', '')}</p>
    <div class="section-label">核心优势</div>
    <ul class="advantages">{adv_html}</ul>
    <div class="section-label">应用场景</div>
    <ul class="scenarios">{scen_html}</ul>
    <div class="why"><strong>为什么值得读：</strong>{a.get('why_matters','')}</div>
    <div class="links">
      <a href="{abs_url}" target="_blank" rel="noopener">📄 Abstract</a>
      <a href="{pdf_url}" target="_blank" rel="noopener">📥 PDF</a>
      <a href="{html_url}" target="_blank" rel="noopener">🌐 HTML</a>
    </div>
  </article>"""


def render_index_html(payload: dict) -> str:
    papers = payload["selected"]
    selected_count = len(papers)
    total_candidates = payload.get("count", selected_count)
    date = payload["date"]

    # 分类统计
    cats = Counter()
    for p in papers:
        c = (p.get("analysis") or {}).get("category", "其他 / 探索")
        cats[c] += 1
    category_stats = " · ".join(
        f"{cat} <strong>{n}</strong>" for cat, n in cats.most_common(4)
    )

    cards = "\n\n".join(render_card(p) for p in papers)
    return HTML.format(
        date=date,
        total_candidates=total_candidates,
        selected_count=selected_count,
        category_stats=category_stats,
        cards=cards,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


def render_archive_html() -> str:
    """历史索引页：列出所有 reports/*.html"""
    REPORTS.mkdir(parents=True, exist_ok=True)
    files = sorted(REPORTS.glob("*.html"), reverse=True)
    rows = []
    for f in files:
        date = f.stem
        rows.append(
            f'<li><a href="reports/{f.name}">{date}</a></li>'
        )
    body = "\n".join(rows) if rows else "<li>暂无历史报告</li>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>arXiv 每日精选 · 历史归档</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; color: #1f2328; background: #fff; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #0d1117; color: #e6edf3; }}
    a {{ color: #58a6ff !important; }}
  }}
  h1 {{ font-size: 24px; }}
  ul {{ list-style: none; padding: 0; }}
  li {{ padding: 10px 0; border-bottom: 1px solid #eaeef2; }}
  @media (prefers-color-scheme: dark) {{ li {{ border-bottom-color: #21262d; }} }}
  a {{ color: #0969da; text-decoration: none; font-size: 16px; font-family: ui-monospace, monospace; }}
  a:hover {{ text-decoration: underline; }}
  p.back {{ margin-top: 32px; color: #59636e; font-size: 13px; }}
  p.back a {{ color: inherit; }}
</style>
</head>
<body>
<h1>arXiv 每日精选 · 历史归档</h1>
<p>共 {len(files)} 份报告</p>
<ul>
{body}
</ul>
<p class="back">← <a href="index.html">回到今日</a></p>
</body>
</html>
"""


def main() -> int:
    SITE.mkdir(exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    src = DATA / f"papers_{today}.json"
    if not src.exists():
        print(f"ERROR: {src} not found — run fetch_papers.py + analyze.py first")
        return 1
    payload = json.loads(src.read_text())

    # 1. 今日 index.html
    index_html = render_index_html(payload)
    (SITE / "index.html").write_text(index_html)
    print(f"✓ wrote site/index.html ({len(index_html)} bytes)")

    # 2. 单日报告 reports/<date>.html（内容同 index，方便分享）
    (REPORTS / f"{today}.html").write_text(index_html)
    print(f"✓ wrote site/reports/{today}.html")

    # 3. archive.html
    archive_html = render_archive_html()
    (SITE / "archive.html").write_text(archive_html)
    print(f"✓ wrote site/archive.html")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
