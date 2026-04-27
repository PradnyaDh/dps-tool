# DPS Tool

Pricing team internal tooling for Delivery Hero — covering incident action item tracking and PR AI adoption analysis across the logistics dynamic pricing repos.

---

## Tools

### PR AI Adoption Dashboard

Analyses PRs across the pricing repositories and classifies each as **AI-Generated**, **AI-Assisted**, or **Manual** based on Git co-author trailers and commit message signals.

- Detects Claude, Gemini, GitHub Copilot, Amazon Q, Aider, HeroGen, Devin, Roo Code, Cursor, Tabnine, Cody
- Distinguishes formal attribution (machine-generated email trailers → AI-Generated) from informal mentions (keyword in commit message → AI-Assisted)
- Self-contained browser dashboard — no server required, open the HTML file directly
- Covers `logistics-dynamic-pricing-api`, `logistics-dynamic-pricing`, `logistics-dynamic-pricing-dashboard` from Jan 2026

### Incident Action Item Tracker

Scans Confluence postmortems, extracts open follow-up action items, cross-checks Jira ticket status, and surfaces them in a weekly report and interactive dashboard.

- Extracts **mid/long-term** action items only (immediate mitigation steps excluded)
- Drops items whose Jira tickets are already Done/Rejected/Closed
- Saves weekly snapshots for trend tracking
- Sends a Slack summary (webhook or bot token)
- Exports to Google Doc or Markdown

---

## Scripts

| Script | Purpose | Run |
|--------|---------|-----|
| `fetch_pr_data.py` | Fetch PR data from pricing repos via `gh` CLI, output to `/tmp/pr_dashboard_data.json` | `python3 fetch_pr_data.py` |
| `pr_ai_dashboard.html` | Self-contained browser dashboard — open directly in any browser | open `pr_ai_dashboard.html` |
| `pr_ai_dashboard.py` | Streamlit version of the PR AI adoption dashboard | `python3 -m streamlit run pr_ai_dashboard.py` |
| `incident_tracker.py` | Weekly scanner — all action items, new incident detection, Google Doc | `python3 incident_tracker.py` |
| `action_items.py` | On-demand — mid/long-term open items, date-filtered, snapshot saved | `python3 action_items.py [--from] [--to] [--no-doc\|--md]` |
| `dashboard.py` | Incident action items Streamlit dashboard | `python3 -m streamlit run dashboard.py` |
| `slack_notify.py` | Send a Slack message (webhook or token) | `python3 slack_notify.py "message"` |

---

## Quick Start

### PR AI Adoption Dashboard

#### 1. Prerequisites

```bash
# GitHub CLI — needed to fetch PR data
brew install gh
gh auth login

pip install pandas plotly streamlit
```

#### 2. Fetch PR data

```bash
python3 fetch_pr_data.py
# Outputs: /tmp/pr_dashboard_data.json
```

#### 3. View the dashboard

```bash
# Option A — open directly in browser (no server needed)
open pr_ai_dashboard.html

# Option B — Streamlit version
python3 -m streamlit run pr_ai_dashboard.py
```

#### Refreshing data

Re-run `fetch_pr_data.py` whenever you want fresh data, then reload the HTML or restart Streamlit. The HTML has data embedded at build time; re-running the script and reopening the file picks up the latest.

---

### Incident Action Item Tracker

#### 1. Clone and install dependencies

```bash
git clone https://github.com/PradnyaDh/dps-tool
cd dps-tool
pip install google-auth google-api-python-client streamlit pandas plotly
```

#### 2. Set up credentials

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Confluence + Jira session cookie
# Get from browser DevTools → Application → Cookies → cloud.session.token
CONF_COOKIE="cloud.session.token=eyJ..."

# Slack (optional)
SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../xxx"
```

Load it:
```bash
source .env   # or add to ~/.zshrc
```

**Google Docs** (optional — needed only for Doc export):
```bash
gcloud auth application-default login \
  --scopes="https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/drive"
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

#### 3. Run

```bash
# Pull open action items for this year, print to terminal
python3 action_items.py --from 2025-01-01 --no-doc

# Same but write a markdown file
python3 action_items.py --from 2025-01-01 --md

# Full run: print + Google Doc + Slack
python3 action_items.py --from 2025-01-01

# Open the dashboard
python3 -m streamlit run dashboard.py
```

---

## Adapting for Your Team

There are three things to configure in `incident_tracker.py`:

### 1. `SERVICES` — what to search for in Confluence

```python
SERVICES = {
    "Your Service Name": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND '
        f'(title ~ "your-keyword" OR title ~ "YSN") '
        f'ORDER BY lastmodified DESC',
    ],
    "Another Service": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND title ~ "other-keyword" '
        f'ORDER BY lastmodified DESC',
    ],
}
```

