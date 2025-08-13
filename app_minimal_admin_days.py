# app.py (minimal version with 'Admin Days')
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Payer Day Share Calculator", layout="wide")
st.title("Payer Day Share Calculator (WM, Admin, Combined)")

st.write(
    "Upload a CSV with columns: **Primary Payer**, **WM Days**, **Admin Days**. "
    "I’ll total by payer and compute each payer’s percentage of the overall totals."
)

# ---------- Helpers ----------
REQUIRED_COLS = ["Primary Payer", "WM Days", "Admin Days"]

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    return df

def validate_columns(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            "Missing required column(s): " + ", ".join(missing) +
            ". Columns found: " + ", ".join(df.columns)
        )

def coerce_numeric(df: pd.DataFrame, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    return df

def summarize(df: pd.DataFrame):
    grouped = (
        df.groupby("Primary Payer", dropna=False)[["WM Days", "Admin Days"]]
          .sum()
          .reset_index()
    )

    total_wm = grouped["WM Days"].sum()
    total_admin = grouped["Admin Days"].sum()

    grouped["WM % of Total"] = (grouped["WM Days"] / total_wm * 100) if total_wm else 0
    grouped["Admin % of Total"] = (grouped["Admin Days"] / total_admin * 100) if total_admin else 0

    table1 = grouped.copy()
    table1[["WM % of Total", "Admin % of Total"]] = table1[["WM % of Total", "Admin % of Total"]].round(2)

    table2 = grouped[["Primary Payer", "WM Days", "Admin Days"]].copy()
    table2["Total Days"] = table2["WM Days"] + table2["Admin Days"]
    total_combined = table2["Total Days"].sum()
    table2["Total Days %"] = (table2["Total Days"] / total_combined * 100) if total_combined else 0
    table2["Total Days %"] = table2["Total Days %"].round(2)
    table2 = table2[["Primary Payer", "Total Days", "Total Days %"]]

    table1 = table1.sort_values("Primary Payer").reset_index(drop=True)
    table2 = table2.sort_values("Primary Payer").reset_index(drop=True)
    return table1, table2

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

# ---------- UI ----------
uploaded = st.file_uploader("Drag & drop your CSV here (or click to browse)", type=["csv"])

if uploaded is None:
    st.info("Waiting for a CSV…")
else:
    try:
        df = pd.read_csv(uploaded)
        df = normalize_columns(df)
        validate_columns(df)
        df = coerce_numeric(df, ["WM Days", "Admin Days"])

        st.subheader("Preview")
        st.dataframe(df.head(25), use_container_width=True)

        table1, table2 = summarize(df)

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("WM & Admin Totals and Shares by Primary Payer")
            st.dataframe(table1, use_container_width=True)
            st.download_button(
                label="Download WM/Admin Totals & Shares CSV",
                data=to_csv_bytes(table1),
                file_name="payer_wm_admin_totals_and_shares.csv",
                mime="text/csv"
            )

        with col2:
            st.subheader("Combined (WM + Admin) Totals and Share by Primary Payer")
            st.dataframe(table2, use_container_width=True)
            st.download_button(
                label="Download Combined Totals & Share CSV",
                data=to_csv_bytes(table2),
                file_name="payer_combined_totals_and_share.csv",
                mime="text/csv"
            )

    except Exception as e:
        st.error(f"Error: {e}")
        st.stop()

st.caption("Tip: If your column names differ slightly, rename them to match the required headers.")
