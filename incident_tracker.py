#!/usr/bin/env python3
"""
Logistics Customer Incident Action Item Tracker
================================================
Runs weekly to find new and existing incidents for Logistics Customer services,
extracts action items, categorizes them (open vs completed), and writes a
Google Doc report + updates a JSON state file to track what's new each week.

Usage:
    python3 incident_tracker.py

Config:
    Edit CONFIG section below or set environment variables.

Cron (every Monday 9am):
    0 9 * * 1 cd /Users/pradnya.shelar/incident_tracker && python3 incident_tracker.py >> logs/tracker.log 2>&1
"""

import os, sys, json, re, subprocess, urllib.parse
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Auto-load .env from the project directory (no need to `source .env` manually)
_env_file = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _key, _, _val = _line.partition('=')
                _key = _key.removeprefix('export').strip()
                _val = _val.strip().strip('"').strip("'")
                os.environ.setdefault(_key, _val)

# ─── CONFIG ───────────────────────────────────────────────────────────────────

# Confluence session cookie — set via .env or: export CONF_COOKIE="cloud.session.token=eyJ..."
CONF_COOKIE = os.environ.get("CONF_COOKIE", "")

CONFLUENCE_BASE = "https://atlassian.cloud.deliveryhero.group/wiki"
CONFLUENCE_SPACE = "PLATFORM"
PAGE_BASE = f"{CONFLUENCE_BASE}/spaces/techfoundations/pages"

GCLOUD_CREDS_FILE = os.path.expanduser("~/.config/gcloud/pricing_oauth_creds.json")
GCLOUD_QUOTA_PROJECT = "dhub-data-commune"
GCLOUD_SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]

# Folder to create weekly docs in (leave empty to put in root Drive)
GDRIVE_FOLDER_ID = ""

# State file — tracks seen incident IDs to detect new ones each week
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

# Log directory
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")

# ─── SERVICE SEARCH QUERIES ──────────────────────────────────────────────────

SERVICES = {
    "DPS / Dynamic Pricing": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND (title ~ "dynamic pricing" OR title ~ "DPS") ORDER BY lastmodified DESC',
    ],
    "DAS / Delivery Area Service": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND (title ~ "delivery area" OR title ~ "DAS") ORDER BY lastmodified DESC',
    ],
    "Order Tracking (TAPI/OTX)": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND (title ~ "order tracking" OR title ~ "tracking API" OR title ~ "TAPI") ORDER BY lastmodified DESC',
    ],
    "Vendor Availability (AVA)": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND title ~ "vendor availability" ORDER BY lastmodified DESC',
    ],
    "Time Estimation (TES)": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND (title ~ "time estimation" OR title ~ "TES" OR title ~ "estimation service" OR title ~ "time prediction" OR title ~ "PDT" OR title ~ "prep time" OR title ~ "preparation time") ORDER BY lastmodified DESC',
    ],
    "LAAS": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND (title ~ "LAAS" OR title ~ "laas") ORDER BY lastmodified DESC',
    ],
    "Customer Notification": [
        f'type=page AND space="{CONFLUENCE_SPACE}" AND title ~ "customer notification" ORDER BY lastmodified DESC',
    ],
}

LOGISTICS_ORG_SIGNALS = [
    'organization: logistics', 'tribe: customer', 'tribe: logistics',
    'logistics - customer', 'affected platforms logistics',
    'logistics tags', 'squad: dps', 'squad: dynamic', 'squad: das',
    'squad: laas', 'squad: time estimat', 'squad: otx', 'squad: ava',
    'squad: delivery are', 'squad: vendor avail',
]

NON_LOGISTICS_SIGNALS = [
    'organization: q-commerce', 'organization: pandora', 'organization: talabat',
    'organization: fintech', 'organization: efood', 'organization: vendor management',
    'organization: pedidosya', 'organization: datahub', 'tribe: q-commerce',
    'tribe: quick commerce', 'tribe: self-service', 'tribe: workforce',
    'tribe: central fintech', 'tribe: transactions',
]

DONE_STATUSES = {'done', 'published', 'completed', 'inreview', 'in review'}

JIRA_BASE = "https://atlassian.cloud.deliveryhero.group"
JIRA_DONE_CATEGORIES = {'done'}
JIRA_DONE_NAMES = {
    'done', 'closed', 'rejected', 'cancelled', 'resolved', 'duplicate',
    "won't do", "won't fix", 'wont do', 'wont fix',
}
_jira_cache: dict = {}