Each service can have multiple CQL queries (results are deduplicated). Use Confluence's CQL syntax — `title ~` is a fuzzy contains match.

### 2. `LOGISTICS_ORG_SIGNALS` / `NON_LOGISTICS_SIGNALS` — filter by your org

Postmortem pages contain metadata like `Organization: X`, `Tribe: Y`, `Squad: Z` in the page excerpt. These lists tell the tool which pages belong to your team and which to exclude.

```python
LOGISTICS_ORG_SIGNALS = [
    'organization: your-org',
    'tribe: your-tribe',
    'squad: your-service-a',
    'squad: your-service-b',
]

NON_LOGISTICS_SIGNALS = [
    'organization: other-org',
    'tribe: unrelated-tribe',
]
```

If your postmortems don't use org/tribe/squad fields, you can return `True` from `is_logistics_org()` to include all results.

### 3. `TEMPLATE_NOISE` — filter out postmortem template boilerplate

Any placeholder phrases your postmortem template contains that aren't real action items:

```python
TEMPLATE_NOISE = [
    'write me',
    'select jira',
    'add missing squad',
    'no action items',
    'to reduce likelihood',  # generic template headings
]
```

### 4. Change the Confluence space

```python
CONFLUENCE_SPACE = "YOUR_SPACE_KEY"
```

### 5. Change the page URL base

```python
PAGE_BASE = "https://your-instance.atlassian.net/wiki/spaces/YOUR_SPACE/pages"
```

---

## How It Classifies Action Items

Items are extracted only from the **Action Items** section of the postmortem, and only from the **mid/long-term** sub-section. The immediate actions section is skipped.

An item is classified as **completed** if:
- It contains ✅, ☑, or `[x]`
- Its text contains completion keywords: `done`, `merged`, `deployed`, `resolved`, `fixed`, `implemented`, etc.
- Its referenced Jira tickets (via ticket ID in the text or as sub-bullets) are all in a terminal state: **Done**, **Closed**, **Rejected**, **Cancelled**, **Won't Do**, **Duplicate**

An item is classified as **open** if none of the above apply.

Items that are bare Jira macro embeds (just a ticket ID with no description in the page) are enriched with the ticket's summary from Jira. If the ticket is Done, the item is dropped. If it's open, it appears as `TICKET-123: Jira ticket title`.

---

## Dashboard

Run with:
```bash
python3 -m streamlit run dashboard.py
```

**Review tab** — go through open items service by service, incident by incident. Click the checkbox next to any item to mark it as noted (persisted locally in `dashboard_notes.json`). Jira ticket IDs are clickable links.

**Overview tab** — bar chart by service, PM status breakdown, trend over time, new/resolved items since the previous snapshot.

**Full Table tab** — sortable table of all visible items with CSV export.

**Sidebar** — filter by service, PM status, free-text search across item text and incident titles. Switch between historical snapshots.

Snapshots are saved automatically each time `action_items.py` runs, building up history for trend charts.

---

## Scheduled Weekly Run

```bash
# Edit crontab
crontab -e

# Add: every Monday at 9am
0 9 * * 1 cd /path/to/incident-tracker && source .env && python3 incident_tracker.py >> logs/tracker.log 2>&1
```

---

## Dependencies

```bash
pip install google-auth google-api-python-client streamlit pandas plotly
```

| Package | Used for |
|---------|---------|
| `google-auth` + `google-api-python-client` | Google Docs / Drive export |
| `streamlit` | Dashboard UI |
| `pandas` + `plotly` | Dashboard charts and tables |
| `curl` (system) | Confluence and Jira REST API calls |

---

## File Structure

```
dps-tool/
├── fetch_pr_data.py        # Fetches PRs from GitHub, outputs /tmp/pr_dashboard_data.json
├── pr_ai_dashboard.html    # Self-contained browser dashboard (open directly)
├── pr_ai_dashboard.py      # Streamlit version of the PR AI adoption dashboard
├── incident_tracker.py     # Weekly scanner + Google Doc report
├── action_items.py         # On-demand follow-up item analysis
├── dashboard.py            # Incident action items Streamlit dashboard
├── slack_notify.py         # Slack notification helper
├── .env.example            # Credentials template
├── .env                    # Your credentials (gitignored)
├── snapshots/              # JSON snapshots per run (gitignored)
├── logs/                   # Weekly run logs (gitignored)
└── state.json              # Seen incident IDs (gitignored)
```

---

## Getting Your Confluence Cookie

1. Log in to your Confluence instance in Chrome
2. Open DevTools → Application → Cookies
3. Find `cloud.session.token`
4. Copy the value and set: `CONF_COOKIE="cloud.session.token=<value>"`

The cookie expires every ~30 days. When the tool stops returning results, refresh it.

---

## Contributing

PRs welcome. If you adapt this for your team and add useful features (new output formats, different postmortem structures, etc.), open a PR.
