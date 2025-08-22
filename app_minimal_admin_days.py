# app.py — Detox → 11-col target; Inpatient → 9-col target (keeps Total Days)
# + separate % tables + combined % table + collapsed combined % table
import io
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Palm Avenue Detox (PAD) Bed Day Model Calculator", layout="wide")
st.title("Palm Avenue Detox (PAD) Bed Day Model Calculator")

st.write(
    "Upload the Detox Bed Day Report and Inpatient Bed Day Report CSVs for PAD.\n\n"
)

DETOX_TARGET_COLUMNS = [
    "Primary Payer","Visit Type","Client ID","Episode ID",
    "Service Start Date","Time In","Service End Date","Time Out",
    "WM Days","R&B Days","Admin Days",
]

INPATIENT_TARGET_COLUMNS = [
    "Primary Payer","Service Type","Client ID","Episode ID",
    "Service Start Date","Time In","Service End Date","Time Out","Total Days",
]

# ---------- Helpers ----------
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

def clean_raw_frame(df: pd.DataFrame) -> pd.DataFrame:
    """(Detox) Delete top row; drop rows with any empty/whitespace cell; reset index."""
    df = df.iloc[1:, :]
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(how="any").reset_index(drop=True)
    return df

def clean_after_header(df: pd.DataFrame) -> pd.DataFrame:
    """(Inpatient) Keep the header as-is; drop rows with blanks; normalize header text."""
    df.columns = [str(c).strip() for c in df.columns]
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(how="any").reset_index(drop=True)
    return df

def as_int_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64")

def as_num_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0)