TEMPLATE_NOISE = [
    'write me', 'select jira', 'improve observab', 'update runbook',
    'add missing squad', 'no action items', 'these issues must be',
    'to reduce likelihood', 'to reduce impact', 'to reduce recovery',
    'mid- and longterm', 'immediate action', 'select jira issues',
    # Table headers / data labels
    'in eur by country', 'estimated known unpaid',
    # Past workarounds taken during incident (not future action items)
    'temporarily to stabilize',
]

# ─── JIRA HELPERS ────────────────────────────────────────────────────────────

def get_jira_status(ticket_id: str):
    """Return (status_name, category_key, summary) for a Jira ticket, or (None, None, None) on error."""
    if ticket_id in _jira_cache:
        return _jira_cache[ticket_id]
    url = f"{JIRA_BASE}/rest/api/3/issue/{ticket_id}?fields=status,summary"
    result = subprocess.run(
        ['curl', '-s', '-H', f'Cookie: {CONF_COOKIE}', '-H', 'Accept: application/json', url],
        capture_output=True, text=True
    )
    try:
        data = json.loads(result.stdout)
        fields = data.get('fields', {})
        status = fields.get('status', {})
        name = status.get('name', '').lower()
        category = status.get('statusCategory', {}).get('key', '').lower()
        summary = fields.get('summary', '')
        _jira_cache[ticket_id] = (name, category, summary)
        return name, category, summary
    except Exception:
        _jira_cache[ticket_id] = (None, None, None)
        return None, None, None


def extract_jira_ids(text: str):
    """Extract Jira ticket IDs (e.g. LOGL-5837, GDP-10490) from text."""
    return re.findall(r'\b([A-Z][A-Z0-9]+-\d+)\b', text)


# ─── CONFLUENCE HELPERS ───────────────────────────────────────────────────────

def conf_get(url):
    result = subprocess.run(
        ['curl', '-s', '-H', f'Cookie: {CONF_COOKIE}', '-H', 'Accept: application/json', url],
        capture_output=True, text=True
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {}


def search_confluence(cql, limit=100):
    url = (f"{CONFLUENCE_BASE}/rest/api/search?limit={limit}&cql="
           + urllib.parse.quote(cql))
    return conf_get(url).get('results', [])


def fetch_page_body(page_id):
    url = f"{CONFLUENCE_BASE}/rest/api/content/{page_id}?expand=body.storage"
    data = conf_get(url)
    return data.get('body', {}).get('storage', {}).get('value', '')


def is_logistics_org(excerpt):
    ex = excerpt.lower()
    if any(s in ex for s in NON_LOGISTICS_SIGNALS):
        return False
    return any(s in ex for s in LOGISTICS_ORG_SIGNALS)


def get_postmortem_status(html):
    text = re.sub(r'<[^>]+>', ' ', html[:3000]).lower()
    for s in ['published', 'done', 'completed', 'inreview', 'in review', 'draft']:
        if s in text:
            return s
    return 'unknown'


# ─── ACTION ITEM EXTRACTION ──────────────────────────────────────────────────

def extract_action_items(html):
    """Extract action item lines from postmortem HTML."""
    text = re.sub(r'<br\s*/?>', '\n', html)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'</li>', '\n', text)
    text = re.sub(r'</h[1-6]>', '\n', text)
    text = re.sub(r'</tr>', '\n', text)
    text = re.sub(r'</td>', ' | ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    for ent, rep in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&#39;', "'")]:
        text = text.replace(ent, rep)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text).strip()

    lines = text.split('\n')
    items = []
    in_section = False
    stop_sections = r'^(incident timeline|appendix|lessons learned|root cause|resolution|detection|executive summary|trigger|five why|what went well|where we got lucky)'

    for line in lines:
        line = line.strip()
        if not line:
            continue
        ll = line.lower()
        if re.search(r'action item', ll) and not re.search(r'lessons|timeline|trigger|executive', ll):
            in_section = True
            continue
        if in_section and re.search(stop_sections, ll):
            in_section = False
        if in_section and len(line) > 15:
            if any(n in ll for n in TEMPLATE_NOISE):
                continue
            if re.search(r'\[.*\]|placeholder|TBD\b', line):
                continue
            items.append(line[:250])

    return items


