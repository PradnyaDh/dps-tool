#!/usr/bin/env python3
"""
Logistics Open Action Items — Interactive Dashboard
====================================================
Run: python3 -m streamlit run dashboard.py
"""

import json
import os
import glob
import re
from datetime import datetime, date as date_type

import streamlit as st
import pandas as pd
import plotly.express as px

SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'snapshots')
PAGE_BASE     = "https://atlassian.cloud.deliveryhero.group/wiki/spaces/techfoundations/pages"
JIRA_BASE     = "https://atlassian.cloud.deliveryhero.group/browse"

# Canonical team names shown in the dashboard
SERVICE_COLORS = {
    'Dynamic Pricing Service':   '#d61f26',
    'Delivery Area Service':     '#343b46',
    'Order Tracking Experience': '#83828a',
    'Vendor Availability':       '#b01519',
    'Time Estimation Service':   '#5a5f6b',
    'LAAS':                      '#ea565f',
    'Customer Notification':     '#9d9ca3',
}

# Maps any raw service name from snapshot data → canonical team name
SVC_ABBREV = {
    'Dynamic Pricing Service':   'DPS',
    'Delivery Area Service':     'DAS',
    'Order Tracking Experience': 'OTX',
    'Vendor Availability':       'AVA',
    'Time Estimation Service':   'TES',
}

SERVICE_MAPPING = {
    # Dynamic Pricing
    'DPS / Dynamic Pricing':              'Dynamic Pricing Service',
    'Dynamic Pricing':                    'Dynamic Pricing Service',
    'DPS':                                'Dynamic Pricing Service',
    # Delivery Area Service
    'DAS / Delivery Area Service':        'Delivery Area Service',
    'DAS':                                'Delivery Area Service',
    'pyosrm':                             'Delivery Area Service',
    'pyOSRM':                             'Delivery Area Service',
    # Order Tracking
    'Order Tracking (TAPI/OTX)':          'Order Tracking Experience',
    'Order Tracking':                     'Order Tracking Experience',
    'TAPI':                               'Order Tracking Experience',
    'OTX':                                'Order Tracking Experience',
    # Vendor Availability
    'Vendor Availability (AVA)':          'Vendor Availability',
    'AVA':                                'Vendor Availability',
    'Demand Manager':                     'Vendor Availability',
    'demand manager':                     'Vendor Availability',
    'Demand Optimizer':                   'Vendor Availability',
    'demand optimizer':                   'Vendor Availability',
    'Delay Service':                      'Vendor Availability',
    'delay service':                      'Vendor Availability',
    # Time Estimation
    'Time Estimation (TES)':              'Time Estimation Service',
    'Time Estimation':                    'Time Estimation Service',
    'TES':                                'Time Estimation Service',
}

PM_BADGE = {
    'DONE':      '🟢',
    'COMPLETED': '🟢',
    'IN REVIEW': '🔵',
    'DRAFT':     '🟡',
    'UNKNOWN':   '⚪',
}

# ─── DATA ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_snapshots():
    files = sorted(glob.glob(os.path.join(SNAPSHOTS_DIR, '*.json')))
    out = []
    for f in files:
        try:
            with open(f) as fp:
                out.append(json.load(fp))
        except Exception:
            pass
    return out


def normalize_svc(svc):
    """Map any raw service name to the canonical owning-team name."""
    return SERVICE_MAPPING.get(svc, svc)


def svc_filter_label(svc):
    """Short abbreviation used in the sidebar filter pills."""
    canonical = normalize_svc(svc)
    return SVC_ABBREV.get(canonical, canonical)


def linkify_item(text):
    """Turn LOGDPA-123: description into a clickable Jira link."""
    m = re.match(r'^([A-Z][A-Z0-9]+-\d+):\s*(.*)', text)
    if m:
        ticket, desc = m.group(1), m.group(2)
        return f"[{ticket}]({JIRA_BASE}/{ticket}): {desc}"
    return text


def item_jira_project(text):
    """Return Jira project prefix (e.g. LOGL, LOGDPA) or 'No ticket'."""
    m = re.match(r'^([A-Z][A-Z0-9]+)-\d+', text)
    return m.group(1) if m else 'No ticket'


def incident_age(inc_date_str):
    """Return age in days from incident date to today, or None."""
    if not inc_date_str:
        return None
    try:
        return (date_type.today() - datetime.strptime(inc_date_str, '%Y-%m-%d').date()).days
    except Exception:
        return None


def age_label(days):
    if days is None:
        return '—'
    if days < 30:
        return f'{days}d'
    if days < 365:
        return f'{days // 30}mo {days % 30}d'
    return f'{days // 365}y {(days % 365) // 30}mo'


# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Logistics Customer - Incident Action Items Progress",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #dcdde0;
    border-left: 4px solid #d61f26;
    border-radius: 8px;
    padding: 16px 20px;
    box-shadow: 0 1px 4px rgba(52,59,70,0.08);
}
[data-testid="stMetricLabel"] { color: #83828a !important; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; }
[data-testid="stMetricValue"] { color: #343b46 !important; font-size: 1.8rem; font-weight: 700; }

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 1px solid #dcdde0 !important;
    border-left: 4px solid #343b46 !important;
    border-radius: 8px !important;
    background: #ffffff !important;
    margin-bottom: 10px;
    box-shadow: 0 1px 3px rgba(52,59,70,0.05);
}
[data-testid="stExpander"] summary { color: #343b46 !important; font-weight: 600; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #e8e9ec !important;
    border-right: 1px solid #d0d1d5;
}
[data-testid="stSidebar"] * { color: #343b46 !important; }
[data-testid="stSidebar"] h2 { color: #343b46 !important; font-size: 1rem !important; text-transform: uppercase; letter-spacing: 0.06em; }
/* Text input fields only — not the internal multiselect input */
[data-testid="stSidebar"] [data-testid="stTextInput"] input,
[data-testid="stSidebar"] select {
    background: #ffffff !important;
    color: #343b46 !important;
    border: 1px solid #c8c9cd !important;
    border-radius: 6px !important;
}
/* Multiselect container — transparent so pills sit on sidebar bg */
[data-testid="stSidebar"] [data-baseweb="select"] {
    background: transparent !important;
    border: none !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="input"] {
    background: #ffffff !important;
    border: 1px solid #c8c9cd !important;
    border-radius: 6px !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] input {
    background: transparent !important;
    border: none !important;
}
/* Multiselect tag pills → slate blue, white text */
[data-testid="stSidebar"] [data-baseweb="tag"] {
    background: #364F6B !important;
    border: 1px solid #364F6B !important;
}
[data-testid="stSidebar"] [data-baseweb="tag"] span,
[data-testid="stSidebar"] [data-baseweb="tag"] div,
[data-testid="stSidebar"] [data-baseweb="tag"] p,
[data-testid="stSidebar"] [data-baseweb="tag"] svg { color: #ffffff !important; fill: #ffffff !important; }

/* ── Divider ── */
hr { border-color: #dcdde0 !important; }

/* ── Tabs ── */
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #d61f26 !important;
    border-bottom-color: #d61f26 !important;
    font-weight: 600;
}

/* ── Title: red accent ── */
h1 { color: #d61f26 !important; }

/* ── Caption ── */
[data-testid="stCaptionContainer"] { color: #343b46 !important; font-weight: 500; }

/* ── Changes since last run dataframes ── */
[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

</style>
""", unsafe_allow_html=True)

snapshots = load_snapshots()
if not snapshots:
    st.error("No snapshots found. Run `python3 action_items.py --no-doc` first.")
    st.stop()

latest = snapshots[-1]
prev   = snapshots[-2] if len(snapshots) > 1 else None

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔧 Filters")

    search = st.text_input("🔍 Search", placeholder="alert, redis, fallback…")

    all_services = sorted({inc['service'] for inc in latest['incidents']})
    sel_services = st.multiselect(
        "Service", all_services, default=all_services, format_func=svc_filter_label,
    )

    all_projects = sorted({
        item_jira_project(i)
        for inc in latest['incidents']
        for i in inc['items']
    })
    sel_projects = st.multiselect("Jira Project", all_projects, default=all_projects)

    st.divider()
    st.markdown("## 📅 Date Range")
    inc_dates = [
        datetime.strptime(inc['date'], '%Y-%m-%d').date()
        for inc in latest['incidents'] if inc.get('date')
    ]
    min_date = min(inc_dates) if inc_dates else datetime(2025, 1, 1).date()
    max_date = max(inc_dates) if inc_dates else datetime.now().date()

    dcol1, dcol2 = st.columns(2)
    date_from = dcol1.date_input("From", value=min_date, min_value=min_date, max_value=max_date)
    date_to   = dcol2.date_input("To",   value=max_date, min_value=min_date, max_value=max_date)

    st.divider()
    st.markdown("## 📸 Snapshot")
    snapshot_dates = [s['date'] for s in snapshots]
    selected_date = st.selectbox("View snapshot", snapshot_dates, index=len(snapshot_dates) - 1)
    if selected_date != latest['date']:
        latest = next(s for s in snapshots if s['date'] == selected_date)
        prev   = next((s for s in reversed(snapshots) if s['date'] < selected_date), None)

    st.caption(f"Period: {latest.get('from_date','?')} → {latest.get('to_date','?')}")

# ─── FILTER ──────────────────────────────────────────────────────────────────

def passes(inc, item):
    if inc['service'] not in sel_services:
        return False
    if item_jira_project(item) not in sel_projects:
        return False
    if search and search.lower() not in item.lower() and search.lower() not in inc['title'].lower():
        return False
    if inc.get('date'):
        inc_date = datetime.strptime(inc['date'], '%Y-%m-%d').date()
        if not (date_from <= inc_date <= date_to):
            return False
    return True

visible = [
    {**inc, 'items': [i for i in inc['items'] if passes(inc, i)]}
    for inc in latest['incidents']
]
visible = [inc for inc in visible if inc['items']]

total_shown = sum(len(inc['items']) for inc in visible)

# ─── HEADER ──────────────────────────────────────────────────────────────────

st.title("Logistics Customer - Incident Action Items Progress")
st.caption(
    f"Mid/long-term follow-up items · Immediate actions excluded · "
    f"Jira-closed tickets excluded · Last updated {latest['date']}"
)

# ─── METRICS ─────────────────────────────────────────────────────────────────

filtered_open      = total_shown
filtered_completed = sum(inc.get('completed_count', 0) for inc in visible)
filtered_total     = filtered_open + filtered_completed
prev_total         = (prev.get('total_items', prev['total_open'])) if prev else None
delta_total        = (latest.get('total_items', latest['total_open']) - prev_total) if prev_total is not None else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Items",  filtered_total, delta=delta_total, delta_color="inverse")
c2.metric("Open",         filtered_open)
c3.metric("Completed",    filtered_completed)
c4.metric("Incidents",    len(visible))

st.divider()

# ─── TABS ────────────────────────────────────────────────────────────────────

tab_review, tab_overview, tab_table = st.tabs(["📋 Review", "📊 Overview", "📄 Full Table"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — REVIEW
# ════════════════════════════════════════════════════════════════════════════

with tab_review:
    if not visible:
        st.info("No items match the current filters.")
        st.stop()

    by_svc: dict = {}
    for inc in visible:
        by_svc.setdefault(inc['service'], []).append(inc)

    for service, incidents in by_svc.items():
        n_items = sum(len(inc['items']) for inc in incidents)

        with st.expander(
            f"**{normalize_svc(service)}** &nbsp;·&nbsp; {n_items} items &nbsp;·&nbsp; {len(incidents)} incidents",
            expanded=True,
        ):
            for inc in incidents:
                inc_date  = inc.get('date') or '?'
                pm_status = inc['pm_status'].upper()
                badge     = PM_BADGE.get(pm_status, '⚪')
                link      = f"{PAGE_BASE}/{inc['id']}"
                title     = inc['title'][:80]
                age       = incident_age(inc.get('date'))
                age_str   = f"&nbsp;·&nbsp;🕐 {age_label(age)}" if age is not None else ""

                st.markdown(
                    f"{badge} **[{inc_date}] {title}**"
                    f"&nbsp;&nbsp;<sup>[`{pm_status}`]({link}){age_str}</sup>",
                    unsafe_allow_html=True,
                )

                for item in inc['items']:
                    disp_text = linkify_item(item)
                    st.markdown(f"• {disp_text[:200]}")

                st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════

with tab_overview:
    st.subheader("Items by Service")
    svc_counts: dict = {}
    for inc in visible:
        svc_counts[normalize_svc(inc['service'])] = svc_counts.get(normalize_svc(inc['service']), 0) + len(inc['items'])
    svc_df = pd.DataFrame([
        {'Service': s, 'Items': c} for s, c in svc_counts.items() if c > 0
    ]).sort_values('Items', ascending=True)
    fig = px.bar(svc_df, x='Items', y='Service', orientation='h',
                 color_discrete_sequence=['#364F6B'])
    fig.update_layout(
        showlegend=False, margin=dict(l=0, r=0, t=10, b=0), height=280,
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font_color='#2D3142',
        xaxis=dict(gridcolor='#D6E4F0', zerolinecolor='#D6E4F0'),
        yaxis=dict(gridcolor='#D6E4F0'),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Snapshot progress table ───────────────────────────────────────────
    if len(snapshots) > 1:
        st.divider()
        st.subheader("Progress Over Time")
        snap_counts = []
        for s in snapshots:
            s_open = s_completed = s_incidents = 0
            for inc in s['incidents']:
                if inc['service'] not in sel_services:
                    continue
                if inc.get('date'):
                    inc_date = datetime.strptime(inc['date'], '%Y-%m-%d').date()
                    if not (date_from <= inc_date <= date_to):
                        continue
                filtered_items = [
                    i for i in inc['items']
                    if item_jira_project(i) in sel_projects
                    and (not search or search.lower() in i.lower()
                         or search.lower() in inc['title'].lower())
                ]
                if filtered_items:
                    s_open += len(filtered_items)
                    s_completed += inc.get('completed_count', 0)
                    s_incidents += 1
            snap_counts.append({
                'date': s['date'], 'open': s_open,
                'completed': s_completed, 'total': s_open + s_completed,
                'incidents': s_incidents,
            })

        first, last = snap_counts[0], snap_counts[-1]

        def delta(a, b):
            diff = b - a
            sign = '+' if diff >= 0 else ''
            pct  = f"{sign}{(diff / a * 100):.0f}%" if a else '—'
            return f"{sign}{diff}", pct

        metrics = ['open', 'completed', 'total', 'incidents']
        labels  = {'open': 'Open', 'completed': 'Completed', 'total': 'Total Items', 'incidents': 'Incidents'}
        progress_rows = []
        for m in metrics:
            chg, pct = delta(first[m], last[m])
            progress_rows.append({
                'Metric': labels[m],
                first['date']: first[m],
                last['date']:  last[m],
                'Change': chg,
                '% Change': pct,
            })
        st.dataframe(pd.DataFrame(progress_rows), hide_index=True, use_container_width=True)

    if prev:
        st.subheader("Changes Since Last Run")
        def item_key(inc, i):
            return f"{inc['id']}::{i[:100]}"

        prev_keys = {item_key(inc, i) for inc in prev['incidents'] for i in inc['items']}
        curr_keys = {item_key(inc, i) for inc in latest['incidents'] for i in inc['items']}

        new_items = [
            {'Service': normalize_svc(inc['service']), 'Incident': inc['title'][:65], 'Item': i[:110]}
            for inc in latest['incidents'] for i in inc['items']
            if item_key(inc, i) not in prev_keys
        ]
        resolved_items = [
            {'Service': normalize_svc(inc['service']), 'Incident': inc['title'][:65], 'Item': i[:110]}
            for inc in prev['incidents'] for i in inc['items']
            if item_key(inc, i) not in curr_keys
        ]

        cn, cr = st.columns(2)
        with cn:
            st.markdown(
                f'<div style="background:#343b46;color:#fff;padding:6px 12px;border-radius:6px;'
                f'font-weight:600;margin-bottom:8px;">🆕 New &nbsp;·&nbsp; {len(new_items)}</div>',
                unsafe_allow_html=True,
            )
            if new_items:
                st.dataframe(pd.DataFrame(new_items), hide_index=True, use_container_width=True)
            else:
                st.markdown('<div style="background:#e8e9ec;color:#343b46;padding:8px 12px;border-radius:6px;font-size:0.9rem;">No new items</div>', unsafe_allow_html=True)
        with cr:
            st.markdown(
                f'<div style="background:#343b46;color:#fff;padding:6px 12px;border-radius:6px;'
                f'font-weight:600;margin-bottom:8px;">✅ Resolved &nbsp;·&nbsp; {len(resolved_items)}</div>',
                unsafe_allow_html=True,
            )
            if resolved_items:
                st.dataframe(pd.DataFrame(resolved_items), hide_index=True, use_container_width=True)
            else:
                st.markdown('<div style="background:#e8e9ec;color:#343b46;padding:8px 12px;border-radius:6px;font-size:0.9rem;">No items resolved</div>', unsafe_allow_html=True)

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — FULL TABLE
# ════════════════════════════════════════════════════════════════════════════

with tab_table:
    rows = [
        {
            'Service':      normalize_svc(inc['service']),
            'Date':         inc.get('date') or '',
            'Age (days)':   incident_age(inc.get('date')),
            'Incident':     inc['title'][:80],
            'PM Status':    inc['pm_status'].upper(),
            'Jira Project': item_jira_project(i),
            'Action Item':  i,
            'Postmortem':   f"{PAGE_BASE}/{inc['id']}",
        }
        for inc in visible
        for i in inc['items']
    ]
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(
            df,
            column_config={
                'Postmortem': st.column_config.LinkColumn('Postmortem'),
            },
            hide_index=True,
            use_container_width=True,
            height=600,
        )
        csv = df.to_csv(index=False)
        st.download_button(
            "⬇ Download as CSV",
            data=csv,
            file_name=f"open_action_items_{latest['date']}.csv",
            mime='text/csv',
        )
    else:
        st.info("No items match the current filters.")
