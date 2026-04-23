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
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.express as px

SNAPSHOTS_DIR = os.path.join(os.path.dirname(__file__), 'snapshots')
NOTES_FILE    = os.path.join(os.path.dirname(__file__), 'dashboard_notes.json')
PAGE_BASE     = "https://atlassian.cloud.deliveryhero.group/wiki/spaces/techfoundations/pages"
JIRA_BASE     = "https://atlassian.cloud.deliveryhero.group/browse"

SERVICE_COLORS = {
    'DPS / Dynamic Pricing':       '#e74c3c',
    'DAS / Delivery Area Service': '#e67e22',
    'Order Tracking (TAPI/OTX)':   '#f1c40f',
    'Vendor Availability (AVA)':   '#2ecc71',
    'Time Estimation (TES)':       '#3498db',
    'LAAS':                        '#9b59b6',
    'Customer Notification':       '#1abc9c',
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


def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE) as f:
            return json.load(f)
    return {}


def save_notes(notes):
    with open(NOTES_FILE, 'w') as f:
        json.dump(notes, f, indent=2)


def ikey(incident_id, item_text):
    return f"{incident_id}::{item_text[:100]}"


def svc_short(svc):
    return svc.split(' / ')[0] if ' / ' in svc else svc


def linkify_item(text):
    """Turn LOGDPA-123: description into a clickable Jira link."""
    m = re.match(r'^([A-Z][A-Z0-9]+-\d+):\s*(.*)', text)
    if m:
        ticket, desc = m.group(1), m.group(2)
        return f"[{ticket}]({JIRA_BASE}/{ticket}): {desc}"
    return text


# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Logistics Open Action Items",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

snapshots = load_snapshots()
if not snapshots:
    st.error("No snapshots found. Run `python3 action_items.py --no-doc` first.")
    st.stop()

latest = snapshots[-1]
prev   = snapshots[-2] if len(snapshots) > 1 else None

if 'notes' not in st.session_state:
    st.session_state.notes = load_notes()

notes = st.session_state.notes

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔧 Filters")

    search = st.text_input("🔍 Search", placeholder="alert, redis, fallback…")

    all_services = sorted({inc['service'] for inc in latest['incidents']})
    sel_services = st.multiselect(
        "Service", all_services, default=all_services, format_func=svc_short,
    )

    all_statuses = sorted({inc['pm_status'].upper() for inc in latest['incidents']})
    sel_statuses = st.multiselect("PM Status", all_statuses, default=all_statuses)

    hide_noted = st.checkbox("Hide items marked as noted", value=False)

    st.divider()
    st.markdown("## 📅 Snapshot")
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
    if inc['pm_status'].upper() not in sel_statuses:
        return False
    if search and search.lower() not in item.lower() and search.lower() not in inc['title'].lower():
        return False
    if hide_noted and notes.get(ikey(inc['id'], item), {}).get('noted'):
        return False
    return True

visible = [
    {**inc, 'items': [i for i in inc['items'] if passes(inc, i)]}
    for inc in latest['incidents']
]
visible = [inc for inc in visible if inc['items']]

total_shown    = sum(len(inc['items']) for inc in visible)
noted_count    = sum(1 for inc in latest['incidents'] for i in inc['items']
                     if notes.get(ikey(inc['id'], i), {}).get('noted'))

# ─── HEADER ──────────────────────────────────────────────────────────────────

st.title("Logistics Customer — Open Action Items")
st.caption(
    f"Mid/long-term follow-up items · Immediate actions excluded · "
    f"Jira-closed tickets excluded · Last updated {latest['date']}"
)

# ─── METRICS ─────────────────────────────────────────────────────────────────

delta_total = (latest['total_open'] - prev['total_open']) if prev else None
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Open",   latest['total_open'],   delta=delta_total,  delta_color="inverse")
c2.metric("Showing Now",  total_shown)
c3.metric("Incidents",    len(visible))
c4.metric("Noted / Done", noted_count)
c5.metric("Remaining",    total_shown - noted_count)

st.divider()

# ─── TABS ────────────────────────────────────────────────────────────────────

tab_review, tab_overview, tab_table = st.tabs(["📋 Review", "📊 Overview", "📄 Full Table"])

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — REVIEW  (main tab: go through items service by service)
# ════════════════════════════════════════════════════════════════════════════

