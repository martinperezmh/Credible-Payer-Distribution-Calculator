# app.py — Detox → 11-col target (Inpatient upload removed)
# + separate % tables (Detox-only) + collapsed combined % table (Detox-only) + ALOS section
# + Download All (ZIP of CSVs) at the top; button now requires only Detox
import io
import pandas as pd
import streamlit as st
import zipfile
import re
from datetime import datetime  # for dynamic ZIP filename

st.set_page_config(page_title="Cherry Hill Detox (CHD) Payer Percentage Calculator", layout="wide")
st.title("Cherry Hill Detox (CHD) Payer Percentage Calculator")

# --- Top placeholder for the Download All button (filled after computations) ---
download_all_placeholder = st.container()

st.write("Upload the **Detox Bed Day Report** CSV for CHD.\n")
("These calculations are based on the **Bed Day Model** for CHD.\n")

DETOX_TARGET_COLUMNS = [
    "Primary Payer","Visit Type","Client ID","Episode ID",
    "Service Start Date","Time In","Service End Date","Time Out",
    "WM Days","R&B Days","Admin Days",
]

INPATIENT_TARGET_COLUMNS = [
    "Primary Payer","Service Type","Client ID","Episode ID",
    "Service Start Date","Time In","Service End Date","Time Out","Total Days",
]

# ---------- Defaults for objects we might or might not produce ----------
detox_out = None
inpatient_out = None  # kept for compatibility with helper functions; will remain None
combined_table = None
combined_collapsed = None
alos_rows = None
alos_avg = None
alos_month_label = None
alos_n = None

# ---------- Helpers ----------
def to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

def clean_raw_frame(df: pd.DataFrame) -> pd.DataFrame:
    """(Detox legacy) Delete top row; drop rows with any empty/whitespace cell; reset index."""
    df = df.iloc[1:, :]
    df = df.replace(r"^\s*$", pd.NA, regex=True).dropna(how="any").reset_index(drop=True)
    return df

def clean_after_header(df: pd.DataFrame) -> pd.DataFrame:
    """Keep headers; drop rows with blanks; normalize header text."""
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
    return pd.to_numeric(s.astype("string").str.replace(",", "", regex=False).str.strip(), errors="coerce")

def find_col(df: pd.DataFrame, name_lower: str):
    for c in df.columns:
        if str(c).strip().lower() == name_lower:
            return c
    return None

def find_col_any(df: pd.DataFrame, options_lower: list[str]):
    for opt in options_lower:
        c = find_col(df, opt)
        if c is not None:
            return c
    for c in df.columns:
        name = str(c).strip().lower()
        if "wm" in name and "day" in name:
            return c
    return None

# ---------- ZIP builder (renamed files; no manifest) ----------
def build_download_all_zip(
    detox_df=None,
    inpatient_df=None,  # will be None in this Detox-only flow
    combined_table=None,
    combined_collapsed=None,
    alos_rows=None,
    alos_avg=None,
    alos_month_label=None,
    alos_n=None,
):
    """
    Build a ZIP of CSVs for all available calculated outputs.
    (No manifest file written.)
    """
    buf = io.BytesIO()

    def _write_csv_to_zip(zf: zipfile.ZipFile, df: pd.DataFrame, filename: str):
        csv_bytes = to_csv_bytes(df)
        zf.writestr(filename, csv_bytes)

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as z:
        # Detox WM & R&B totals (filename unchanged)
        if detox_df is not None:
            wm_total = pd.to_numeric(detox_df.get("WM Days"), errors="coerce").fillna(0).sum()
            rb_total = pd.to_numeric(detox_df.get("R&B Days"), errors="coerce").fillna(0).sum()
            wm_rb_totals = pd.DataFrame([{
                "WM Days Total": int(wm_total),
                "R&B Days Total": int(rb_total),
                "WM + R&B Total": int(wm_total + rb_total),
            }])
            _write_csv_to_zip(z, wm_rb_totals, "detox_wm_rb_totals.csv")

            # RENAMED: detox_units_pct -> detox_breakdown
            _write_csv_to_zip(z, summarize_units_by_payer(detox_df), "detox_breakdown.csv")

        # Inpatient outputs intentionally omitted (no inpatient upload in this version)

        # RENAMED: combined_summary -> unique_payer_breakdown
        if combined_table is not None:
            _write_csv_to_zip(z, combined_table, "unique_payer_breakdown.csv")

        # RENAMED: combined_collapsed -> detox_inpatient_units_payroll
        if combined_collapsed is not None:
            _write_csv_to_zip(z, combined_collapsed, "detox_inpatient_units_payroll.csv")

        # ALOS
        # RENAMED: alos_rows_median_month -> alos_used_data
        if alos_rows is not None and len(alos_rows) > 0:
            _write_csv_to_zip(z, alos_rows, "alos_used_data.csv")

        # Keep ALOS summary name unless you want that changed too
        if alos_avg is not None:
            meta = pd.DataFrame([{
                "Median Month": alos_month_label or "",
                "ALOS (days)": alos_avg,
                "Row Count": alos_n or 0,
            }])
            _write_csv_to_zip(z, meta, "alos_summary.csv")

    buf.seek(0)
    return buf.getvalue()

