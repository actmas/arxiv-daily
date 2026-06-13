#!/usr/bin/env python3
"""
Push site/ to the gh-pages branch using a worktree (clean, no destructive
checkouts, no race conditions). Follows the pattern documented in
github-pages-publishing skill.

Reads GH_OWNER and ARXIV_REPO from ~/.hermes/.env and publishes over SSH.
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SITE = PROJECT / "site"
WORKTREE = PROJECT / ".gh-pages-wt"
BRANCH_PAGES = "gh-pages"
BRANCH_MAIN = "main"

# --- Load config from ~/.hermes/.env ---
ENV_FILE = Path.home() / ".hermes" / ".env"
_env_text = ENV_FILE.read_text() if ENV_FILE.exists() else ""


def _envval(key: str, default: str | None = None) -> str | None:
    m = re.search(rf"^{key}=(.*)$", _env_text, re.M)
    return m.group(1).strip().strip('"').strip("'") if m else default


OWNER = _envval("GH_OWNER")
REPO = _envval("ARXIV_REPO") or _envval("GH_REPO")
if not OWNER or not REPO:
    sys.exit("GH_OWNER / ARXIV_REPO not set in ~/.hermes/.env")


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}", file=sys.stderr)
    res = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                         capture_output=True, text=True)
    if res.stdout.strip():
        print("    " + res.stdout.strip().replace("\n", "\n    "), file=sys.stderr)
    if res.returncode != 0 and check:
        print("    STDERR:", res.stderr, file=sys.stderr)
        raise SystemExit(f"command failed (rc={res.returncode}): {' '.join(cmd)}")
    return res


def main() -> str:
    if not (SITE / "index.html").exists():
        sys.exit("no site/index.html — run render_html.py first")

    remote_url = f"git@github.com:{OWNER}/{REPO}.git"

    # 0. Switch to main (in case we're on gh-pages from a previous run)
    _run(["git", "checkout", BRANCH_MAIN], cwd=PROJECT, check=False)

    # 1. Reset remote URL to the SSH target for the current owner/repo
    _run(["git", "remote", "remove", "origin"], cwd=PROJECT, check=False)
    _run(["git", "remote", "add", "origin", remote_url], cwd=PROJECT)

    # 2. Make sure source is committed (so we can branch gh-pages from it)
    status = _run(["git", "status", "--porcelain"], cwd=PROJECT, check=False)
    if status.stdout.strip():
        print("  ⚠ uncommitted source changes — committing", file=sys.stderr)
        _run(["git", "add", "-A"], cwd=PROJECT)
        _run(["git", "commit", "-m", "chore: pre-publish snapshot"], cwd=PROJECT, check=False)

    # 3. Tear down any old worktree / branch
    if WORKTREE.exists():
        _run(["git", "worktree", "remove", "--force", str(WORKTREE)], cwd=PROJECT, check=False)
    _run(["git", "worktree", "prune"], cwd=PROJECT, check=False)
    _run(["git", "branch", "-D", BRANCH_PAGES], cwd=PROJECT, check=False)
    _run(["git", "push", "origin", "--delete", BRANCH_PAGES], cwd=PROJECT, check=False)

    # 4. Create fresh gh-pages worktree (branched from main)
    _run(
        ["git", "worktree", "add", "-B", BRANCH_PAGES, str(WORKTREE), BRANCH_MAIN],
        cwd=PROJECT,
    )

    # 5. Clean the worktree except .git
    for child in WORKTREE.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    # 6. Copy site/* into the worktree
    for src in SITE.iterdir():
        dst = WORKTREE / src.name
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # 7. .nojekyll — critical: skip Jekyll processing
    (WORKTREE / ".nojekyll").write_text("")

    # 8. Stage + commit
    _run(["git", "add", "-A"], cwd=WORKTREE)
    status = _run(["git", "status", "--porcelain"], cwd=WORKTREE, check=False)
    if not status.stdout.strip():
        print("  ⚠ nothing to commit on gh-pages", file=sys.stderr)
    else:
        msg = f"publish: arxiv report {datetime.now().strftime('%Y-%m-%d')}"
        _run(["git", "commit", "-m", msg], cwd=WORKTREE)

    # 9. Push (force is fine — Pages artifact is read-only)
    _run(["git", "push", "origin", BRANCH_PAGES, "--force"], cwd=WORKTREE)

    # 10. Cleanup worktree
    _run(["git", "worktree", "remove", "--force", str(WORKTREE)], cwd=PROJECT, check=False)
    _run(["git", "worktree", "prune"], cwd=PROJECT, check=False)

    pages_url = f"https://{OWNER}.github.io/{REPO}/"
    print(f"\n✓ pushed gh-pages → {pages_url}", file=sys.stderr)
    return pages_url


if __name__ == "__main__":
    print(main())