with tab_review:
    if not visible:
        st.info("No items match the current filters.")
        st.stop()

    # Group by service
    by_svc: dict = {}
    for inc in visible:
        by_svc.setdefault(inc['service'], []).append(inc)

    for service, incidents in by_svc.items():
        n_items = sum(len(inc['items']) for inc in incidents)
        color   = SERVICE_COLORS.get(service, '#95a5a6')

        with st.expander(
            f"**{svc_short(service)}** &nbsp;·&nbsp; {n_items} items &nbsp;·&nbsp; {len(incidents)} incidents",
            expanded=True,
        ):
            for inc in incidents:
                inc_date  = inc.get('date') or '?'
                pm_status = inc['pm_status'].upper()
                badge     = PM_BADGE.get(pm_status, '⚪')
                link      = f"{PAGE_BASE}/{inc['id']}"
                title     = inc['title'][:80]

                # Incident header
                st.markdown(
                    f"{badge} **[{inc_date}] {title}**"
                    f"&nbsp;&nbsp;<sup>[`{pm_status}`]({link})</sup>",
                    unsafe_allow_html=True,
                )

                noted_in_inc = sum(
                    1 for i in inc['items']
                    if notes.get(ikey(inc['id'], i), {}).get('noted')
                )
                if noted_in_inc:
                    st.caption(f"{noted_in_inc}/{len(inc['items'])} items noted")

                for item in inc['items']:
                    k         = ikey(inc['id'], item)
                    is_noted  = notes.get(k, {}).get('noted', False)
                    disp_text = linkify_item(item)

                    col_chk, col_txt = st.columns([0.03, 0.97])
                    with col_chk:
                        checked = st.checkbox(
                            "", value=is_noted, key=f"chk_{k}",
                            label_visibility="collapsed",
                        )
                        if checked != is_noted:
                            notes.setdefault(k, {})['noted'] = checked
                            save_notes(notes)
                            st.rerun()
                    with col_txt:
                        if is_noted:
                            st.markdown(f"~~{item[:160]}~~")
                        else:
                            st.markdown(f"• {disp_text[:160]}")

                st.markdown("---")

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — OVERVIEW  (charts)
# ════════════════════════════════════════════════════════════════════════════

with tab_overview:
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Items by Service")
        svc_df = pd.DataFrame([
            {'Service': svc_short(s), 'Items': v['item_count']}
            for s, v in latest['by_service'].items() if v['item_count'] > 0
        ]).sort_values('Items', ascending=True)
        fig = px.bar(
            svc_df, x='Items', y='Service', orientation='h',
            color='Service',
            color_discrete_map={svc_short(k): v for k, v in SERVICE_COLORS.items()},
        )
        fig.update_layout(showlegend=False, margin=dict(l=0, r=0, t=10, b=0), height=280)
        st.plotly_chart(fig, use_container_width=True)

    with col_r:
        st.subheader("By PM Status")
        status_counts: dict = {}
        for inc in latest['incidents']:
            s = inc['pm_status'].upper()
            status_counts[s] = status_counts.get(s, 0) + len(inc['items'])
        fig = px.pie(
            values=list(status_counts.values()),
            names=list(status_counts.keys()),
            hole=0.45,
            color_discrete_sequence=['#e67e22', '#3498db', '#2ecc71', '#95a5a6', '#e74c3c'],
        )
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
        st.plotly_chart(fig, use_container_width=True)

    if len(snapshots) > 1:
        st.subheader("Open Items Over Time")
        all_svcs = sorted({s for snap in snapshots for s in snap['by_service']})
        rows = [
            {'Date': snap['date'], 'Service': svc,
             'Items': snap['by_service'].get(svc, {}).get('item_count', 0)}
            for snap in snapshots for svc in all_svcs
        ]
        fig = px.area(
            pd.DataFrame(rows), x='Date', y='Items', color='Service',
            color_discrete_map=SERVICE_COLORS,
        )
        fig.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), height=300,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

    if prev:
        st.subheader("Changes Since Last Run")
        prev_keys = {ikey(inc['id'], i) for inc in prev['incidents'] for i in inc['items']}
        curr_keys = {ikey(inc['id'], i) for inc in latest['incidents'] for i in inc['items']}

        new_items = [
            {'Service': svc_short(inc['service']), 'Incident': inc['title'][:65], 'Item': i[:110]}
            for inc in latest['incidents'] for i in inc['items']
            if ikey(inc['id'], i) not in prev_keys
        ]
        resolved_items = [
            {'Service': svc_short(inc['service']), 'Incident': inc['title'][:65], 'Item': i[:110]}
            for inc in prev['incidents'] for i in inc['items']
            if ikey(inc['id'], i) not in curr_keys
        ]

        cn, cr = st.columns(2)
        with cn:
            st.markdown(f"**🆕 New ({len(new_items)})**")
            if new_items:
                st.dataframe(pd.DataFrame(new_items), hide_index=True, use_container_width=True)
            else:
                st.success("No new items")
        with cr:
            st.markdown(f"**✅ Resolved ({len(resolved_items)})**")
            if resolved_items:
                st.dataframe(pd.DataFrame(resolved_items), hide_index=True, use_container_width=True)
            else:
                st.info("No items resolved")

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — FULL TABLE  (sortable, filterable, exportable)
# ════════════════════════════════════════════════════════════════════════════

with tab_table:
    rows = [
        {
            'Service':     svc_short(inc['service']),
            'Date':        inc.get('date') or '',
            'Incident':    inc['title'][:80],
            'PM Status':   inc['pm_status'].upper(),
            'Action Item': i,
            'Noted':       notes.get(ikey(inc['id'], i), {}).get('noted', False),
            'Postmortem':  f"{PAGE_BASE}/{inc['id']}",
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
                'Noted':      st.column_config.CheckboxColumn('Noted', disabled=True),
            },
            hide_index=True,
            use_container_width=True,
            height=600,
        )
        # Export
        csv = df.drop(columns=['Postmortem']).to_csv(index=False)
        st.download_button(
            "⬇ Download as CSV",
            data=csv,
            file_name=f"open_action_items_{latest['date']}.csv",
            mime='text/csv',
        )
    else:
        st.info("No items match the current filters.")