# Rename "Alameda County" → "Alameda 3.2"
def rename_detox_payer_to_32(df: pd.DataFrame) -> pd.DataFrame:
    if "Primary Payer" not in df.columns:
        return df
    s = df["Primary Payer"].astype("string").str.strip()
    alameda_variants = {"alameda county", "county of alameda", "alameda"}
    df["Primary Payer"] = s.where(~s.str.lower().isin(alameda_variants), "Alameda 3.2")
    return df

# ---------- Detox (File 1) → 11-col target ----------
def transform_detox_by_position(df: pd.DataFrame) -> pd.DataFrame:
    cols = list(df.columns)
    if len(cols) < 11:
        raise ValueError(f"Expected at least 11 columns for Detox mapping; found {len(cols)}.\nCols: {cols[:15]}")

    payer_col, visit_col, client_col, episode_col = cols[0], cols[1], cols[2], cols[3]
    start_col, time_in_col, end_col, time_out_col = cols[6], cols[7], cols[8], cols[9]
    rb_col, admin_col = cols[-2], cols[-1]

    # Preserve WM Days from source if present; otherwise explicit zero Series
    wm_col = find_col_any(df, ["wm days", "wm day", "withdrawal management days", "wm total days"])
    if wm_col is not None:
        wm_series = _num_clean(df[wm_col]).fillna(0).astype(int)
    else:
        wm_series = pd.Series(0, index=df.index, dtype=int)

    out = pd.DataFrame({
        "Primary Payer": df[payer_col].astype("string").str.strip(),
        "Visit Type": df[visit_col].astype("string").str.strip(),
        "Client ID": as_int_series(df[client_col]),
        "Episode ID": as_int_series(df[episode_col]),
        "Service Start Date": as_date_str(df[start_col]),
        "Time In": df[time_in_col].astype("string").str.strip(),
        "Service End Date": as_date_str(df[end_col]),
        "Time Out": df[time_out_col].astype("string").str.strip(),
        "WM Days": pd.to_numeric(wm_series, errors="coerce").fillna(0).astype(int),
        "R&B Days": pd.to_numeric(df[rb_col], errors="coerce").fillna(0).astype(int),
        "Admin Days": pd.to_numeric(df[admin_col], errors="coerce").fillna(0).astype(int),
    })
    return out[DETOX_TARGET_COLUMNS]

# ---------- Inpatient mapping helpers kept (unused now) ----------
def transform_inpatient_to_reference(df: pd.DataFrame, force_primary: bool = True) -> pd.DataFrame:
    # Unused in this Detox-only version; kept for compatibility
    cols = list(df.columns)
    if len(cols) < 10:
        raise ValueError(f"Unexpected inpatient column count ({len(cols)}). Columns: {cols[:15]}")
    payer_col, service_col, client_col, episode_col = cols[0], cols[1], cols[2], cols[3]
    start_col, time_in_col, end_col, time_out_col = cols[6], cols[7], cols[8], cols[9]
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
    primary_payer_series = pd.Series(["Alameda 3.5"] * len(df), dtype="string") if force_primary else df[payer_col].astype("string").str.strip()
    out = pd.DataFrame({
        "Primary Payer": primary_payer_series,
        "Service Type": df[service_col].astype("string").str.strip(),
        "Client ID": as_int_series(df[client_col]),
        "Episode ID": as_int_series(df[episode_col]),
        "Service Start Date": as_date_str(df[start_col]),
        "Time In": df[time_in_col].astype("string").str.strip(),
        "Service End Date": as_date_str(df[end_col]),
        "Time Out": df[time_out_col].astype("string").str.strip(),
        "Total Days": pd.to_numeric(total_days, errors="coerce").fillna(0).astype(int),
    })[INPATIENT_TARGET_COLUMNS]
    st.caption(f"Inpatient Total Days source: {source}")
    return out

# ---------- Summaries ----------
def summarize_units_by_payer(df_target_11: pd.DataFrame) -> pd.DataFrame:
    grouped = df_target_11.groupby("Primary Payer", as_index=False)[["R&B Days", "Admin Days"]].sum()
    grouped["Detox Units"] = grouped["R&B Days"] + grouped["Admin Days"]
    total_units = grouped["Detox Units"].sum()
    grouped["% of Detox Units"] = (grouped["Detox Units"] / total_units * 100).round(2) if total_units else 0
    return grouped[["Primary Payer", "Detox Units", "% of Detox Units"]].sort_values("Primary Payer").reset_index(drop=True)

