#!/usr/bin/env python3
"""
Pricing Team — PR AI Adoption Dashboard
========================================
Run: python3 -m streamlit run pr_ai_dashboard.py
"""

import json
import re
from datetime import datetime, date as date_type

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ─── EMBEDDED DATA ───────────────────────────────────────────────────────────
# Fetched 2026-04-27 via gh CLI (read-only). Re-run fetch_pr_data.py to refresh.

RAW_DATA_PATH = "/tmp/pr_dashboard_data.json"

REPO_LABELS = {
    "logistics-dynamic-pricing-api":       "pricing-api",
    "logistics-dynamic-pricing":           "pricing-admin",
    "logistics-dynamic-pricing-dashboard": "pricing-dashboard",
}

REPO_COLORS = {
    "pricing-api":       "#d61f26",
    "pricing-admin":     "#343b46",
    "pricing-dashboard": "#364F6B",
}

CAT_COLORS = {
    "AI-Generated": "#2ecc71",
    "AI-Assisted":  "#f39c12",
    "Manual":       "#adb5bd",
}

TOOL_COLORS = {
    "Claude":          "#d61f26",
    "Gemini":          "#4285F4",
    "Claude + Gemini": "#9b59b6",
}

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Pricing — PR AI Adoption",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
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
[data-testid="stExpander"] {
    border: 1px solid #dcdde0 !important;
    border-left: 4px solid #343b46 !important;
    border-radius: 8px !important;
    background: #ffffff !important;
    margin-bottom: 10px;
}
[data-testid="stSidebar"] { background: #e8e9ec !important; border-right: 1px solid #d0d1d5; }
[data-testid="stSidebar"] * { color: #343b46 !important; }
[data-testid="stSidebar"] [data-testid="stTextInput"] input { background: #ffffff !important; border: 1px solid #c8c9cd !important; border-radius: 6px !important; }
[data-testid="stSidebar"] [data-baseweb="select"] { background: transparent !important; border: none !important; }
[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="input"] { background: #ffffff !important; border: 1px solid #c8c9cd !important; border-radius: 6px !important; }
[data-testid="stSidebar"] [data-baseweb="select"] input { background: transparent !important; border: none !important; }
[data-testid="stSidebar"] [data-baseweb="tag"] { background: #364F6B !important; border: 1px solid #364F6B !important; }
[data-testid="stSidebar"] [data-baseweb="tag"] span,
[data-testid="stSidebar"] [data-baseweb="tag"] div,
[data-testid="stSidebar"] [data-baseweb="tag"] p,
[data-testid="stSidebar"] [data-baseweb="tag"] svg { color: #ffffff !important; fill: #ffffff !important; }
hr { border-color: #dcdde0 !important; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #d61f26 !important; border-bottom-color: #d61f26 !important; font-weight: 600; }
h1 { color: #d61f26 !important; }
[data-testid="stCaptionContainer"] { color: #343b46 !important; font-weight: 500; }
</style>
""", unsafe_allow_html=True)

# ─── LOAD DATA ───────────────────────────────────────────────────────────────

@st.cache_data
def load_data():
    try:
        with open(RAW_DATA_PATH) as f:
            raw = json.load(f)
    except FileNotFoundError:
        st.error(f"Data file not found at {RAW_DATA_PATH}. Run fetch_pr_data.py first.")
        st.stop()

    rows = []
    for r in raw:
        dt = datetime.fromisoformat(r["date"].replace("Z", "+00:00"))
        rows.append({
            "repo":      REPO_LABELS.get(r["repo"], r["repo"]),
            "pr":        r["pr"],
            "title":     r["title"],
            "author":    r["author"],
            "date":      dt.date(),
            "month":     dt.strftime("%Y-%m"),
            "category":  r["category"],
            "tool":      r["tool"] or "—",
            "url":       r["url"],
        })
    return pd.DataFrame(rows)

df_all = load_data()

# ─── SIDEBAR ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔧 Filters")

    all_repos = sorted(df_all["repo"].unique())
    sel_repos = st.multiselect("Repository", all_repos, default=all_repos,
                               format_func=lambda x: x)

    all_cats = ["AI-Generated", "AI-Assisted", "Manual"]
    sel_cats = st.multiselect("Category", all_cats, default=all_cats)

    all_authors = sorted(df_all["author"].unique())
    sel_authors = st.multiselect("Author", all_authors, default=all_authors)

    st.divider()
    st.markdown("## 📅 Date Range")
    min_date = df_all["date"].min()
    max_date = df_all["date"].max()
    dcol1, dcol2 = st.columns(2)
    date_from = dcol1.date_input("From", value=min_date, min_value=min_date, max_value=max_date)
    date_to   = dcol2.date_input("To",   value=max_date, min_value=min_date, max_value=max_date)

    st.divider()
    st.caption(f"Data as of 2026-04-27 · 3 repos · {len(df_all)} PRs")

# ─── FILTER ──────────────────────────────────────────────────────────────────

df = df_all[
    df_all["repo"].isin(sel_repos) &
    df_all["category"].isin(sel_cats) &
    df_all["author"].isin(sel_authors) &
    (df_all["date"] >= date_from) &
    (df_all["date"] <= date_to)
].copy()

# ─── HEADER ──────────────────────────────────────────────────────────────────

st.title("Pricing Team — PR AI Adoption")
st.caption("Last 100 PRs per repo · logistics-dynamic-pricing-{api, admin, dashboard} · Co-author trailers + commit message signals")

# ─── AGGREGATE METRICS ───────────────────────────────────────────────────────

total      = len(df)
ai_gen     = (df["category"] == "AI-Generated").sum()
ai_assist  = (df["category"] == "AI-Assisted").sum()
manual     = (df["category"] == "Manual").sum()
ai_pct     = round((ai_gen + ai_assist) / total * 100, 1) if total else 0

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total PRs",     total)
c2.metric("AI-Generated",  ai_gen,    delta=f"{round(ai_gen/total*100,1)}%" if total else None, delta_color="off")
c3.metric("AI-Assisted",   ai_assist, delta=f"{round(ai_assist/total*100,1)}%" if total else None, delta_color="off")
c4.metric("Manual",        manual,    delta=f"{round(manual/total*100,1)}%" if total else None, delta_color="off")
c5.metric("Any AI Signal", f"{ai_pct}%")

st.divider()

# ─── TABS ────────────────────────────────────────────────────────────────────

tab_overview, tab_by_repo, tab_authors, tab_timeline, tab_detail = st.tabs(
    ["📊 Overview", "🗂 By Repo", "👤 Authors", "📈 Timeline", "📄 All PRs"]
)

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — OVERVIEW
# ════════════════════════════════════════════════════════════════════════════

with tab_overview:
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Category Breakdown (all repos)")
        cat_counts = df["category"].value_counts().reset_index()
        cat_counts.columns = ["Category", "PRs"]
        cat_counts["Color"] = cat_counts["Category"].map(CAT_COLORS)
        fig = px.pie(
            cat_counts, names="Category", values="PRs",
            color="Category", color_discrete_map=CAT_COLORS,
            hole=0.45,
        )
        fig.update_traces(textposition="outside", textinfo="percent+label")
        fig.update_layout(
            showlegend=False, margin=dict(l=0, r=0, t=10, b=0),
            paper_bgcolor="rgba(0,0,0,0)", font_color="#343b46",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        st.subheader("AI Tool Used (AI-Generated PRs only)")
        ai_df = df[df["category"] == "AI-Generated"]
        if len(ai_df):
            tool_counts = ai_df["tool"].value_counts().reset_index()
            tool_counts.columns = ["Tool", "PRs"]
            fig2 = px.bar(
                tool_counts, x="Tool", y="PRs",
                color="Tool", color_discrete_map=TOOL_COLORS,
                text="PRs",
            )
            fig2.update_traces(textposition="outside")
            fig2.update_layout(
                showlegend=False, margin=dict(l=0, r=0, t=10, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#343b46",
                xaxis=dict(gridcolor="#D6E4F0"), yaxis=dict(gridcolor="#D6E4F0"),
            )
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No AI-Generated PRs in current filter.")

    st.divider()
    st.subheader("Category × Repo Heatmap")
    heat = df.groupby(["repo", "category"]).size().reset_index(name="PRs")
    heat_pivot = heat.pivot(index="repo", columns="category", values="PRs").fillna(0).astype(int)
    for col in ["AI-Generated", "AI-Assisted", "Manual"]:
        if col not in heat_pivot.columns:
            heat_pivot[col] = 0
    heat_pivot = heat_pivot[["AI-Generated", "AI-Assisted", "Manual"]]
    heat_pivot["Total"] = heat_pivot.sum(axis=1)
    heat_pivot["AI %"] = ((heat_pivot["AI-Generated"] + heat_pivot["AI-Assisted"]) / heat_pivot["Total"] * 100).round(1).astype(str) + "%"
    st.dataframe(heat_pivot.reset_index().rename(columns={"repo": "Repository"}),
                 hide_index=True, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — BY REPO
# ════════════════════════════════════════════════════════════════════════════

with tab_by_repo:
    for repo in sorted(df["repo"].unique()):
        rdf = df[df["repo"] == repo]
        n_total = len(rdf)
        n_ai_gen = (rdf["category"] == "AI-Generated").sum()
        n_ai_ass = (rdf["category"] == "AI-Assisted").sum()
        n_manual = (rdf["category"] == "Manual").sum()
        ai_pct_r = round((n_ai_gen + n_ai_ass) / n_total * 100, 1) if n_total else 0

        with st.expander(
            f"**{repo}** &nbsp;·&nbsp; {n_total} PRs &nbsp;·&nbsp; "
            f"🤖 {n_ai_gen} generated &nbsp;·&nbsp; 🟡 {n_ai_ass} assisted &nbsp;·&nbsp; "
            f"⚙️ {n_manual} manual &nbsp;·&nbsp; **{ai_pct_r}% AI**",
            expanded=True,
        ):
            rcol1, rcol2 = st.columns([1, 2])

            with rcol1:
                cat_r = rdf["category"].value_counts().reset_index()
                cat_r.columns = ["Category", "PRs"]
                fig_r = px.bar(
                    cat_r, x="PRs", y="Category", orientation="h",
                    color="Category", color_discrete_map=CAT_COLORS, text="PRs",
                )
                fig_r.update_traces(textposition="outside")
                fig_r.update_layout(
                    showlegend=False, margin=dict(l=0, r=0, t=5, b=0), height=180,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#343b46",
                    xaxis=dict(gridcolor="#D6E4F0"), yaxis=dict(gridcolor="#D6E4F0"),
                )
                st.plotly_chart(fig_r, use_container_width=True)

            with rcol2:
                ai_prs = rdf[rdf["category"].isin(["AI-Generated", "AI-Assisted"])].copy()
                if len(ai_prs):
                    ai_prs = ai_prs.sort_values("date", ascending=False)
                    display = ai_prs[["category", "pr", "title", "author", "tool", "date", "url"]].copy()
                    display["pr"] = display.apply(lambda row: f"[#{row['pr']}]({row['url']})", axis=1)
                    st.dataframe(
                        display[["category", "pr", "title", "author", "tool", "date"]],
                        column_config={
                            "category": st.column_config.TextColumn("Category", width="small"),
                            "pr":       st.column_config.TextColumn("PR"),
                            "title":    st.column_config.TextColumn("Title"),
                            "author":   st.column_config.TextColumn("Author", width="small"),
                            "tool":     st.column_config.TextColumn("Tool", width="small"),
                            "date":     st.column_config.DateColumn("Date", width="small"),
                        },
                        hide_index=True, use_container_width=True, height=160,
                    )
                else:
                    st.info("No AI-attributed PRs in this filter.")


# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — AUTHORS
# ════════════════════════════════════════════════════════════════════════════

with tab_authors:
    st.subheader("PRs by Author × Category")

    author_cat = df.groupby(["author", "category"]).size().reset_index(name="PRs")
    author_total = df.groupby("author").size().reset_index(name="Total")
    author_ai = df[df["category"].isin(["AI-Generated","AI-Assisted"])].groupby("author").size().reset_index(name="AI PRs")
    author_summary = author_total.merge(author_ai, on="author", how="left").fillna(0)
    author_summary["AI PRs"] = author_summary["AI PRs"].astype(int)
    author_summary["AI %"] = (author_summary["AI PRs"] / author_summary["Total"] * 100).round(1)
    author_summary = author_summary.sort_values("AI PRs", ascending=False)

    fig_auth = px.bar(
        author_cat[author_cat["category"].isin(["AI-Generated","AI-Assisted"])],
        x="author", y="PRs", color="category",
        color_discrete_map=CAT_COLORS,
        barmode="stack",
    )
    fig_auth.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=350,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#343b46",
        xaxis=dict(gridcolor="#D6E4F0", tickangle=-35),
        yaxis=dict(gridcolor="#D6E4F0"),
        legend=dict(title=""),
    )
    st.plotly_chart(fig_auth, use_container_width=True)

    st.divider()
    st.subheader("Author Summary Table")
    st.dataframe(
        author_summary.rename(columns={"author": "Author", "Total": "Total PRs"}),
        hide_index=True, use_container_width=True,
        column_config={
            "AI %": st.column_config.NumberColumn("AI %", format="%.1f%%"),
        },
    )


# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — TIMELINE
# ════════════════════════════════════════════════════════════════════════════

with tab_timeline:
    st.subheader("AI-Generated PRs Over Time (all repos)")

    monthly = df[df["category"] == "AI-Generated"].groupby(["month","tool"]).size().reset_index(name="PRs")
    if len(monthly):
        fig_time = px.bar(
            monthly, x="month", y="PRs", color="tool",
            color_discrete_map=TOOL_COLORS, barmode="stack",
            labels={"month": "Month", "tool": "Tool"},
        )
        fig_time.update_layout(
            margin=dict(l=0, r=0, t=10, b=0), height=320,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font_color="#343b46",
            xaxis=dict(gridcolor="#D6E4F0"), yaxis=dict(gridcolor="#D6E4F0"),
            legend=dict(title="Tool"),
        )
        st.plotly_chart(fig_time, use_container_width=True)
    else:
        st.info("No AI-Generated PRs in current filter.")

    st.divider()
    st.subheader("Monthly PR Volume by Category")

    monthly_cat = df.groupby(["month", "category"]).size().reset_index(name="PRs")
    fig_mc = px.bar(
        monthly_cat, x="month", y="PRs", color="category",
        color_discrete_map=CAT_COLORS, barmode="stack",
        labels={"month": "Month", "category": "Category"},
    )
    fig_mc.update_layout(
        margin=dict(l=0, r=0, t=10, b=0), height=320,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font_color="#343b46",
        xaxis=dict(gridcolor="#D6E4F0"), yaxis=dict(gridcolor="#D6E4F0"),
        legend=dict(title=""),
    )
    st.plotly_chart(fig_mc, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — ALL PRs TABLE
# ════════════════════════════════════════════════════════════════════════════

with tab_detail:
    search = st.text_input("🔍 Search title or author", placeholder="leilaplanisi, capping, subscriber…")
    if search:
        mask = (
            df["title"].str.contains(search, case=False, na=False) |
            df["author"].str.contains(search, case=False, na=False)
        )
        df_show = df[mask]
    else:
        df_show = df

    st.caption(f"Showing {len(df_show)} PRs")

    display = df_show[["repo","category","tool","pr","title","author","date","url"]].sort_values("date", ascending=False)
    st.dataframe(
        display,
        column_config={
            "url":      st.column_config.LinkColumn("Link"),
            "category": st.column_config.TextColumn("Category"),
            "tool":     st.column_config.TextColumn("Tool"),
            "repo":     st.column_config.TextColumn("Repo"),
            "date":     st.column_config.DateColumn("Date"),
        },
        hide_index=True, use_container_width=True, height=600,
    )

    csv = display.drop(columns=["url"]).to_csv(index=False)
    st.download_button("⬇ Download CSV", data=csv,
                       file_name="pricing_pr_ai_adoption.csv", mime="text/csv")
