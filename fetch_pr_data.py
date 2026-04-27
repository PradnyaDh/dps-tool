#!/usr/bin/env python3
"""
Fetch PR data from pricing repos (read-only via gh CLI).
Run this to refresh the dashboard data.

Usage: python3 fetch_pr_data.py
Output: /tmp/pr_dashboard_data.json
"""

import json
import subprocess
import sys
from datetime import datetime

REPOS = [
    ("logistics-dynamic-pricing-api",       "deliveryhero/logistics-dynamic-pricing-api"),
    ("logistics-dynamic-pricing",           "deliveryhero/logistics-dynamic-pricing"),
    ("logistics-dynamic-pricing-dashboard", "deliveryhero/logistics-dynamic-pricing-dashboard"),
]

FROM_DATE = "2026-01-01"
OUT_FILE  = "/tmp/pr_dashboard_data.json"


def fetch_prs(repo_slug):
    """Fetch all PRs created >= FROM_DATE via gh CLI (read-only)."""
    print(f"  Fetching PRs from {repo_slug} since {FROM_DATE}...")
    result = subprocess.run(
        [
            "gh", "pr", "list",
            "--repo", repo_slug,
            "--limit", "500",
            "--state", "all",
            "--search", f"created:>={FROM_DATE}",
            "--json", "number,title,author,createdAt,body,url",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: {result.stderr[:200]}", file=sys.stderr)
        return []
    return json.loads(result.stdout)


def fetch_commits(pr_number, repo_slug):
    result = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--repo", repo_slug, "--json", "commits"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout).get("commits", [])
    except Exception:
        return []


# ── Known AI tool signatures ─────────────────────────────────────────────────
#
# FORMAL signals — unambiguous co-author trailers or bot PR authors.
# Presence → AI-Generated.
#
#   Claude Code:    "noreply@anthropic.com" in commit body
#   Gemini:         "gemini-code-assist[bot]" in commit body
#   GitHub Copilot: "github-copilot[bot]" in commit body
#   Amazon Q:       "amazonq@amazon.com" in commit body
#   Aider:          "aider (https://aider.chat)" in commit body
#   HeroGen:        PR author contains "herogen"
#   Devin:          PR author contains "devin[bot]"
#   Copilot bot:    PR author contains "copilot[bot]"
#
# INFORMAL signals — tool name mentioned in commit message, no email trailer.
# Presence → AI-Assisted (engineer worked with AI but left no formal attribution).
#
#   "claude" in commit but no @anthropic.com
#   "gemini" in commit but no gemini-code-assist trailer
#   "copilot" in commit but no copilot[bot] trailer
#   "roocode", "cursor ai", "tabnine", "amazon q", "cody" in commit
#
FORMAL_SIGNATURES = {
    "Claude":    ["noreply@anthropic.com"],
    "Gemini":    ["gemini-code-assist[bot]"],
    "Copilot":   ["github-copilot[bot]", "175728472+github-copilot"],
    "Amazon Q":  ["amazonq@amazon.com", "amazon q developer <"],
    "Aider":     ["aider (https://aider.chat)", "co-authored-by: aider"],
}

INFORMAL_SIGNATURES = {
    "Claude":    ["claude"],
    "Gemini":    ["gemini"],
    "Copilot":   ["copilot"],
    "Amazon Q":  ["amazon q", "codewhisperer"],
    "Roo Code":  ["roocode", "roo-code", "roosai"],
    "Cursor":    ["cursor ai", "cursorai"],
    "Tabnine":   ["tabnine"],
    "Cody":      ["sourcegraph cody", "cody@sourcegraph"],
}

# Bot PR authors → immediately AI-Generated
BOT_AUTHOR_SIGNALS = {
    "HeroGen": ["herogen"],
    "Devin":   ["devin[bot]", "devinai"],
    "Copilot": ["copilot[bot]"],
    "Amazon Q":["amazonq[bot]"],
}


def detect_signals(commits, pr_body, pr_author):
    signals = []
    author_lower = pr_author.lower()

    # Bot PR authors
    for tool, keywords in BOT_AUTHOR_SIGNALS.items():
        if any(kw in author_lower for kw in keywords):
            signals.append(f"PR_AUTHOR:{tool.lower()}")

    for c in commits:
        msg = c.get("messageBody", "") + c.get("messageHeadline", "")
        ml = msg.lower()
        # Capture any commit that mentions a formal or informal AI keyword
        all_keywords = [kw for sig in FORMAL_SIGNATURES.values() for kw in sig] + \
                       [kw for sig in INFORMAL_SIGNATURES.values() for kw in sig]
        if any(kw in ml for kw in all_keywords):
            signals.append(msg[:300])

    body = pr_body or ""
    if any(kw in body.lower() for kw in ["noreply@anthropic.com", "generated with claude", "generated with [claude"]):
        signals.append("PR_BODY:ai_mention")
    return signals


def categorize(signals):
    combined = " ".join(signals).lower()

    # Bot PR author → AI-Generated
    if any(s.lower().startswith("pr_author:") for s in signals):
        return "AI-Generated"

    # Formal co-author trailer present → AI-Generated
    for keywords in FORMAL_SIGNATURES.values():
        if any(kw in combined for kw in keywords):
            return "AI-Generated"

    # Informal mention only → AI-Assisted
    for keywords in INFORMAL_SIGNATURES.values():
        if any(kw in combined for kw in keywords):
            return "AI-Assisted"

    return "Manual"


def detect_tool(signals):
    combined = " ".join(signals).lower()
    found = set()

    # Bot PR authors
    for s in signals:
        if s.lower().startswith("pr_author:"):
            tool = s.split(":")[1].title()
            found.add(tool)

    # Formal signatures
    for tool, keywords in FORMAL_SIGNATURES.items():
        if any(kw in combined for kw in keywords):
            found.add(tool)

    # Informal only (if no formal found for that tool)
    for tool, keywords in INFORMAL_SIGNATURES.items():
        if tool not in found and any(kw in combined for kw in keywords):
            found.add(tool)

    return " + ".join(sorted(found)) if found else None


def main():
    all_prs = []

    for repo_name, repo_slug in REPOS:
        prs = fetch_prs(repo_slug)
        print(f"  Found {len(prs)} PRs")

        for i, pr in enumerate(prs):
            author  = pr.get("author", {}).get("login", "?")
            commits = fetch_commits(pr["number"], repo_slug)
            signals = detect_signals(commits, pr.get("body", ""), author)
            all_prs.append({
                "repo":     repo_name,
                "pr":       pr["number"],
                "title":    pr["title"][:70],
                "author":   author,
                "date":     pr["createdAt"],
                "category": categorize(signals),
                "tool":     detect_tool(signals),
                "url":      pr["url"],
                "signals":  signals,
            })
            if (i + 1) % 20 == 0:
                print(f"    {i+1}/{len(prs)} commits checked...")

        print(f"  Done: {repo_name}")

    with open(OUT_FILE, "w") as f:
        json.dump(all_prs, f, separators=(",", ":"))

    print(f"\nSaved {len(all_prs)} PRs to {OUT_FILE}")

    # Summary
    for repo_name, _ in REPOS:
        repo_prs = [p for p in all_prs if p["repo"] == repo_name]
        dates = sorted(p["date"] for p in repo_prs)
        counts = {c: sum(1 for p in repo_prs if p["category"] == c) for c in ["AI-Generated", "AI-Assisted", "Manual"]}
        print(f"  {repo_name}: {len(repo_prs)} PRs "
              f"({dates[0][:10] if dates else '?'} → {dates[-1][:10] if dates else '?'}) "
              f"| {counts}")


if __name__ == "__main__":
    main()