def summarize_total_days_by_payer(df_target_9: pd.DataFrame) -> pd.DataFrame:
    grouped = df_target_9.groupby("Primary Payer", as_index=False)["Total Days"].sum()
    total_days = grouped["Total Days"].sum()
    grouped["% of Total Days"] = (grouped["Total Days"] / total_days * 100).round(2) if total_days else 0
    return grouped.sort_values("Primary Payer").reset_index(drop=True)

def summarize_combined_by_payer(detox_df: pd.DataFrame | None, inpatient_df: pd.DataFrame | None) -> pd.DataFrame:
    if detox_df is not None:
        d = detox_df.groupby("Primary Payer", as_index=False)[["R&B Days", "Admin Days"]].sum()
        d["Detox Units"] = d["R&B Days"] + d["Admin Days"]
        d = d[["Primary Payer", "Detox Units"]]
    else:
        d = pd.DataFrame(columns=["Primary Payer", "Detox Units"])

    # inpatient_df is None in this Detox-only flow → yields empty frame
    if inpatient_df is not None:
        i = inpatient_df.groupby("Primary Payer", as_index=False)[["Total Days"]].sum()
        i = i.rename(columns={"Total Days": "Inpatient Total Days"})
    else:
        i = pd.DataFrame(columns=["Primary Payer", "Inpatient Total Days"])

    combined = pd.merge(d, i, on="Primary Payer", how="outer").fillna(0)
    combined["Detox Units"] = pd.to_numeric(combined["Detox Units"], errors="coerce").fillna(0).astype(int)
    combined["Inpatient Total Days"] = pd.to_numeric(combined["Inpatient Total Days"], errors="coerce").fillna(0).astype(int)
    combined["Combined Units"] = combined["Detox Units"] + combined["Inpatient Total Days"]
    total_combined = combined["Combined Units"].sum()
    combined["% of Combined"] = (combined["Combined Units"] / total_combined * 100).round(2) if total_combined else 0.0
    return combined.sort_values("Primary Payer").reset_index(drop=True)

def summarize_combined_collapsed_by_payer(detox_df: pd.DataFrame | None, inpatient_df: pd.DataFrame | None) -> pd.DataFrame:
    base = summarize_combined_by_payer(detox_df, inpatient_df).copy()
    mask = base["Primary Payer"].astype("string").str.contains("alameda", case=False, na=False)
    base["Primary Payer"] = base["Primary Payer"].where(mask, "Third Party")
    collapsed = base.groupby("Primary Payer", as_index=False)[["Detox Units", "Inpatient Total Days", "Combined Units"]].sum()
    total = collapsed["Combined Units"].sum()
    collapsed["% of Combined"] = (collapsed["Combined Units"] / total * 100).round(2) if total else 0.0
    return collapsed.sort_values("Primary Payer").reset_index(drop=True)

# NEW: small helper for Detox WM & R&B totals (display only)
def summarize_wm_rb_totals(detox_df: pd.DataFrame) -> pd.DataFrame:
    wm_total = pd.to_numeric(detox_df["WM Days"], errors="coerce").fillna(0).sum()
    rb_total = pd.to_numeric(detox_df["R&B Days"], errors="coerce").fillna(0).sum()
    return pd.DataFrame([{
        "WM Days Total": int(wm_total),
        "R&B Days Total": int(rb_total),
        "WM + R&B Total": int(wm_total + rb_total),
    }])

# ---------- UI ----------
st.subheader("Upload CSV")
uploaded1 = st.file_uploader("**Detox Bed Day Report (CSV)**", type=["csv"], key="file1")

if uploaded1 is None:
    st.info("Waiting for Detox CSV…")
else:
    try:
        # Detox (READ WITH header=1 to use 2nd line as header; preserves WM Days)
        st.write(f"**File selected:** {uploaded1.name}")
        raw1 = pd.read_csv(uploaded1, header=1, engine="python")
        clean1 = clean_after_header(raw1)
        detox_out = transform_detox_by_position(clean1)
        detox_out = rename_detox_payer_to_32(detox_out)
        with st.expander("Preview: Detox 3.2 Data", expanded=False):
            st.dataframe(detox_out.head(25), use_container_width=True)

        # Detox totals (display only)
        st.subheader("Detox Totals — WM & R&B")
        wm_rb_table = summarize_wm_rb_totals(detox_out)
        st.dataframe(wm_rb_table, use_container_width=True)

        # Combined tables (Detox-only; inpatient remains None)
        st.subheader("Percentage Table — Detox Units by Primary Payer")
        st.caption("This table shows Detox units of service for each unique payer.")
        combined_table = summarize_combined_by_payer(detox_out, inpatient_out)
        st.dataframe(combined_table, use_container_width=True)

        st.subheader("Percentage Table — Alameda vs Third Party (Detox-only)")
        st.caption("Detox rows mapped to **Alameda 3.2** (formerly 'Alameda County').")
        combined_collapsed = summarize_combined_collapsed_by_payer(detox_out, inpatient_out)
        st.dataframe(combined_collapsed, use_container_width=True)

    except Exception as e:
        st.error(f"Error: {e}")
        st.stop()