_BARE_JIRA_RE = re.compile(r'^([A-Z][A-Z0-9]+-\d+)\s+[0-9a-f-]{36}')

def enrich_items(items):
    """
    Process action item lines with awareness of how Confluence postmortems are structured:

    - Text bullet with Jira sub-bullets (or inline Jira via <br/>):
        After HTML stripping these become consecutive lines — text first, then bare Jira refs.
        We group them together. If ALL Jira tickets are Done → drop the whole group.
        If any are open → emit only the open enriched Jira items (no duplicate plain text).

    - Standalone bare Jira ref (no preceding text): enrich with Jira title, drop if Done.

    - Plain text with no associated Jira refs: pass through unchanged.
    """
    # Step 1: group text items with their immediately-following bare Jira refs
    groups = []
    i = 0
    while i < len(items):
        item = items[i].strip()
        m = _BARE_JIRA_RE.match(item)
        if m:
            groups.append((None, [m.group(1)]))
            i += 1
        else:
            jira_ids = []
            j = i + 1
            while j < len(items):
                nm = _BARE_JIRA_RE.match(items[j].strip())
                if nm:
                    jira_ids.append(nm.group(1))
                    j += 1
                else:
                    break
            groups.append((item, jira_ids))
            i = j

    # Step 2: resolve each group
    out = []
    for text, jira_ids in groups:
        if not jira_ids:
            if text:
                out.append(text)
            continue

        ticket_info = [(tid, *get_jira_status(tid)) for tid in jira_ids]

        open_tix = [
            (tid, summary) for tid, name, cat, summary in ticket_info
            if name is None
            or (cat not in JIRA_DONE_CATEGORIES and name not in JIRA_DONE_NAMES)
        ]

        if not open_tix:
            continue  # all tickets done → drop group including parent label

        for tid, summary in open_tix:
            label = (summary or '').strip() or text or tid
            out.append(f"{tid}: {label}")

    # Step 3: deduplicate enriched summaries vs plain text
    enriched_summaries = {
        item.split(': ', 1)[1].lower().strip()
        for item in out
        if re.match(r'^[A-Z][A-Z0-9]+-\d+: ', item)
    }
    return [
        item for item in out
        if re.match(r'^[A-Z][A-Z0-9]+-\d+: ', item)
        or item.lower().strip() not in enriched_summaries
    ]


def classify_item(item):
    """Classify a single action item as completed or open."""
    il = item.lower()
    if '✅' in item or '☑' in item or '[x]' in il:
        return 'completed'
    if re.search(r'\b(done|completed|resolved|fixed|closed|merged|deployed|shipped|implemented|added|created|updated|released|addressed|mitigated|hotfixed|reverted|rolled back|rollbacked)\b', il):
        return 'completed'
    ticket_ids = extract_jira_ids(item)
    if ticket_ids:
        statuses = [get_jira_status(tid) for tid in ticket_ids]
        known = [(name, cat) for name, cat, _ in statuses if name is not None]
        if known and all(
            cat in JIRA_DONE_CATEGORIES or name in JIRA_DONE_NAMES
            for name, cat in known
        ):
            return 'completed'
    return 'open'


# ─── STATE MANAGEMENT ─────────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"seen_ids": {}, "runs": []}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


# ─── GOOGLE DOCS ─────────────────────────────────────────────────────────────

def get_docs_service():
    creds = Credentials.from_authorized_user_file(GCLOUD_CREDS_FILE, GCLOUD_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    creds._quota_project_id = GCLOUD_QUOTA_PROJECT
    return build("docs", "v1", credentials=creds)


def create_doc(title):
    svc = get_docs_service()
    doc = svc.documents().create(body={"title": title}).execute()
    return doc["documentId"], svc


def append_to_doc(svc, doc_id, text):
    doc = svc.documents().get(documentId=doc_id).execute()
    end_idx = doc['body']['content'][-1]['endIndex'] - 1
    svc.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": [{"insertText": {"location": {"index": end_idx}, "text": text}}]}
    ).execute()


# ─── REPORT BUILDER ──────────────────────────────────────────────────────────