def as_date_str(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")

def _num_clean(s: pd.Series) -> pd.Series:
    # Remove commas/spaces so "1,234" parses correctly
    return pd.to_numeric(s.astype("string").str.replace(",", "", regex=False).str.strip(), errors="coerce")

def find_col(df: pd.DataFrame, name_lower: str):
    """Case/space-insensitive exact header match (e.g., 'total days')."""
    for c in df.columns:
        if str(c).strip().lower() == name_lower:
            return c
    return None

# NEW: rename "San Mateo County" to "San Mateo 3.2" (handles a few variants)
def rename_detox_payer_to_32(df: pd.DataFrame) -> pd.DataFrame:
    if "Primary Payer" not in df.columns:
        return df
    s = df["Primary Payer"].astype("string").str.strip()
    sm_variants = {"san mateo county", "county of san mateo", "san mateo"}
    df["Primary Payer"] = s.where(~s.str.lower().isin(sm_variants), "San Mateo 3.2")
    return df

# ---------- Detox (File 1) → 11-col target ----------
def transform_detox_by_position(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    if len(cols) < 11:
        raise ValueError(f"Expected at least 11 columns for Detox mapping; found {len(cols)}.\nCols: {cols[:15]}")

    payer_col, visit_col, client_col, episode_col = cols[0], cols[1], cols[2], cols[3]
    start_col, time_in_col, end_col, time_out_col = cols[6], cols[7], cols[8], cols[9]
    rb_col, admin_col = cols[-2], cols[-1]

    out = pd.DataFrame({
        "Primary Payer": df[payer_col].astype("string").str.strip(),
        "Visit Type": df[visit_col].astype("string").str.strip(),
        "Client ID": as_int_series(df[client_col]),
        "Episode ID": as_int_series(df[episode_col]),
        "Service Start Date": as_date_str(df[start_col]),
        "Time In": df[time_in_col].astype("string").str.strip(),
        "Service End Date": as_date_str(df[end_col]),
        "Time Out": df[time_out_col].astype("string").str.strip(),
        "WM Days": 0,
        "R&B Days": as_num_series(df[rb_col]).astype(int),
        "Admin Days": as_num_series(df[admin_col]).astype(int),
    })
    return out[DETOX_TARGET_COLUMNS]

# ---------- Inpatient (File 2) → 9-col target; KEEP 'Total Days' from source ----------
def transform_inpatient_to_reference(df: pd.DataFrame, force_primary: bool = True) -> pd.DataFrame:
    cols = list(df.columns)
    if len(cols) < 9:
        raise ValueError(f"Unexpected inpatient column count ({len(cols)}). Columns: {cols[:15]}")

    payer_col, service_col, client_col, episode_col = cols[0], cols[1], cols[2], cols[3]
    start_col, time_in_col, end_col, time_out_col = cols[6], cols[7], cols[8], cols[9]

    # Prefer literal 'Total Days' header; else fallback to last numeric-looking col
    total_days_col = find_col(df, "total days")
    if total_days_col is not None:
        total_days = _num_clean(df[total_days_col]).fillna(0)
        source = f"Total Days col → {total_days_col}"
    else:
        numeric_like = []
        for c in cols:
            vals = _num_clean(df[c])
            if vals.notna().mean() >= 0.7:
                numeric_like.append((c, vals))
        if numeric_like:
            c, vals = numeric_like[-1]
            total_days = vals.fillna(0)
            source = f"Rightmost numeric col → {c}"
        else:
            total_days = pd.Series(0, index=df.index, dtype="float64")
            source = "Fallback zeros"

    primary_payer_series = (
        pd.Series(["San Mateo 3.5"] * len(df), dtype="string")
        if force_primary else df[payer_col].astype("string").str.strip()
    )

    out = pd.DataFrame({
        "Primary Payer": primary_payer_series,
        "Service Type": df[service_col].astype("string").str.strip(),
        "Client ID": as_int_series(df[client_col]),
        "Episode ID": as_int_series(df[episode_col]),
        "Service Start Date": as_date_str(df[start_col]),
        "Time In": df[time_in_col].astype("string").str.strip(),
        "Service End Date": as_date_str(df[end_col]),
        "Time Out": df[time_out_col].astype("string").str.strip(),
        "Total Days": total_days.astype(int),
    })[INPATIENT_TARGET_COLUMNS]

    st.caption(f"Inpatient Total Days source: {source}")
    return out

# ---------- Separate summaries ----------
def summarize_units_by_payer(df_target_11: pd.DataFrame) -> pd.DataFrame:
    """Detox: Units = R&B + Admin."""
    grouped = df_target_11.groupby("Primary Payer", as_index=False)[["R&B Days", "Admin Days"]].sum()
    grouped["Detox Units"] = grouped["R&B Days"] + grouped["Admin Days"]
    total_units = grouped["Detox Units"].sum()
    grouped["% of Detox Units"] = (grouped["Detox Units"] / total_units * 100).round(2) if total_units else 0
    return grouped[["Primary Payer", "Detox Units", "% of Detox Units"]].sort_values("Primary Payer").reset_index(drop=True)

def summarize_total_days_by_payer(df_target_9: pd.DataFrame) -> pd.DataFrame:
    """Inpatient: use the KEPT Total Days column."""
    grouped = df_target_9.groupby("Primary Payer", as_index=False)["Total Days"].sum()
    total_days = grouped["Total Days"].sum()
    grouped["% of Total Days"] = (grouped["Total Days"] / total_days * 100).round(2) if total_days else 0
    return grouped.sort_values("Primary Payer").reset_index(drop=True)

# ---------- Combined summaries ----------
def summarize_combined_by_payer(detox_df: pd.DataFrame | None, inpatient_df: pd.DataFrame | None) -> pd.DataFrame:
    """
    Union of Primary Payers from both files.
    Columns:
      - Detox Units (R&B + Admin)
      - Inpatient Total Days
      - Combined Units = Detox Units + Inpatient Total Days
      - % of Combined
    """
    # Detox part
    if detox_df is not None:
        d = detox_df.groupby("Primary Payer", as_index=False)[["R&B Days", "Admin Days"]].sum()
        d["Detox Units"] = d["R&B Days"] + d["Admin Days"]
        d = d[["Primary Payer", "Detox Units"]]
    else:
        d = pd.DataFrame(columns=["Primary Payer", "Detox Units"])

    # Inpatient part
    if inpatient_df is not None:
        i = inpatient_df.groupby("Primary Payer", as_index=False)[["Total Days"]].sum()
        i = i.rename(columns={"Total Days": "Inpatient Total Days"})
    else:
        i = pd.DataFrame(columns=["Primary Payer", "Inpatient Total Days"])

    # Outer join on Primary Payer, fill missing as 0
    combined = pd.merge(d, i, on="Primary Payer", how="outer").fillna(0)

    # Ensure numeric types
    combined["Detox Units"] = pd.to_numeric(combined["Detox Units"], errors="coerce").fillna(0).astype(int)
    combined["Inpatient Total Days"] = pd.to_numeric(combined["Inpatient Total Days"], errors="coerce").fillna(0).astype(int)

    combined["Combined Units"] = combined["Detox Units"] + combined["Inpatient Total Days"]
    total_combined = combined["Combined Units"].sum()
    combined["% of Combined"] = (combined["Combined Units"] / total_combined * 100).round(2) if total_combined else 0.0

    return combined.sort_values("Primary Payer").reset_index(drop=True)

def summarize_combined_collapsed_by_payer(detox_df: pd.DataFrame | None, inpatient_df: pd.DataFrame | None) -> pd.DataFrame:
    """
    Keep Primary Payers that contain 'San Mateo' (case-insensitive) as-is,
    collapse everything else into 'Third Party'.
    Then compute Detox Units, Inpatient Total Days, Combined Units, and % of Combined.
    """
    base = summarize_combined_by_payer(detox_df, inpatient_df).copy()

    # Collapse Primary Payer into San Mateo (kept) vs Third Party (everything else)
    mask = base["Primary Payer"].astype("string").str.contains("san mateo", case=False, na=False)
    base["Primary Payer"] = base["Primary Payer"].where(mask, "Third Party")

    collapsed = (
        base.groupby("Primary Payer", as_index=False)[["Detox Units", "Inpatient Total Days", "Combined Units"]]
            .sum()
    )
    total = collapsed["Combined Units"].sum()
    collapsed["% of Combined"] = (collapsed["Combined Units"] / total * 100).round(2) if total else 0.0

    return collapsed.sort_values("Primary Payer").reset_index(drop=True)

# ---------- UI ----------
st.subheader("Upload CSV(s)")
col_u1, col_u2 = st.columns(2)
with col_u1:
    uploaded1 = st.file_uploader("**File 1 — Detox Bed Day Report**", type=["csv"], key="file1")
with col_u2:
    uploaded2 = st.file_uploader("**File 2 — Inpatient Bed Day Report**", type=["csv"], key="file2")

if uploaded1 is None and uploaded2 is None:
    st.info("Waiting for at least one CSV…")
else:
    try:
        per_file_downloads = []
        detox_out = None
        inpatient_out = None

        # File 1 — Detox (read normally, then delete first row)
        if uploaded1 is not None:
            st.write(f"**File 1 selected:** {uploaded1.name}")
            raw1 = pd.read_csv(uploaded1, engine="python")
            clean1 = clean_raw_frame(raw1)
            detox_out = transform_detox_by_position(clean1)
            # Rename SMC → 3.2 here
            detox_out = rename_detox_payer_to_32(detox_out)
            with st.expander("Preview: Detox 3.2 Data", expanded=False):
                st.dataframe(detox_out.head(25), use_container_width=True)
            per_file_downloads.append(("Download Detox Data", to_csv_bytes(detox_out), "detox_data_cleaned.csv"))

        # File 2 — Inpatient (READ WITH header=1 to use 2nd line as header; then keep Total Days)
        if uploaded2 is not None:
            st.write(f"**File 2 selected:** {uploaded2.name}")
            raw2 = pd.read_csv(uploaded2, header=1, engine="python")  # key for preserving 'Total Days' header
            clean2 = clean_after_header(raw2)
            inpatient_out = transform_inpatient_to_reference(clean2, force_primary=True)
            with st.expander("Preview: Inpatient 3.5 Data", expanded=False):
                st.dataframe(inpatient_out.head(25), use_container_width=True)
            per_file_downloads.append(("Download Inpatient Data", to_csv_bytes(inpatient_out), "inpatient_data_cleaned.csv"))

        if not per_file_downloads:
            st.warning("No valid CSVs uploaded.")
            st.stop()

        # Download buttons
        cols = st.columns(len(per_file_downloads))
        for c, (label, data, fname) in zip(cols, per_file_downloads):
            with c:
                st.download_button(label=label, data=data, file_name=fname, mime="text/csv")

        # Combined tables across both files
        if (detox_out is not None) or (inpatient_out is not None):
            st.subheader("Percentage Table — Detox Units + Inpatient Units by Primary Payer")
            st.caption("This table shows units of service for each unique payer.")
            combined_table = summarize_combined_by_payer(detox_out, inpatient_out)
            st.dataframe(combined_table, use_container_width=True)
            st.download_button(
                label="Download",
                data=to_csv_bytes(combined_table),
                file_name="summary_combined_by_primary_payer.csv",
                mime="text/csv"
            )

            # Collapsed combined (San Mateo vs Third Party)
            st.subheader("Percentage Table — San Mateo vs Third Party")
            st.caption("This table shows San Mateo 3.2 (San Mateo County), San Mateo 3.5 and Third Party for Payroll purposes.")
            combined_collapsed = summarize_combined_collapsed_by_payer(detox_out, inpatient_out)
            st.dataframe(combined_collapsed, use_container_width=True)
            st.download_button(
                label="Download",
                data=to_csv_bytes(combined_collapsed),
                file_name="summary_combined_sm_thirdparty_payer.csv",
                mime="text/csv"
            )

    except Exception as e:
        st.error(f"Error: {e}")
        st.stop()

st.caption("Place-holder")

# ---------- NEW: ALOS section (Detox) ----------
st.subheader("Average Length of Stay (ALOS)")
st.caption(
    "Upload the Detox CSV again. We'll clean it the same way, convert to the target format, "
    "find the median Service Start Date across all rows, then compute ALOS for rows whose "
    "Service Start Date falls in that month. ALOS is (End - Start) + 1 days (inclusive)."
)

alos_file = st.file_uploader("Upload Detox CSV for ALOS", type=["csv"], key="alos_detox")

def compute_alos_for_median_month(detox_target_df: pd.DataFrame):
    # Parse dates
    df = detox_target_df.copy()
    df["Service Start Date"] = pd.to_datetime(df["Service Start Date"], errors="coerce")
    df["Service End Date"] = pd.to_datetime(df["Service End Date"], errors="coerce")

    # Drop rows without valid dates or where end < start
    df = df.dropna(subset=["Service Start Date", "Service End Date"])
    df = df[df["Service End Date"] >= df["Service Start Date"]].copy()

    if df.empty:
        return None, None, None, None

    # Determine median Service Start Date → pick its month/year
    ssd_sorted = df["Service Start Date"].sort_values().reset_index(drop=True)
    median_date = ssd_sorted.iloc[len(ssd_sorted) // 2]
    target_year = median_date.year
    target_month = median_date.month

    # Filter rows starting in that month
    mask = (df["Service Start Date"].dt.year == target_year) & (df["Service Start Date"].dt.month == target_month)
    df_median_month = df.loc[mask].copy()

    if df_median_month.empty:
        return None, median_date, 0, pd.DataFrame()

    # Length of Stay (inclusive)
    df_median_month["Length of Stay (days)"] = (df_median_month["Service End Date"] - df_median_month["Service Start Date"]).dt.days + 1

    avg_los = df_median_month["Length of Stay (days)"].mean()
    return float(round(avg_los, 2)), median_date, len(df_median_month), df_median_month

if alos_file is not None:
    try:
        # Clean the same way as Detox, then transform to target
        raw_alo = pd.read_csv(alos_file, engine="python")
        clean_alo = clean_raw_frame(raw_alo)
        detox_target = transform_detox_by_position(clean_alo)
        detox_target = rename_detox_payer_to_32(detox_target)

        avg_los, median_date, n_rows, df_details = compute_alos_for_median_month(detox_target)

        if avg_los is None:
            st.warning("No valid rows with usable dates to compute ALOS.")
        else:
            month_label = median_date.strftime("%B %Y")
            st.write(f"**Median Service Start Month:** {month_label}")
            st.write(f"**Average Length of Stay (inclusive):** {avg_los} days (across {n_rows} rows)")
            with st.expander("Rows Used for ALOS (Median Month)", expanded=False):
                # Show a tidy subset
                show_cols = ["Primary Payer", "Service Start Date", "Service End Date", "Length of Stay (days)"]
                st.dataframe(df_details[show_cols].sort_values("Service Start Date").reset_index(drop=True), use_container_width=True)
            st.download_button(
                label="Download ALOS Rows (Median Month)",
                data=to_csv_bytes(df_details),
                file_name="detox_alos_median_month_rows.csv",
                mime="text/csv"
            )
    except Exception as e:
        st.error(f"ALOS section error: {e}")

st.caption("Place-holder")