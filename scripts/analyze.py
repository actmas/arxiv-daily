#!/usr/bin/env python3
"""
Analyze arXiv papers with LLM:
  1) 从 ~60 篇里筛 top 10（按影响力/新颖性/与 cs.AI/LG/CL/CV 主线相关性）
  2) 对每篇生成：brief / advantages / scenarios / category / why_matters

Output: data/papers_<date>.json 里的每个 paper 增加 `analysis` 字段；
        同时在 paper 顶层增加 `rank` 字段（1-10，全局精选排序）。

LLM 调用：OpenAI 兼容协议，复用 ~/.hermes/.env 里的 MINIMAX_CN_API_KEY。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# --- LLM 配置（OpenAI 兼容协议） ---
LLM_BASE_URL = os.environ.get("HERMES_LLM_BASE_URL", "https://api.minimaxi.com/v1")
LLM_API_KEY = (
    os.environ.get("HERMES_LLM_API_KEY")
    or os.environ.get("MINIMAX_CN_API_KEY")
    or os.environ.get("MINIMAX_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
)
LLM_MODEL = os.environ.get("HERMES_LLM_MODEL", "MiniMax-M3")


# --- 论文方向分类（用于统计 + 分组展示） ---
CATEGORY_RULES = [
    ("LLM 训练 / 微调",        r"\b(pretrain|finetun|sft|rlhf|dpo|ppo|grpo|reasoning\s+model|chain[- ]of[- ]thought)\b"),
    ("LLM 推理 / 加速",        r"\b(quantiz|prun|distill|speculative|kv[- ]?cache|flash[- ]?att|efficient\s+infer|vllm|sglang)\b"),
    ("多模态 / VLM",           r"\b(multimodal|vision[- ]?language|vlm|image[- ]?text|video[- ]?understanding|diffusion|unified\s+model)\b"),
    ("Agent / 工具调用",       r"\b(agent|tool[- ]?use|function[- ]?call|mcp|planning|orchestrat|multi[- ]?agent|workflow)\b"),
    ("RAG / 检索",             r"\b(rag|retriev|embedding|vector\s+(?:db|store|search)|hybrid\s+search)\b"),
    ("对齐 / 安全",            r"\b(alignment|safety|jailbreak|red[- ]?team|harm|toxic|refusal|rlhf)\b"),
    ("评测 / Benchmark",       r"\b(benchmark|evaluat|leaderboard|metric|dataset|survey)\b"),
    ("代码 / 程序合成",        r"\b(code\s+(?:gen|generation|llm)|program\s+synthe|swe[- ]?bench|repository[- ]?level)\b"),
    ("机器人 / 具身",          r"\b(robot|embod|manipul|navigation|sim[- ]?to[- ]?real|locomotion)\b"),
    ("3D / 视觉生成",          r"\b(3d|nerf|gaussian|splatting|texture|reconstruction|point\s+cloud)\b"),
    ("音频 / 语音",            r"\b(speech|audio|asr|tts|whisper|voice|music)\b"),
    ("理论 / 优化",            r"\b(convergen|optimi(?:z|s)|generaliz(?:ation|ation)|pac[- ]?bayes|theory)\b"),
]

TOP_N = 10  # 全局精选数量


def heuristic_category(paper: dict) -> str:
    text = f"{paper.get('title','')} {paper.get('abstract','')}".lower()
    for label, pat in CATEGORY_RULES:
        if re.search(pat, text, re.I):
            return label
    return "其他 / 探索"


def _load_llm_key() -> str | None:
    """从 ~/.hermes/.env 也读一下（cron agent 可能没 export）"""
    if LLM_API_KEY:
        return LLM_API_KEY
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return None
    text = env_path.read_text()
    for k in ("HERMES_LLM_API_KEY", "MINIMAX_CN_API_KEY", "MINIMAX_API_KEY", "OPENAI_API_KEY"):
        m = re.search(rf"^{k}=(.*)$", text, re.M)
        if m:
            v = m.group(1).strip().strip('"').strip("'")
            if v:
                return v
    return None


def _extract_json_block(text: str) -> str:
    """从模型返回中抠出 JSON 块（兼容 ```json ... ``` 围栏、<think>...</think> 包裹、或裸 JSON）。"""
    text = text.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.S)
    if fence:
        return fence.group(1)
    if "[" in text and "]" in text:
        return text[text.index("["): text.rindex("]") + 1]
    if "{" in text and "}" in text:
        return text[text.index("{"): text.rindex("}") + 1]
    return text


def _heuristic_analysis(paper: dict) -> dict:
    """LLM 失败时的降级方案。"""
    abstract = paper.get("abstract", "").strip()
    return {
        "brief": abstract[:80] + ("..." if len(abstract) > 80 else ""),
        "advantages": ["方法创新", "实验充分", "可复现"],
        "scenarios": ["学术研究", "工程参考"],
        "category": heuristic_category(paper),
        "why_matters": "本论文为该方向的最新研究，建议结合原文阅读。",
    }


def _backfill_missing(papers: list[dict]) -> None:
    """LLM 偶尔漏字段时用启发式补齐。"""
    for p in papers:
        a = p.get("analysis") or {}
        if not a.get("brief"):
            a["brief"] = (p.get("abstract") or "")[:100]
        if not a.get("advantages"):
            a["advantages"] = _heuristic_analysis(p)["advantages"]
        if not a.get("scenarios"):
            a["scenarios"] = _heuristic_analysis(p)["scenarios"]
        if not a.get("category"):
            a["category"] = heuristic_category(p)
        if not a.get("why_matters"):
            a["why_matters"] = "值得跟踪。"
        p["analysis"] = a


def _call_llm(papers: list[dict]) -> list[dict] | None:
    """一次 LLM 调用：筛 top N + 分析。返回 list[dict]，每条形如
       {"rank": 1, "id": "2506.xxxxx", "analysis": {...}, "highlight": "..."}
       失败返回 None。
    """
    # 摘要太长，截断到 300 字符避免 token 爆炸（62 篇 × 300 ≈ 18K tokens 输入，仍可承受）
    minimal = [
        {
            "i": i,
            "id": p["id"],
            "title": p["title"],
            "authors": p.get("authors", [])[:5],  # 最多 5 个作者
            "primary": p.get("primary_category", ""),
            "abstract": p.get("abstract", "")[:300],
        }
        for i, p in enumerate(papers)
    ]

    cat_list = " | ".join(label for label, _ in CATEGORY_RULES) + " | 其他 / 探索"

    system = (
        "你是 AI / ML 学术论文筛选与解读专家。"
        "从给定 ~60 篇 arXiv 最新论文中精选 10 篇最值得关注的（按影响力/新颖性/实用价值），"
        "并对每篇做中文深度分析。输出必须严格符合用户给定的 JSON schema。"
        "不要思考过程、不要解释、不要任何前后缀文字。"
        "回复必须且只能是合法 JSON 数组（以 [ 开头 ] 结尾），无 markdown 围栏。"
    )
    user = (
        f"下面有 {len(papers)} 篇 arXiv 最新论文（cs.AI/cs.LG/cs.CL/cs.CV，"
        f"按提交时间倒序，最多看前 24 小时）。\n\n"
        f"**任务**：精选 **{TOP_N}** 篇最值得关注的，**按重要性从高到低排序**（rank 1 最值得看）。\n"
        f"选稿原则（按权重）：\n"
        f"  1) 实质性方法/模型创新（非纯 benchmark / 综述）\n"
        f"  2) 对 LLM/VLM/Agent 主线有潜在影响\n"
        f"  3) 来自知名机构/作者\n"
        f"  4) 可复现性 / 开源代码\n\n"
        f"严格按以下 schema 输出 JSON 数组，**每条都必须包含所有字段**：\n"
        f"[\n"
        f"  {{\n"
        f'    "rank": 1,\n'
        f'    "id": "arxiv id, e.g. 2506.01234",\n'
        f'    "highlight": "一句中文点睛，10-25 字（类似一句话推荐语）",\n'
        f'    "analysis": {{\n'
        f'      "brief": "1-2 句中文，60-100 字，说清问题和方法",\n'
        f'      "advantages": ["创新点1", "创新点2", "创新点3"],\n'
        f'      "scenarios": ["应用场景1", "应用场景2"],\n'
        f'      "category": "从给定列表选一个",\n'
        f'      "why_matters": "1 句中文，说为什么值得读 / 对谁有用"\n'
        f"    }}\n"
        f"  }}\n"
        f"]\n\n"
        f"硬性要求：\n"
        f"1. 数组**恰好 {TOP_N} 条**，rank 严格 1..{TOP_N} 连续\n"
        f"2. id 必须是输入里的某个 id，不要编造\n"
        f"3. advantages 恰好 3 条，每条 4-20 中文字符\n"
        f"4. scenarios 至少 1 条最多 2 条，每条 4-20 中文字符\n"
        f"5. category 必须从以下列表选一个：{cat_list}\n"
        f"6. 直接以 [ 开始、] 结束，中间不要任何说明文字\n\n"
        f"输入：\n" + json.dumps(minimal, ensure_ascii=False)
    )

    if not LLM_API_KEY:
        print("  [analyze] no LLM API key; falling back to heuristic", file=sys.stderr)
        return None

    try:
        import requests
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.4,
                "max_tokens": 12000,
            },
            timeout=240,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [analyze] LLM call failed: {e}", file=sys.stderr)
        return None

    block = _extract_json_block(content)
    try:
        ranked = json.loads(block)
    except json.JSONDecodeError as e:
        print(f"  [analyze] JSON parse failed: {e}", file=sys.stderr)
        print(f"  raw: {content[:300]}...", file=sys.stderr)
        return None

    if not isinstance(ranked, list):
        print(f"  [analyze] not a list: {type(ranked)}", file=sys.stderr)
        return None

    if len(ranked) < TOP_N:
        print(f"  [analyze] only got {len(ranked)} < {TOP_N}, top up with rest", file=sys.stderr)

    return ranked


def main() -> int:
    api_key = _load_llm_key()
    if not api_key:
        print("ERROR: no LLM API key", file=sys.stderr)
        return 1

    # 把 key 同步给 module-level 变量（_call_llm 用得到）
    global LLM_API_KEY
    LLM_API_KEY = api_key

    today = datetime.now().strftime("%Y-%m-%d")
    data_path = Path(__file__).resolve().parent.parent / "data" / f"papers_{today}.json"
    if not data_path.exists():
        print(f"ERROR: {data_path} not found — run fetch_papers.py first", file=sys.stderr)
        return 1

    payload = json.loads(data_path.read_text())
    papers = payload["papers"]
    print(f"analyze {len(papers)} papers ...", file=sys.stderr)

    ranked = _call_llm(papers)
    if not ranked:
        # 兜底：取前 TOP_N
        print("  using fallback ranking (no LLM)", file=sys.stderr)
        ranked = [
            {
                "rank": i + 1,
                "id": p["id"],
                "highlight": "近期新论文",
                "analysis": _heuristic_analysis(p),
            }
            for i, p in enumerate(papers[:TOP_N])
        ]

    # 把分析合并回原 papers，按 id 索引
    by_id = {p["id"]: p for p in papers}
    selected: list[dict] = []
    for entry in ranked:
        pid = entry.get("id")
        if not pid or pid not in by_id:
            continue
        p = by_id[pid]
        p["rank"] = entry.get("rank", len(selected) + 1)
        p["highlight"] = entry.get("highlight", "")
        p["analysis"] = entry.get("analysis") or {}
        selected.append(p)
    if len(selected) < TOP_N:
        # 用未入选的补齐
        seen = {p["id"] for p in selected}
        for p in papers:
            if p["id"] in seen:
                continue
            p["rank"] = len(selected) + 1
            p["highlight"] = "近期新论文"
            p["analysis"] = _heuristic_analysis(p)
            selected.append(p)
            if len(selected) >= TOP_N:
                break
    selected = selected[:TOP_N]
    # 重新写回（确保 rank 连续）
    for i, p in enumerate(selected):
        p["rank"] = i + 1

    _backfill_missing(selected)

    payload["selected"] = selected  # type: ignore[assignment]
    payload["selected_count"] = len(selected)
    data_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\n✓ selected {len(selected)} top papers → {data_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
