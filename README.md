# DPS Tool

PR AI adoption analysis across the logistics dynamic pricing repos at Delivery Hero.

Classifies every PR as **AI-Generated**, **AI-Assisted**, or **Manual** based on Git co-author trailers and commit message signals.

---

## What It Does

- Fetches PRs from `logistics-dynamic-pricing-api`, `logistics-dynamic-pricing`, `logistics-dynamic-pricing-dashboard` via the GitHub CLI
- Detects AI tool usage: Claude, Gemini, GitHub Copilot, Amazon Q, Aider, HeroGen, Devin, Roo Code, Cursor, Tabnine, Cody
- **AI-Generated** — machine-generated co-author email trailer present (e.g. `noreply@anthropic.com`, `gemini-code-assist[bot]`) or PR authored by a bot (HeroGen, Devin, Copilot bot)
- **AI-Assisted** — tool name mentioned in a commit message but no formal trailer (engineer used AI informally)
- **Manual** — no AI signals detected
- Self-contained browser dashboard — open the HTML file directly, no server needed
- Filters to Jan 2026 onwards by default

---

## Scripts

| Script | Purpose | Run |
|--------|---------|-----|
| `fetch_pr_data.py` | Fetch PR + commit data from GitHub, output to `/tmp/pr_dashboard_data.json` | `python3 fetch_pr_data.py` |
| `pr_ai_dashboard.html` | Self-contained browser dashboard (data embedded) | `open pr_ai_dashboard.html` |
| `pr_ai_dashboard.py` | Streamlit version of the dashboard | `python3 -m streamlit run pr_ai_dashboard.py` |

---

## Quick Start

### 1. Prerequisites

```bash
# GitHub CLI — needed to fetch PR data
brew install gh
gh auth login

# Python deps (only needed for the Streamlit version)
pip install pandas plotly streamlit
```

### 2. Fetch PR data

```bash
python3 fetch_pr_data.py
# Outputs: /tmp/pr_dashboard_data.json
# Takes ~5–10 min (fetches commits for every PR)
```

### 3. View the dashboard

```bash
# Option A — open directly in browser (no server needed)
open pr_ai_dashboard.html

# Option B — Streamlit
python3 -m streamlit run pr_ai_dashboard.py
```

### Refreshing data

Re-run `fetch_pr_data.py` whenever you want fresh data. The HTML has data embedded — re-running the script regenerates the file with the latest data, then reopen it in the browser.

---

## Detection Logic

### AI-Generated
Any of:
- Commit contains a formal co-author trailer with a known AI email/bot string
- PR is authored by a bot account

| Tool | Signal |
|------|--------|
| Claude | `noreply@anthropic.com` in commit body |
| Gemini | `gemini-code-assist[bot]` in commit body |
| GitHub Copilot | `github-copilot[bot]` in commit body |
| Amazon Q | `amazonq@amazon.com` in commit body |
| Aider | `aider (https://aider.chat)` in commit body |
| HeroGen | PR author contains `herogen` |
| Devin | PR author contains `devin[bot]` |
| Copilot bot | PR author contains `copilot[bot]` |

### AI-Assisted
Commit message mentions a tool name but no formal trailer:

`claude`, `gemini`, `copilot`, `amazon q`, `codewhisperer`, `roocode`, `cursor ai`, `tabnine`, `sourcegraph cody`

### Manual
No AI signals detected.

---

## File Structure

```
dps-tool/
├── fetch_pr_data.py        # Fetches PRs from GitHub, outputs /tmp/pr_dashboard_data.json
├── pr_ai_dashboard.html    # Self-contained browser dashboard (open directly)
├── pr_ai_dashboard.py      # Streamlit version of the dashboard
├── .gitignore
└── README.md
```

---

## Repos Covered

| Repo | Label |
|------|-------|
| `deliveryhero/logistics-dynamic-pricing-api` | pricing-api |
| `deliveryhero/logistics-dynamic-pricing` | pricing-admin |
| `deliveryhero/logistics-dynamic-pricing-dashboard` | pricing-dashboard |

Data range: Jan 2026 → present (`FROM_DATE` in `fetch_pr_data.py`).
