# app.py (two-file version; auto-rename Res Day columns + robust payer collapse)
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Payer Percentage Calculator", layout="wide")
st.title("Payer Percentage Calculator")

st.write(
    "Upload two **cleaned** CSVs. Each CSV must include **Primary Payer** and day columns.\n\n"
    "- **Res Day (1-30)**, **Res Day (>30)**, **R&B Days** and **Admin Days** are combined as units of service.\n"
    "- This information is gathered from the **Detox Bed Day Report** and the **Inpatient Bed Day Report**"
    "- All Payers that aren't **San Mateo County** or **San Mateo 3.5** are combined and renamed **Third Party** in the Payroll Distribution Summary Table"
)

# ---------- Helpers ----------
REQUIRED_COLS = ["Primary Payer", "R&B Days", "Admin Days"]

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    return df

def harmonize_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Make column names consistent:
       - Res Day (1-30) -> R&B Days
       - Res Day (>30)  -> Admin Days
       Keep Primary Payer as-is (trimmed by normalize_columns).
    """
    col_map = {}
    if "Res Day (1-30)" in df.columns:
        col_map["Res Day (1-30)"] = "R&B Days"
    if "Res Day (>30)" in df.columns:
        col_map["Res Day (>30)"] = "Admin Days"
    df = df.rename(columns=col_map)
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
    # --- Normalize payer values (trim/case-insensitive) and collapse to 3 buckets ---
    df2 = df.copy()

    payer_clean = df2["Primary Payer"].fillna("").astype(str).str.strip()
    payer_lower = payer_clean.str.lower()

    # Default everything to Third Party
    df2["Primary Payer"] = "Third Party"

    # Keep San Mateo County (allowing a few variants)
    keep_smc = payer_lower.isin({
        "san mateo county",
        "san mateo",             # if some files say just "San Mateo"
        "county of san mateo"
    })
    df2.loc[keep_smc, "Primary Payer"] = "San Mateo County"

    # Keep San Mateo 3.5 exactly (case-insensitive, spaces trimmed)
    df2.loc[payer_lower.eq("san mateo 3.5"), "Primary Payer"] = "San Mateo 3.5"

    # --- Group and compute percentages ---
    grouped = (
        df2.groupby("Primary Payer", dropna=False)[["R&B Days", "Admin Days"]]
           .sum()
           .reset_index()
    )

    total_rb = grouped["R&B Days"].sum()
    total_admin = grouped["Admin Days"].sum()

    grouped["R&B % of Total"]   = (grouped["R&B Days"]   / total_rb    * 100) if total_rb else 0
    grouped["Admin % of Total"] = (grouped["Admin Days"] / total_admin * 100) if total_admin else 0

    table1 = grouped.copy()
    table1[["R&B % of Total", "Admin % of Total"]] = table1[["R&B % of Total", "Admin % of Total"]].round(2)

    # --- Summary table with new labels ---
    table2 = grouped[["Primary Payer", "R&B Days", "Admin Days"]].copy()
    table2["Units"] = table2["R&B Days"] + table2["Admin Days"]
    total_units = table2["Units"].sum()
    table2["% of Total Units"] = (table2["Units"] / total_units * 100) if total_units else 0
    table2["% of Total Units"] = table2["% of Total Units"].round(2)
    table2 = table2[["Primary Payer", "Units", "% of Total Units"]]

    table1 = table1.sort_values("Primary Payer").reset_index(drop=True)
    table2 = table2.sort_values("Primary Payer").reset_index(drop=True)
    return table1, table2

def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

# ---------- UI ----------
st.subheader("Upload CSV(s)")
col_u1, col_u2 = st.columns(2)
with col_u1:
    uploaded1 = st.file_uploader("Primary CSV", type=["csv"], key="file1")
with col_u2:
    uploaded2 = st.file_uploader("Optional: Second CSV to combine", type=["csv"], key="file2")

if uploaded1 is None and uploaded2 is None:
    st.info("Waiting for at least one CSV…")
else:
    try:
        dfs = []

        # Read, normalize, harmonize, validate each uploaded file
        for idx, up in enumerate([uploaded1, uploaded2]):
            if up is None:
                continue
            df = pd.read_csv(up)
            df = normalize_columns(df)
            df = harmonize_schema(df)

            # Force the second CSV to "San Mateo 3.5" (per your requirement)
            if idx == 1:
                if "Primary Payer" not in df.columns:
                    df["Primary Payer"] = "San Mateo 3.5"
                else:
                    df["Primary Payer"] = df["Primary Payer"].astype(str)
                    df["Primary Payer"] = "San Mateo 3.5"

            validate_columns(df)
            df = coerce_numeric(df, ["R&B Days", "Admin Days"])
            dfs.append(df)

        if not dfs:
            st.warning("No valid CSVs uploaded.")
            st.stop()

        # Combine all uploaded data
        combined = pd.concat(dfs, ignore_index=True)

        # Previews
        with st.expander("Preview: File 1", expanded=False):
            if uploaded1 is not None:
                st.dataframe(dfs[0].head(25) if len(dfs) >= 1 else pd.DataFrame(), use_container_width=True)
            else:
                st.write("No File 1 uploaded.")

        if uploaded2 is not None:
            with st.expander("Preview: File 2 (forced to 'San Mateo 3.5')", expanded=False):
                df2_view = dfs[1] if uploaded1 is not None and len(dfs) > 1 else dfs[0]
                st.dataframe(df2_view.head(25), use_container_width=True)

        st.subheader("Preview: Combined Data")
        st.dataframe(combined.head(50), use_container_width=True)

        # Summaries (San Mateo County, San Mateo 3.5, Third Party)
        table1, table2 = summarize(combined)

        col1, col2 = st.columns(2)

        with col2:
            st.subheader("Summary Table - Payroll Distribution "
            "(Units of Service by Primary Payer)")
            st.dataframe(table2, use_container_width=True)
            st.download_button(
                label="Download Units & % of Total Units CSV",
                data=to_csv_bytes(table2),
                file_name="payroll_units_and_percent_of_total_units.csv",
                mime="text/csv"
            )

    except Exception as e:
        st.error(f"Error: {e}")
        st.stop()

st.caption(
    "Tip: If your column names differ slightly, they'll be normalized. "
    "If you use 'Res Day (1-30)' and 'Res Day (>30)', they will be mapped to 'R&B Days' and 'Admin Days' automatically. "
    "The second CSV is forced to 'San Mateo 3.5'. In the summary, payers are collapsed to: "
    "'San Mateo County', 'San Mateo 3.5', and 'Third Party'."
)
