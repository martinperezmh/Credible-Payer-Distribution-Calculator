# app.py
import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Payer Day Share Calculator", layout="wide")
st.title("Payer Day Share Calculator (WM, Admin, Combined)")

st.write(
    "Upload a CSV or Excel with columns for the payer and their day counts. "
    "I'll total by payer and compute each payer’s percentage of the overall totals."
)

# ---------- Config / Helpers ----------
# Canonical headers (case-insensitive) with common variants
COL_SYNONYMS = {
    "Primary Payer": [
        "primary payer", "payer", "primarypayer", "primary_payer",
        "payer name", "primary payer name"
    ],
    "WM Days": [
        "wm days", "wm", "withdrawal mgmt days", "withdrawal management days"
    ],
    "Admin Days": [
        "admin days", "administrative days", "admin",
        # Back-compat if older files still say R&B / RB / Residential
        "r&b days", "rb days", "residential days", "res & bed days",
        "residential & bed days", "res & bed"
    ],
}
REQUIRED_CANONICAL = ["Primary Payer", "WM Days", "Admin Days"]

def _normalize_header(h: str) -> str:
    return re.sub(r"\s+", " ", h).strip().lower()

def map_columns(df: pd.DataFrame) -> pd.DataFrame:
    lower_map = {_normalize_header(c): c for c in df.columns}
    resolved = {}
    for canonical, variants in COL_SYNONYMS.items():
        found = None
        for v in variants:
            if v in lower_map:
                found = lower_map[v]
                break
        if found is None:
            # try exact canonical as a variant
            cand = _normalize_header(canonical)
            if cand in lower_map:
                found = lower_map[cand]
        if found is None:
            raise ValueError(
                f"Missing required column for '{canonical}'. "
                f"Headers found: {', '.join(df.columns)}"
            )
        resolved[canonical] = found
    out = df[[resolved[c] for c in REQUIRED_CANONICAL]].copy()
    out.columns = REQUIRED_CANONICAL
    return out

def to_number(s):
    # Handles $, commas, parentheses negatives, blanks
    if pd.isna(s):
        return 0
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    if s == "":
        return 0
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace("$", "").replace(",", "")
    try:
        val = float(s)
        return -val if neg else val
    except ValueError:
        return 0.0

def summarize(df: pd.DataFrame):
    # Fill payer blanks with "Unknown"
    df["Primary Payer"] = (
        df["Primary Payer"].astype(str).str.strip().replace({"": "Unknown", "nan": "Unknown"})
    )
    df["WM Days"] = df["WM Days"].map(to_number)
    df["Admin Days"] = df["Admin Days"].map(to_number)

    grouped = (
        df.groupby("Primary Payer", dropna=False)[["WM Days", "Admin Days"]]
          .sum(numeric_only=True)
          .reset_index()
    )

    total_wm = grouped["WM Days"].sum()
    total_admin = grouped["Admin Days"].sum()

    grouped["WM % of Total"] = (grouped["WM Days"] / total_wm * 100).where(total_wm != 0, 0)
    grouped["Admin % of Total"] = (grouped["Admin Days"] / total_admin * 100).where(total_admin != 0, 0)

    table1 = grouped.copy()
    table1[["WM % of Total", "Admin % of Total"]] = (
        table1[["WM % of Total", "Admin % of Total"]].round(2)
    )

    table2 = grouped[["Primary Payer", "WM Days", "Admin Days"]].copy()
    table2["Total Days"] = table2["WM Days"] + table2["Admin Days"]
    total_combined = table2["Total Days"].sum()
    table2["Total Days %"] = (
        (table2["Total Days"] / total_combined * 100).where(total_combined != 0, 0).round(2)
    )
    table2 = table2[["Primary Payer", "Total Days", "Total Days %"]]

    return table1, table2

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

def to_excel_bytes(t1: pd.DataFrame, t2: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as xw:
        t1.to_excel(xw, sheet_name="WM_Admin_Totals_Shares", index=False)
        t2.to_excel(xw, sheet_name="Combined_Totals_Share", index=False)
        for sheet in ["WM_Admin_Totals_Shares", "Combined_Totals_Share"]:
            ws = xw.sheets[sheet]
            ws.set_column(0, 0, 28)  # Primary Payer
            ws.set_column(1, 10, 16)
    bio.seek(0)
    return bio.read()

# ---------- UI ----------
uploaded = st.file_uploader("Drag & drop CSV/XLSX here (or click to browse)", type=["csv", "xlsx", "xls"])
sort_mode = st.radio("Sort tables by:", ["Primary Payer (A–Z)", "Largest totals first"], horizontal=True, index=1)

if uploaded is None:
    st.info("Waiting for a file…")
else:
    try:
        if uploaded.name.lower().endswith((".xlsx", ".xls")):
            df_raw = pd.read_excel(uploaded)
        else:
            try:
                df_raw = pd.read_csv(uploaded)
            except UnicodeDecodeError:
                uploaded.seek(0)
                df_raw = pd.read_csv(uploaded, encoding="latin1")

        df = map_columns(df_raw)

        st.subheader("Preview")
        st.dataframe(df.head(25), use_container_width=True)

        table1, table2 = summarize(df)

        # Sorting
        if sort_mode == "Largest totals first":
            table1 = table1.sort_values(
                ["WM Days", "Admin Days"], ascending=False, kind="mergesort"
            ).reset_index(drop=True)
            table2 = table2.sort_values(
                "Total Days", ascending=False, kind="mergesort"
            ).reset_index(drop=True)
        else:
            table1 = table1.sort_values("Primary Payer").reset_index(drop=True)
            table2 = table2.sort_values("Primary Payer").reset_index(drop=True)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("WM & Admin Totals and Shares by Primary Payer")
            st.dataframe(table1, use_container_width=True)
            st.download_button(
                label="Download WM/Admin Totals & Shares (CSV)",
                data=to_csv_bytes(table1),
                file_name="payer_wm_admin_totals_and_shares.csv",
                mime="text/csv"
            )

        with col2:
            st.subheader("Combined (WM + Admin) Totals and Share by Primary Payer")
            st.dataframe(table2, use_container_width=True)
            st.download_button(
                label="Download Combined Totals & Share (CSV)",
                data=to_csv_bytes(table2),
                file_name="payer_combined_totals_and_share.csv",
                mime="text/csv"
            )

        st.divider()
        st.subheader("Quick Charts")
        st.caption("Tip: Use the sorting toggle above to change chart order.")
        st.bar_chart(table1.set_index("Primary Payer")[["WM Days", "Admin Days"]])
        st.bar_chart(table2.set_index("Primary Payer")[["Total Days"]])

        st.divider()
        st.subheader("Excel Export (both tables)")
        st.download_button(
            label="Download Excel (2 sheets)",
            data=to_excel_bytes(table1, table2),
            file_name="payer_day_share_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        st.error(f"Error: {e}")
        st.stop()

st.caption(
    "Required fields (case-insensitive): Primary Payer, WM Days, and Admin Days. "
    "Common header variations (including older 'R&B Days') are auto-detected."
)
