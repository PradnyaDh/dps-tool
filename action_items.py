#!/usr/bin/env python3
"""
Logistics Customer — Open Action Items
======================================
Fetches postmortems from Confluence for Logistics Customer services,
extracts mid/long-term open action items (immediate actions excluded),
and optionally writes a Google Doc report.

Usage:
    python3 action_items.py [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--no-doc]

Defaults:
    --from  2025-01-01
    --to    today
"""

import os, sys, re, json, subprocess, argparse
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__))
from incident_tracker import (
    SERVICES, TEMPLATE_NOISE, CONFLUENCE_BASE, CONF_COOKIE,
    search_confluence, fetch_page_body, is_logistics_org,
    get_postmortem_status, get_docs_service
)
try:
    from slack_notify import send_slack
    _SLACK_AVAILABLE = True
except ImportError:
    _SLACK_AVAILABLE = False

JIRA_BASE = "https://atlassian.cloud.deliveryhero.group"

# Terminal Jira status categories / names — if all tickets in an item are
# in one of these states, we classify the item as completed.
JIRA_DONE_CATEGORIES = {'done'}
JIRA_DONE_NAMES = {
    'done', 'closed', 'rejected', 'cancelled', 'resolved', 'duplicate',
    "won't do", "won't fix", 'wont do', 'wont fix',
}

_jira_cache: dict = {}


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

PAGE_BASE = "https://atlassian.cloud.deliveryhero.group/wiki/spaces/techfoundations/pages"
SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'snapshots')


# ─── CLASSIFIERS ─────────────────────────────────────────────────────────────

