# Incident Action Item Tracker

A tool that scans Confluence postmortems, extracts open follow-up action items, cross-checks Jira ticket status, and surfaces them in a weekly report, interactive dashboard, and Slack summary.

Built for **Logistics Customer** services at Delivery Hero — but designed to be adopted by any team with postmortems in Confluence.

---

## What It Does

- Searches Confluence for postmortems matching your service keywords
- Extracts **mid/long-term** action items only (immediate mitigation steps are excluded)
- Looks up referenced Jira tickets and drops items whose tickets are already Done/Rejected/Closed
- Handles the Confluence postmortem structure: parent labels with Jira sub-bullets are resolved as a group — if all tickets are done, the whole group is dropped
- Groups open items by service and incident, with links to the postmortem
- Saves weekly snapshots for trend tracking
- Serves an interactive Streamlit dashboard to review, search, filter, and mark items
- Sends a Slack summary (webhook or bot token)
- Exports to Google Doc or Markdown

---

## Scripts

| Script | Purpose | Run |
|--------|---------|-----|
| `incident_tracker.py` | Weekly scanner — all action items, new incident detection, Google Doc | `python3 incident_tracker.py` |
| `action_items.py` | On-demand — mid/long-term open items, date-filtered, snapshot saved | `python3 action_items.py [--from] [--to] [--no-doc\|--md]` |
| `dashboard.py` | Interactive Streamlit dashboard | `python3 -m streamlit run dashboard.py` |
| `slack_notify.py` | Send a Slack message (webhook or token) | `python3 slack_notify.py "message"` |

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/PradnyaDh/incident-tracker
cd incident-tracker
pip install google-auth google-api-python-client streamlit pandas plotly
```

### 2. Set up credentials

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

### 3. Run

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
incident-tracker/
├── incident_tracker.py     # Weekly scanner + Google Doc report
├── action_items.py         # On-demand follow-up item analysis
├── dashboard.py            # Streamlit dashboard
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