def build_report(week_label, all_results, new_ids):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []

    def add(s=""): lines.append(s)

    add(f"Logistics Customer — Incident Action Item Tracker")
    add(f"Week: {week_label} | Generated: {now}")
    add(f"Space: Tech Foundations (PLATFORM) | Services: DPS, DAS, Order Tracking, Vendor Availability, TES, LAAS, Customer Notification")
    add()
    add("━" * 65)
    add("SUMMARY")
    add("━" * 65)

    total_incidents = sum(len(v) for v in all_results.values())
    total_open = total_completed = total_no_items = 0
    new_count = sum(1 for svc in all_results.values() for p in svc if str(p['id']) in new_ids)

    svc_summaries = []
    for service, incidents in all_results.items():
        s_open = s_done = s_none = 0
        for p in incidents:
            clean = enrich_items([i for i in p['items'] if not any(n in i.lower() for n in TEMPLATE_NOISE)])
            if not clean:
                s_none += 1
            else:
                for item in clean:
                    if classify_item(item) == 'completed':
                        s_done += 1
                    else:
                        s_open += 1
        total_open += s_open
        total_completed += s_done
        total_no_items += s_none
        new_in_svc = sum(1 for p in incidents if str(p['id']) in new_ids)
        svc_summaries.append((service, len(incidents), s_open, s_done, s_none, new_in_svc))

    add(f"  Total incidents scanned : {total_incidents}")
    add(f"  NEW this week           : {new_count}")
    add(f"  Open action items       : {total_open}")
    add(f"  Completed action items  : {total_completed}")
    add(f"  Incidents with no items : {total_no_items}")
    add()
    add(f"  {'Service':<35} {'Incidents':>9} {'New':>5} {'Open':>6} {'Done':>6} {'NoItems':>8}")
    add(f"  {'-'*35} {'-'*9} {'-'*5} {'-'*6} {'-'*6} {'-'*8}")
    for service, n, s_open, s_done, s_none, new_in_svc in svc_summaries:
        add(f"  {service:<35} {n:>9} {new_in_svc:>5} {s_open:>6} {s_done:>6} {s_none:>8}")
    add()

    # ── NEW INCIDENTS THIS WEEK ──
    if new_count:
        add("━" * 65)
        add(f"  NEW INCIDENTS THIS WEEK  ({new_count})")
        add("━" * 65)
        for service, incidents in all_results.items():
            new_here = [p for p in incidents if str(p['id']) in new_ids]
            if not new_here:
                continue
            add(f"\n  {service}")
            add("  " + "─" * 50)
            for p in new_here:
                add(f"    [NEW] [{p['id']}] {p['title']}")
                add(f"    Status: {p['pm_status'].upper()} | {PAGE_BASE}/{p['id']}")
                clean = enrich_items([i for i in p['items'] if not any(n in i.lower() for n in TEMPLATE_NOISE)])
                if clean:
                    for item in clean:
                        tag = "✓" if classify_item(item) == 'completed' else "•"
                        add(f"      {tag} {item}")
                else:
                    add("      → No action items recorded")
                add()

    # ── FULL ACTION ITEMS BY SERVICE ──
    add()
    add("━" * 65)
    add("ALL OPEN ACTION ITEMS BY SERVICE")
    add("━" * 65)

    for service, incidents in all_results.items():
        open_blocks = []
        for p in incidents:
            clean = enrich_items([i for i in p['items'] if not any(n in i.lower() for n in TEMPLATE_NOISE)])
            open_items = [i for i in clean if classify_item(i) == 'open']
            if open_items:
                is_new = "🆕 " if str(p['id']) in new_ids else ""
                block = [f"    {is_new}[{p['id']}] {p['title']}",
                         f"    Postmortem: {p['pm_status'].upper()} | {PAGE_BASE}/{p['id']}"]
                for item in open_items:
                    block.append(f"      • {item}")
                open_blocks.append('\n'.join(block))

        if open_blocks:
            add()
            add(f"  {service.upper()} — {len(open_blocks)} incidents with open items")
            add("  " + "─" * 50)
            for b in open_blocks:
                add(b)
                add()

    add()
    add("━" * 65)
    add("COMPLETED ACTION ITEMS")
    add("━" * 65)

    for service, incidents in all_results.items():
        done_blocks = []
        for p in incidents:
            clean = enrich_items([i for i in p['items'] if not any(n in i.lower() for n in TEMPLATE_NOISE)])
            done_items = [i for i in clean if classify_item(i) == 'completed']
            if done_items:
                block = [f"    [{p['id']}] {p['title']}",
                         f"    Postmortem: {p['pm_status'].upper()} | {PAGE_BASE}/{p['id']}"]
                for item in done_items:
                    block.append(f"      ✓ {item}")
                done_blocks.append('\n'.join(block))

        if done_blocks:
            add()
            add(f"  {service.upper()} — {len(done_blocks)} incidents with completed items")
            add("  " + "─" * 50)
            for b in done_blocks:
                add(b)
                add()

    return '\n'.join(lines)


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    week_label = datetime.now().strftime("Week of %Y-%m-%d")
    print(f"[{datetime.now().isoformat()}] Starting incident tracker — {week_label}")

    # Load previous state
    state = load_state()
    seen_ids = set(state.get("seen_ids", {}).keys())

    # ── Step 1: Search Confluence for all matching incidents ──
    print("  Searching Confluence...")
    all_results = {}
    found_ids = {}  # id -> service

    for service, queries in SERVICES.items():
        all_results[service] = []
        for cql in queries:
            results = search_confluence(cql, limit=100)
            for r in results:
                pid = r['content']['id']
                if pid in found_ids:
                    continue
                excerpt = r.get('excerpt', '')
                if not is_logistics_org(excerpt):
                    continue
                found_ids[pid] = service
                all_results[service].append({
                    'id': pid,
                    'title': r['title'],
                    'modified': r.get('friendlyLastModified', ''),
                    'pm_status': 'unknown',
                    'items': [],
                })

    total = sum(len(v) for v in all_results.values())
    print(f"  Found {total} matching incidents. Fetching full content...")

    # ── Step 2: Fetch each page and extract action items ──
    done = 0
    for service, incidents in all_results.items():
        for p in incidents:
            html = fetch_page_body(p['id'])
            p['pm_status'] = get_postmortem_status(html)
            p['items'] = extract_action_items(html)
            done += 1
            if done % 10 == 0:
                print(f"    Fetched {done}/{total}...")

    print(f"  Done fetching. Identifying new incidents...")

    # ── Step 3: Identify new incidents ──
    new_ids = set()
    for pid in found_ids:
        if str(pid) not in seen_ids:
            new_ids.add(str(pid))

    print(f"  New incidents this week: {len(new_ids)}")

    # ── Step 4: Build report ──
    report_text = build_report(week_label, all_results, new_ids)

    # ── Step 5: Write to Google Doc ──
    doc_title = f"Logistics Incidents — Action Items — {datetime.now().strftime('%Y-%m-%d')}"
    print(f"  Creating Google Doc: {doc_title}")
    doc_id, svc = create_doc(doc_title)
    append_to_doc(svc, doc_id, report_text)
    doc_url = f"https://docs.google.com/document/d/{doc_id}"
    print(f"  Doc created: {doc_url}")

    # ── Step 6: Update state ──
    for pid in found_ids:
        state["seen_ids"][str(pid)] = {
            "service": found_ids[pid],
            "first_seen": state["seen_ids"].get(str(pid), {}).get("first_seen", datetime.now().isoformat()),
            "last_seen": datetime.now().isoformat(),
        }
    state["runs"].append({
        "date": datetime.now().isoformat(),
        "week": week_label,
        "total_incidents": total,
        "new_incidents": len(new_ids),
        "doc_url": doc_url,
    })
    save_state(state)

    # ── Summary ──
    total_open = sum(
        1 for svc_incidents in all_results.values()
        for p in svc_incidents
        for i in p['items']
        if classify_item(i) == 'open' and not any(n in i.lower() for n in TEMPLATE_NOISE)
    )
    total_done = sum(
        1 for svc_incidents in all_results.values()
        for p in svc_incidents
        for i in p['items']
        if classify_item(i) == 'completed' and not any(n in i.lower() for n in TEMPLATE_NOISE)
    )

    print()
    print(f"  ✅ Report complete")
    print(f"     Incidents scanned : {total}")
    print(f"     New this week     : {len(new_ids)}")
    print(f"     Open action items : {total_open}")
    print(f"     Completed items   : {total_done}")
    print(f"     Google Doc        : {doc_url}")
    print()

    return doc_url


if __name__ == "__main__":
    main()