def classify_item(item):
    il = item.lower()
    if '✅' in item or '☑' in item or '[x]' in il:
        return 'completed'
    if re.search(r'\b(done|completed|resolved|fixed|closed|merged|deployed|shipped|implemented|added|created|updated|released|addressed|mitigated|hotfixed|reverted|rolled back|rollbacked)\b', il):
        return 'completed'
    # Check Jira ticket statuses when ticket IDs are present
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

    This fixes two bugs:
      1. Parent label not dropped when all its Jira sub-tickets are Done.
      2. Text + inline Jira ref appearing as two duplicate items.
    """
    # Step 1: group text items with their immediately-following bare Jira refs
    groups = []  # list of (text_or_none, [ticket_id, ...])
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
            i = j  # skip consumed Jira sub-refs

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
            if name is None  # can't fetch → treat as open
            or (cat not in JIRA_DONE_CATEGORIES and name not in JIRA_DONE_NAMES)
        ]

        if not open_tix:
            continue  # all tickets done → drop group including parent label

        for tid, summary in open_tix:
            label = (summary or '').strip() or text or tid
            out.append(f"{tid}: {label}")

    # Step 3: deduplicate — drop plain text items whose content matches
    # an enriched Jira item's summary (safety net for any remaining inline cases)
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


def is_real_action_item(item):
    il = item.lower().strip()
    # Incident metadata prefixes — not action items
    if re.search(r'^(status changed|affected component|time to detect|time to acknowledge|time to mitigate|time to graduate|time to verify|time to close|\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', il):
        return False
    # Incident summary/context fields
    if re.search(r'^(scope:|duration:|impact:|severity:|region:|country:|service:|summary:|description:)', il):
        return False
    # Negative impact statements ("No customer impact", "No orders affected")
    if re.search(r'^no (customer|order|user|impact|service|delivery)', il):
        return False
    # Past-tense incident descriptions — describe what happened, not what to do
    if re.search(r'\b(experienced|was (affected|impacted|unavailable|degraded|observed)|resulted in|caused by|handled by|fallback (mechanism|service) (handled|was used))\b', il):
        return False
    # Completed past actions — describes what was already done, not future work
    if re.search(r'\bwas (conducted|changed|deployed|updated|completed|fixed|resolved|used during the incident)\b', il):
        return False
    # Factual/descriptive state — not actionable
    if re.search(r'\bis present[\s:]', il):
        return False
    if re.search(r'\b(has a fallback service|doesn\'t have a fallback|does not have a fallback)\b', il):
        return False
    # Short section/subsection headers — no Jira ticket and no imperative verb
    imperative_verbs = r'^(add|fix|investigate|update|create|improve|introduce|review|evaluate|implement|deploy|migrate|establish|conduct|define|align|avoid|announce|rename|deprecate|strengthen|terminate|increase|consider|begin|allow|analyze|expand|ensure|integrate|enable|move|change|make|set|run|use|check|test|validate|monitor|configure|document|discuss|schedule|plan|prioritize)'
    if (len(item.strip()) < 30
            and not re.search(r'[A-Z][A-Z0-9]+-\d+', item)
            and not re.search(imperative_verbs, il)):
        return False
    if 'do not update' in il or 'incident bot' in il or 'out of sync' in il:
        return False
    if len(item.strip()) < 20:
        return False
    return True


def extract_followup_action_items(html):
    """Extract only mid/long-term action items — immediate section skipped."""
    text = re.sub(r'<br\s*/?>', '\n', html)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'</li>', '\n', text)
    text = re.sub(r'</h[1-6]>', '\n', text)
    text = re.sub(r'</tr>', '\n', text)
    text = re.sub(r'</td>', ' | ', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    for ent, rep in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
                     ('&#39;', "'"), ('&ldquo;', '"'), ('&rdquo;', '"'), ('&rsquo;', "'")]:
        text = text.replace(ent, rep)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n', text).strip()

    lines = text.split('\n')
    items = []
    in_action_section = False
    in_immediate = False
    stop_sections = r'^(incident timeline|appendix|lessons learned|root cause|resolution|detection|executive summary|trigger|five why|what went well|where we got lucky)'
    longterm_headers = r'\b(mid|long.?term|follow.?up|short.?term|next step|preventive|systemic)\b'

    for line in lines:
        line = line.strip()
        if not line:
            continue
        ll = line.lower()
        if re.search(r'action item', ll) and not re.search(r'lessons|timeline|trigger|executive', ll):
            in_action_section = True
            in_immediate = bool(re.search(r'\bimmediate\b', ll))
            continue
        if not in_action_section:
            continue
        if re.search(stop_sections, ll):
            in_action_section = False
            in_immediate = False
            continue
        if len(line) < 120 and re.search(r'immediate', ll):
            in_immediate = True
            continue
        if len(line) < 120 and re.search(longterm_headers, ll):
            in_immediate = False
            continue
        if in_immediate:
            continue
        if len(line) > 15:
            if any(n in ll for n in TEMPLATE_NOISE):
                continue
            if re.search(r'\[.*\]|placeholder|TBD\b', line):
                continue
            items.append(line[:250])

    return items


def extract_incident_date(title):
    m = re.search(r'(\d{4}-\d{2}-\d{2})', title)
    if m:
        try:
            return datetime.strptime(m.group(1), '%Y-%m-%d')
        except:
            pass
    return None


# ─── SLACK ───────────────────────────────────────────────────────────────────

def build_slack_summary(date_from, date_to, svc_summaries, grand_total, incident_count, doc_url=None):
    from_str = date_from.strftime('%Y-%m-%d')
    to_str   = date_to.strftime('%Y-%m-%d')
    lines = [
        f"*Logistics Customer — Open Action Items* ({from_str} → {to_str})",
        f"📋 *{grand_total} open follow-up items* across *{incident_count} incidents*",
        "",
        "*By service:*",
    ]
    for svc, ni, nc in svc_summaries:
        if ni > 0:
            lines.append(f"  • {svc}: {nc} items / {ni} incidents")
    lines.append("")
    lines.append("_Mid/long-term items only · immediate actions excluded · Jira-closed tickets excluded_")
    if doc_url:
        lines.append(f"📄 <{doc_url}|Open Google Doc>")
    return "\n".join(lines)


# ─── SNAPSHOT ────────────────────────────────────────────────────────────────

def save_snapshot(date_from, date_to, svc_open_blocks, svc_summaries, grand_total, incident_count,
                  grand_completed=0, svc_completed_counts=None, snapshot_date=None):
    """Save a dated JSON snapshot for dashboard week-over-week tracking."""
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)
    svc_completed_counts = svc_completed_counts or {}
    snap_date = snapshot_date if snapshot_date else datetime.now().strftime('%Y-%m-%d')
    snapshot = {
        "date": snap_date,
        "from_date": date_from.strftime('%Y-%m-%d'),
        "to_date": date_to.strftime('%Y-%m-%d'),
        "total_open": grand_total,
        "total_completed": grand_completed,
        "total_items": grand_total + grand_completed,
        "incident_count": incident_count,
        "by_service": {
            svc: {
                "incident_count": ni,
                "item_count": nc,
                "completed_count": svc_completed_counts.get(svc, 0),
            }
            for svc, ni, nc in svc_summaries
        },
        "incidents": [
            {
                "id": pid,
                "title": title,
                "service": service,
                "pm_status": pm_status,
                "date": (d := extract_incident_date(title)) and d.strftime('%Y-%m-%d'),
                "items": items,
                "completed_count": inc_completed,
            }
            for service, open_blocks in svc_open_blocks.items()
            for title, pid, pm_status, items, inc_completed in open_blocks
        ],
    }
    out = os.path.join(SNAPSHOTS_DIR, f"{snapshot['date']}.json")
    with open(out, 'w') as f:
        json.dump(snapshot, f, indent=2)
    print(f"Snapshot saved: {out}")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run(date_from, date_to, write_doc=True, snapshot_date=None):
    from_str = date_from.strftime('%Y-%m-%d')
    to_str = date_to.strftime('%Y-%m-%d')
    print(f"Searching Confluence ({from_str} → {to_str})...")

    SERVICES_FILTERED = {
        svc: [q.replace('ORDER BY lastmodified DESC',
                        f'AND created >= "{from_str}" ORDER BY lastmodified DESC') for q in queries]
        for svc, queries in SERVICES.items()
    }

    all_results = {}
    found_ids = {}
    for service, queries in SERVICES_FILTERED.items():
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
                    'id': pid, 'title': r['title'],
                    'pm_status': 'unknown', 'items': [], 'skip': False
                })

    total = sum(len(v) for v in all_results.values())
    print(f"Found {total} incidents. Fetching content and checking Jira ticket statuses...")

    for service, incidents in all_results.items():
        for p in incidents:
            inc_date = extract_incident_date(p['title'])
            if inc_date and not (date_from <= inc_date <= date_to):
                p['skip'] = True
                continue
            html = fetch_page_body(p['id'])
            p['pm_status'] = get_postmortem_status(html)
            p['items'] = extract_followup_action_items(html)

    # Build report
    now = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    lines = []
    lines.append(f"Logistics Customer — Open Follow-up Action Items")
    lines.append(f"Generated: {now} | Period: {from_str} – {to_str}")
    lines.append(f"Filter: Mid/long-term items only (immediate actions excluded), completed items excluded")
    lines.append("")
    lines.append("=" * 70)

    grand_total = 0
    grand_completed = 0
    incident_count = 0
    svc_summaries = []

    svc_open_blocks = {}
    svc_completed_counts = {}
    for service, incidents in all_results.items():
        open_blocks = []
        svc_completed = 0
        for p in incidents:
            if p.get('skip'):
                continue
            raw = [i for i in p['items'] if not any(n in i.lower() for n in TEMPLATE_NOISE)]
            enriched = enrich_items(raw)
            real = [i for i in enriched if is_real_action_item(i)]
            classified = [(i, classify_item(i)) for i in real]
            open_items = [i for i, c in classified if c == 'open']
            inc_completed = sum(1 for i, c in classified if c == 'completed')
            svc_completed += inc_completed
            if open_items:
                open_blocks.append((p['title'], p['id'], p['pm_status'], open_items, inc_completed))
        svc_open_blocks[service] = open_blocks
        svc_completed_counts[service] = svc_completed
        count = sum(len(b[3]) for b in open_blocks)
        grand_total += count
        grand_completed += svc_completed
        incident_count += len(open_blocks)
        svc_summaries.append((service, len(open_blocks), count))

    save_snapshot(date_from, date_to, svc_open_blocks, svc_summaries, grand_total, incident_count,
                  grand_completed, svc_completed_counts, snapshot_date=snapshot_date)

    lines.append("SUMMARY")
    lines.append("=" * 70)
    lines.append(f"  Total open follow-up action items : {grand_total}")
    lines.append(f"  Total incidents with open items   : {incident_count}")
    lines.append("")
    lines.append(f"  {'Service':<40} {'Incidents':>9} {'Items':>6}")
    lines.append(f"  {'-'*40} {'-'*9} {'-'*6}")
    for svc, ni, nc in svc_summaries:
        if ni > 0:
            lines.append(f"  {svc:<40} {ni:>9} {nc:>6}")
    lines.append("")

    for service, open_blocks in svc_open_blocks.items():
        if not open_blocks:
            continue
        count = sum(len(b[3]) for b in open_blocks)
        lines.append("")
        lines.append("=" * 70)
        lines.append(f"{service.upper()}  —  {count} items across {len(open_blocks)} incidents")
        lines.append("=" * 70)
        for title, pid, pm_status, items, *_ in open_blocks:
            link = f"{PAGE_BASE}/{pid}"
            inc_date = extract_incident_date(title)
            date_str = inc_date.strftime('%Y-%m-%d') if inc_date else 'date unknown'
            lines.append("")
            lines.append(f"  [{date_str}] {title}")
            lines.append(f"  Postmortem ({pm_status.upper()}): {link}")
            for item in items:
                lines.append(f"    • {item}")

    doc_text = '\n'.join(lines)
    print(doc_text)

    if write_doc:
        print("\nCreating Google Doc...")
        svc = get_docs_service()
        title = f"Logistics Open Action Items — {datetime.now().strftime('%Y-%m-%d')}"
        doc = svc.documents().create(body={"title": title}).execute()
        doc_id = doc["documentId"]
        end_idx = svc.documents().get(documentId=doc_id).execute()['body']['content'][-1]['endIndex'] - 1
        svc.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": end_idx}, "text": doc_text}}]}
        ).execute()
        doc_url = f"https://docs.google.com/document/d/{doc_id}"
        print(f"\nGoogle Doc: {doc_url}")
        _try_slack(date_from, date_to, svc_summaries, grand_total, incident_count, doc_url)
        return doc_url

    _try_slack(date_from, date_to, svc_summaries, grand_total, incident_count)
    return None


def _try_slack(date_from, date_to, svc_summaries, grand_total, incident_count, doc_url=None):
    if not _SLACK_AVAILABLE:
        return
    try:
        msg = build_slack_summary(date_from, date_to, svc_summaries, grand_total, incident_count, doc_url)
        send_slack(msg)
        print("Slack summary sent.")
    except Exception as e:
        print(f"Slack notification skipped: {e}")


def build_markdown(date_from, date_to, svc_open_blocks, svc_summaries, grand_total, incident_count):
    from_str = date_from.strftime('%Y-%m-%d')
    to_str = date_to.strftime('%Y-%m-%d')
    now = datetime.now().strftime('%Y-%m-%d %H:%M UTC')
    md = []
    md.append(f"# Logistics Customer — Open Follow-up Action Items")
    md.append(f"")
    md.append(f"**Generated:** {now}  ")
    md.append(f"**Period:** {from_str} – {to_str}  ")
    md.append(f"**Filter:** Mid/long-term items only (immediate actions excluded), completed items excluded")
    md.append(f"")
    md.append(f"---")
    md.append(f"")
    md.append(f"## Summary")
    md.append(f"")
    md.append(f"| Service | Incidents | Items |")
    md.append(f"|---------|----------:|------:|")
    for svc, ni, nc in svc_summaries:
        if ni > 0:
            md.append(f"| {svc} | {ni} | {nc} |")
    md.append(f"| **Total** | **{incident_count}** | **{grand_total}** |")
    md.append(f"")

    for service, open_blocks in svc_open_blocks.items():
        if not open_blocks:
            continue
        count = sum(len(b[3]) for b in open_blocks)
        md.append(f"---")
        md.append(f"")
        md.append(f"## {service}  —  {count} items across {len(open_blocks)} incidents")
        md.append(f"")
        for title, pid, pm_status, items, *_ in open_blocks:
            link = f"{PAGE_BASE}/{pid}"
            inc_date = extract_incident_date(title)
            date_str = inc_date.strftime('%Y-%m-%d') if inc_date else 'date unknown'
            md.append(f"### [{date_str}] {title}")
            md.append(f"")
            md.append(f"**Postmortem ({pm_status.upper()}):** {link}")
            md.append(f"")
            for item in items:
                md.append(f"- {item}")
            md.append(f"")

    return '\n'.join(md)


def run_and_collect(date_from, date_to):
    """Run analysis and return structured data for reuse (markdown, doc, etc.)."""
    from_str = date_from.strftime('%Y-%m-%d')
    to_str = date_to.strftime('%Y-%m-%d')

    SERVICES_FILTERED = {
        svc: [q.replace('ORDER BY lastmodified DESC',
                        f'AND created >= "{from_str}" ORDER BY lastmodified DESC') for q in queries]
        for svc, queries in SERVICES.items()
    }

    all_results = {}
    found_ids = {}
    for service, queries in SERVICES_FILTERED.items():
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
                    'id': pid, 'title': r['title'],
                    'pm_status': 'unknown', 'items': [], 'skip': False
                })

    for service, incidents in all_results.items():
        for p in incidents:
            inc_date = extract_incident_date(p['title'])
            if inc_date and not (date_from <= inc_date <= date_to):
                p['skip'] = True
                continue
            html = fetch_page_body(p['id'])
            p['pm_status'] = get_postmortem_status(html)
            p['items'] = extract_followup_action_items(html)

    svc_open_blocks = {}
    svc_completed_counts = {}
    svc_summaries = []
    grand_total = 0
    grand_completed = 0
    incident_count = 0

    for service, incidents in all_results.items():
        open_blocks = []
        svc_completed = 0
        for p in incidents:
            if p.get('skip'):
                continue
            raw = [i for i in p['items'] if not any(n in i.lower() for n in TEMPLATE_NOISE)]
            enriched = enrich_items(raw)
            real = [i for i in enriched if is_real_action_item(i)]
            classified = [(i, classify_item(i)) for i in real]
            open_items = [i for i, c in classified if c == 'open']
            inc_completed = sum(1 for i, c in classified if c == 'completed')
            svc_completed += inc_completed
            if open_items:
                open_blocks.append((p['title'], p['id'], p['pm_status'], open_items, inc_completed))
        svc_open_blocks[service] = open_blocks
        svc_completed_counts[service] = svc_completed
        count = sum(len(b[3]) for b in open_blocks)
        grand_total += count
        grand_completed += svc_completed
        incident_count += len(open_blocks)
        svc_summaries.append((service, len(open_blocks), count))

    return svc_open_blocks, svc_summaries, grand_total, incident_count, grand_completed, svc_completed_counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--from', dest='date_from', default='2025-01-01', help='Start date YYYY-MM-DD')
    parser.add_argument('--to', dest='date_to', default=datetime.now().strftime('%Y-%m-%d'), help='End date YYYY-MM-DD')
    parser.add_argument('--no-doc', action='store_true', help='Skip Google Doc creation')
    parser.add_argument('--md', action='store_true', help='Write markdown file')
    parser.add_argument('--snapshot-date', dest='snapshot_date', default=None, help='Override snapshot filename date YYYY-MM-DD')
    args = parser.parse_args()
    date_from = datetime.strptime(args.date_from, '%Y-%m-%d')
    date_to = datetime.strptime(args.date_to, '%Y-%m-%d')

    if args.md:
        from_str = date_from.strftime('%Y-%m-%d')
        to_str = date_to.strftime('%Y-%m-%d')
        print(f"Searching Confluence ({from_str} → {to_str})...")
        print(f"Found incidents. Fetching content and checking Jira ticket statuses...")
        svc_open_blocks, svc_summaries, grand_total, incident_count, grand_completed, svc_completed_counts = run_and_collect(date_from, date_to)
        save_snapshot(date_from, date_to, svc_open_blocks, svc_summaries, grand_total, incident_count,
                      grand_completed, svc_completed_counts, snapshot_date=args.snapshot_date)
        md_text = build_markdown(date_from, date_to, svc_open_blocks, svc_summaries, grand_total, incident_count)
        out_file = os.path.join(os.path.dirname(__file__), f"open_action_items_{date_from.strftime('%Y-%m-%d')}_to_{date_to.strftime('%Y-%m-%d')}.md")
        with open(out_file, 'w') as f:
            f.write(md_text)
        print(f"\nMarkdown file: {out_file}")
        print(f"Total open items: {grand_total} across {incident_count} incidents")
    else:
        run(
            date_from=date_from,
            date_to=date_to,
            write_doc=not args.no_doc,
            snapshot_date=args.snapshot_date,
        )