# ---------- ALOS section (Detox) ----------
st.subheader("Average Length of Stay (ALOS) — Median Service Start Month (Detox)")
st.caption(
    "Upload the Detox CSV again. We'll clean it the same way (header=1, drop blanks), "
    "convert to the target format, find the median Service Start Date month, and compute "
    "ALOS = (End - Start) + 1 for rows starting in that month."
)
alos_file = st.file_uploader("Upload Detox CSV for ALOS", type=["csv"], key="alos_detox")

def compute_alos_for_median_month(detox_target_df: pd.DataFrame):
    df = detox_target_df.copy()
    df["Service Start Date"] = pd.to_datetime(df["Service Start Date"], errors="coerce")
    df["Service End Date"] = pd.to_datetime(df["Service End Date"], errors="coerce")
    df = df.dropna(subset=["Service Start Date", "Service End Date"])
    df = df[df["Service End Date"] >= df["Service Start Date"]].copy()
    if df.empty:
        return None, None, None, None
    ssd_sorted = df["Service Start Date"].sort_values().reset_index(drop=True)
    median_date = ssd_sorted.iloc[len(ssd_sorted) // 2]
    target_year, target_month = median_date.year, median_date.month
    mask = (df["Service Start Date"].dt.year == target_year) & (df["Service Start Date"].dt.month == target_month)
    df_median_month = df.loc[mask].copy()
    if df_median_month.empty:
        return None, median_date, 0, pd.DataFrame()
    df_median_month["Length of Stay (days)"] = (df_median_month["Service End Date"] - df_median_month["Service Start Date"]).dt.days + 1
    avg_los = df_median_month["Length of Stay (days)"].mean()
    return float(round(avg_los, 2)), median_date, len(df_median_month), df_median_month

if alos_file is not None:
    try:
        raw_alo = pd.read_csv(alos_file, header=1, engine="python")
        clean_alo = clean_after_header(raw_alo)
        detox_target = transform_detox_by_position(clean_alo)
        detox_target = rename_detox_payer_to_32(detox_target)
        avg_los, median_date, n_rows, df_details = compute_alos_for_median_month(detox_target)
        alos_rows = df_details
        alos_avg = avg_los
        alos_n = n_rows
        alos_month_label = median_date.strftime("%B %Y") if isinstance(median_date, pd.Timestamp) else None
        if avg_los is None:
            st.warning("No valid rows with usable dates to compute ALOS.")
        else:
            st.write(f"**Median Service Start Month:** {alos_month_label}")
            st.write(f"**Average Length of Stay (inclusive):** {avg_los} days (across {n_rows} rows)")
            with st.expander("Rows Used for ALOS (Median Month)", expanded=False):
                show_cols = ["Primary Payer", "Service Start Date", "Service End Date", "Length of Stay (days)"]
                st.dataframe(df_details[show_cols].sort_values("Service Start Date").reset_index(drop=True), use_container_width=True)
    except Exception as e:
        st.error(f"ALOS section error: {e}")

# ---------- Download All (ZIP of CSVs) — dynamic filename; requires only Detox ----------
with download_all_placeholder:
    zip_bytes = build_download_all_zip(
        detox_df=detox_out,
        inpatient_df=None,  # no inpatient in this version
        combined_table=combined_table,
        combined_collapsed=combined_collapsed,
        alos_rows=alos_rows,
        alos_avg=alos_avg,
        alos_month_label=alos_month_label,
        alos_n=alos_n,
    )
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Enable when Detox is uploaded
    has_detox = (detox_out is not None)

    # If Detox uploaded, inject CSS to make the button green
    if has_detox:
        st.markdown(
            """
            <style>
            div.stDownloadButton > button {
                background-color: #90EE90 !important; /* light green */
                color: black !important;
                font-weight: bold !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

    # Tooltip wrapper
    tooltip_text = "Waiting for Detox Bed Day Report" if not has_detox else ""

    st.markdown(f'<div title="{tooltip_text}">', unsafe_allow_html=True)
    st.download_button(
        "Download All (ZIP of CSVs)",
        data=zip_bytes if has_detox else b"",  # empty if disabled
        file_name=f"CHD_report_{today_str}.zip",
        mime="application/zip",
        use_container_width=True,
        disabled=not has_detox,  # disabled until Detox uploaded
    )
    st.markdown("</div>", unsafe_allow_html=True)
