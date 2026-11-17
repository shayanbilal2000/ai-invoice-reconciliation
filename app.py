"""
AI Invoice Reconciliation Assistant: the web app.
Run locally:  streamlit run app.py

Flow:  invoices (PDF) --[extract.py]--> table of invoice data --[match.py]--> statuses --[report.py]--> Excel
"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from recon.extract import DEFAULT_MODEL, extract_with_gemini, extract_with_rules
from recon.match import STATUS_ORDER, Settings, reconcile, summary
from recon.report import COLORS, to_excel

SAMPLE = Path(__file__).parent / "sample_data"

st.set_page_config(page_title="AI Invoice Reconciliation", layout="wide")
st.title("AI Invoice Reconciliation Assistant")
st.caption("Upload supplier invoices (PDF) and a bank statement. AI reads the invoices, rule-based logic "
           "matches them to payments, and every exception is flagged for review.")


# ---------------------------------------------------------------- sidebar: settings
def get_api_key():
    # On Streamlit Cloud the key lives in Settings -> Secrets. Locally, use an environment variable.
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY", "")


with st.sidebar:
    st.header("1. Data")
    source = st.radio("Data source", ["Sample data (50 invoices)", "Upload my own"])
    st.header("2. Extraction")
    method = st.radio("How to read the invoices", ["AI (Google Gemini)", "Rule-based (no AI)"],
                      help="Rule-based is the baseline: it only understands invoice layouts it was written for.")
    api_key = get_api_key()
    model = DEFAULT_MODEL
    if method.startswith("AI"):
        if not api_key:
            api_key = st.text_input("Gemini API key", type="password",
                                    help="Free key from Google AI Studio. It is not stored.")
        model = st.text_input("Model", DEFAULT_MODEL)
    st.header("3. Matching rules")
    with st.expander("Adjust"):
        s = Settings(
            days_before=st.number_input("Days a payment may come BEFORE the invoice", 0, 30, 3),
            days_after=st.number_input("Days a payment may come AFTER the invoice", 1, 180, 45),
            vendor_threshold=st.slider("Vendor name similarity needed", 50, 100, 80),
            amount_tolerance=st.number_input("Rounding tolerance (PKR)", 0.0, 100.0, 1.0),
            mismatch_pct=st.slider("Max % difference for an 'Amount Mismatch'", 1, 50, 10),
        )


# ---------------------------------------------------------------- load inputs
def load_bank(file):
    df = pd.read_excel(file) if str(getattr(file, "name", file)).endswith(("xlsx", "xls")) else pd.read_csv(file)
    df.columns = [c.strip().lower() for c in df.columns]
    missing = {"date", "description", "debit"} - set(df.columns)
    if missing:
        st.error(f"Bank statement is missing column(s): {', '.join(sorted(missing))}. "
                 "Expected: date, description, debit (and optionally reference, credit, balance).")
        st.stop()
    if "reference" not in df.columns:
        df["reference"] = [f"ROW{i + 2}" for i in range(len(df))]
    return df


if source.startswith("Sample"):
    pdfs = [(p.name, p.read_bytes()) for p in sorted((SAMPLE / "invoices").glob("*.pdf"))]
    bank = load_bank(SAMPLE / "bank_statement.csv")
    with st.expander("What's in the sample data?"):
        st.markdown("Fictional data with **12 errors planted on purpose**: 3 duplicate invoices, 4 amount "
                    "mismatches, 3 unpaid invoices and 2 unexplained payments. The invoices come in three "
                    "different layouts, and the rule-based reader only understands two of them.")
else:
    c1, c2 = st.columns(2)
    up_pdfs = c1.file_uploader("Invoices (PDF)", type="pdf", accept_multiple_files=True)
    up_bank = c2.file_uploader("Bank statement (CSV or Excel)", type=["csv", "xlsx"])
    if not up_pdfs or not up_bank:
        st.info("Upload invoices and a bank statement to begin.")
        st.stop()
    pdfs = [(f.name, f.getvalue()) for f in up_pdfs]
    bank = load_bank(up_bank)

with st.expander(f"Bank statement preview ({len(bank)} rows)"):
    st.dataframe(bank, hide_index=True, width="stretch")


# ---------------------------------------------------------------- step 1: extraction
@st.cache_data(show_spinner=False)
def cached_gemini(pdf_bytes, filename, model, _api_key):
    # Cached: the same PDF is only sent to the AI once, which saves free-tier quota.
    # (The leading underscore keeps the key out of the cache.)
    return extract_with_gemini(pdf_bytes, filename, _api_key, model)


run_key = (source, method, model, tuple(name for name, _ in pdfs))
if st.button(f"Read {len(pdfs)} invoices", type="primary"):
    if method.startswith("AI") and not api_key:
        st.error("Add a Gemini API key in the sidebar, or switch to Rule-based.")
        st.stop()
    rows, errors = [], []
    bar = st.progress(0.0, text="Reading invoices...")
    for n, (name, data) in enumerate(pdfs, 1):
        try:
            rows.append(cached_gemini(data, name, model, api_key) if method.startswith("AI")
                        else extract_with_rules(data, name))
        except Exception as e:  # one bad file shouldn't stop the whole batch
            errors.append(f"{name}: {e}")
        bar.progress(n / len(pdfs), text=f"Reading invoices... {n}/{len(pdfs)}")
    bar.empty()
    for e in errors:
        st.warning(e)
    st.session_state["extracted"] = pd.DataFrame(rows)
    st.session_state["run_key"] = run_key

if st.session_state.get("run_key") != run_key or "extracted" not in st.session_state:
    st.stop()

st.subheader("Step 1: Extracted invoice data")
extracted = st.session_state["extracted"]
bad = (extracted["extraction_check"] != "OK").sum()
if bad:
    st.warning(f"{bad} invoice(s) failed the subtotal + tax = total check. Review and correct them in the "
               "table below before trusting the reconciliation.")
st.caption("You can edit any cell. A human reviewer always has the final say.")
edited = st.data_editor(extracted, hide_index=True, width="stretch", key="editor")


# ---------------------------------------------------------------- step 2: reconciliation
st.subheader("Step 2: Reconciliation")
results = reconcile(edited, bank, s)
counts = results["status"].value_counts()
cols = st.columns(len(STATUS_ORDER))
for col, status in zip(cols, STATUS_ORDER):
    col.metric(status, int(counts.get(status, 0)))

exceptions_value = results.loc[results["status"] != "Matched", "invoice_amount"].sum()
st.caption(f"Value of invoices needing attention: PKR {exceptions_value:,.0f}")

show = st.multiselect("Show", STATUS_ORDER, default=[x for x in STATUS_ORDER if x != "Matched"])
view = results[results["status"].isin(show)]


def colour(row):
    return [f"background-color: #{COLORS.get(str(row['status']), 'FFFFFF')}; color: #111"] * len(row)


st.dataframe(view.style.apply(colour, axis=1).format(
    {"invoice_amount": "{:,.0f}", "paid_amount": "{:,.0f}", "difference": "{:+,.0f}"}, na_rep=""),
    hide_index=True, width="stretch")

with st.expander("Summary by status"):
    st.dataframe(summary(results), hide_index=True)

st.download_button("Download reconciliation report (.xlsx)", to_excel(results),
                   file_name="reconciliation_report.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
