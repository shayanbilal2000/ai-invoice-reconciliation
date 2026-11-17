"""
STEP 2 OF THE PIPELINE: reconcile invoices against the bank statement.

No AI here, on purpose. Matching must be explainable and repeatable: an auditor has to be able to see
WHY an invoice was matched to a payment. Fixed rules give the same answer every time.

The rules, in order:
  1. Duplicate check  - same vendor + same invoice number seen before -> "Duplicate Invoice" (don't pay twice!)
  2. Exact match      - same vendor, amount equal, payment date within the window -> "Matched"
  3. Near match       - same vendor, in the window, amount close OR digits swapped -> "Amount Mismatch"
  4. Leftovers        - invoices nobody paid -> "Unpaid Invoice"
                        payments with no invoice -> "Unexplained Payment"
"""
import re
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import fuzz

STATUS_ORDER = ["Matched", "Amount Mismatch", "Duplicate Invoice", "Unpaid Invoice", "Unexplained Payment"]


@dataclass
class Settings:
    days_before: int = 3            # payment may come slightly BEFORE the invoice date (advance payment)
    days_after: int = 45            # ...or up to this many days after it (payment terms)
    vendor_threshold: int = 80      # 0-100 similarity needed between invoice vendor and bank description
    amount_tolerance: float = 1.0   # PKR difference still treated as "equal" (rounding)
    mismatch_pct: float = 10.0      # how far off (in %) an amount can be and still count as "the same payment"


# ---------------------------------------------------------------- cleaning helpers
LEGAL_WORDS = r"\b(pvt|private|ltd|limited|co|company|services|traders|and|the|m/s)\b"
BANK_WORDS = r"\b(ibft|to|from|online|trf|transfer|chq|cheque|ref|payment)\b"


def clean_vendor(name):
    """'Margalla Office Supplies (Pvt) Ltd' -> 'margalla office supplies'"""
    s = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    s = re.sub(LEGAL_WORDS, " ", s)
    return " ".join(s.split())


def clean_bank_text(desc):
    """'IBFT TO MARGALLA OFFICE SUPP REF INV-1023' -> 'margalla office supp'"""
    s = str(desc).lower()
    s = re.sub(r"\bref\b.*$", " ", s)          # drop the reference part
    s = re.sub(r"\d+", " ", s)                 # drop cheque numbers
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(BANK_WORDS, " ", s)
    return " ".join(s.split())


def vendor_similarity(vendor, bank_desc):
    """0-100 score. Banks shorten names ('FACILITY MGT', 'BLUEAREA'), so we take the best of a few
    fuzzy measures, including one that ignores spaces."""
    a, b = clean_vendor(vendor), clean_bank_text(bank_desc)
    if not a or not b:
        return 0
    return max(
        fuzz.token_set_ratio(a, b),
        fuzz.partial_ratio(a.replace(" ", ""), b.replace(" ", "")),
    )


def looks_transposed(a, b):
    """Classic accounting check: if two amounts contain the same digits in a different order,
    it's probably a typing (transposition) error. Bonus fact: the difference is always divisible by 9."""
    sa, sb = str(int(round(a))), str(int(round(b)))
    return sa != sb and sorted(sa) == sorted(sb)


# ---------------------------------------------------------------- main function
def reconcile(invoices: pd.DataFrame, bank: pd.DataFrame, s: Settings = Settings()) -> pd.DataFrame:
    inv = invoices.copy().reset_index(drop=True)
    inv["invoice_date"] = pd.to_datetime(inv["invoice_date"], errors="coerce")
    inv["total_amount"] = pd.to_numeric(inv["total_amount"], errors="coerce")
    inv["status"] = None
    inv["note"] = ""

    # Only money going OUT is a supplier payment. Customer receipts (credits) are ignored.
    pay = bank.copy()
    pay["date"] = pd.to_datetime(pay["date"], errors="coerce")
    pay["debit"] = pd.to_numeric(pay["debit"], errors="coerce").fillna(0)
    pay = pay[pay["debit"] > 0].reset_index(drop=True)
    pay["used"] = False

    # ---- Rule 1: duplicates
    seen = {}
    for i, row in inv.sort_values("source_file").iterrows():
        key = (clean_vendor(row["vendor_name"]), str(row["invoice_number"]).strip().upper())
        if not key[1]:
            continue
        if key in seen:
            inv.at[i, "status"] = "Duplicate Invoice"
            inv.at[i, "note"] = f"Same vendor and invoice number as {seen[key]}. Do not pay again."
        else:
            seen[key] = row["source_file"]

    # ---- Build every possible (invoice, payment) pair that passes the vendor + date rules
    pairs = []
    for i, r in inv[inv["status"].isna()].iterrows():
        if pd.isna(r["total_amount"]) or pd.isna(r["invoice_date"]):
            continue
        for j, p in pay.iterrows():
            days = (p["date"] - r["invoice_date"]).days
            if not (-s.days_before <= days <= s.days_after):
                continue
            score = vendor_similarity(r["vendor_name"], p["description"])
            if score < s.vendor_threshold:
                continue
            ref_hit = bool(r["invoice_number"]) and str(r["invoice_number"]).upper() in str(p["description"]).upper()
            pairs.append({"i": i, "j": j, "days": days, "score": score, "ref_hit": ref_hit,
                          "diff": p["debit"] - r["total_amount"]})
    pairs = pd.DataFrame(pairs, columns=["i", "j", "days", "score", "ref_hit", "diff"])

    matched = {}  # invoice index -> payment index

    def assign(candidates, status):
        # Best candidates first: invoice number in the bank text, then closest amount, then closest date
        candidates = candidates.assign(abs_diff=candidates["diff"].abs(), abs_days=candidates["days"].abs())
        candidates = candidates.sort_values(["ref_hit", "abs_diff", "abs_days"], ascending=[False, True, True])
        for c in candidates.itertuples():
            if c.i in matched or pay.at[c.j, "used"]:
                continue
            matched[c.i] = c.j
            pay.at[c.j, "used"] = True
            inv.at[c.i, "status"] = status

    # ---- Rule 2: exact amount
    assign(pairs[pairs["diff"].abs() <= s.amount_tolerance], "Matched")

    # ---- Rule 3: near match (amount slightly off, or digits swapped)
    left = pairs[~pairs["i"].isin(matched.keys())].copy()
    if not left.empty:
        amt = inv.loc[left["i"], "total_amount"].to_numpy()
        paid = pay.loc[left["j"], "debit"].to_numpy()
        pct_ok = (abs(paid - amt) / amt * 100) <= s.mismatch_pct
        swapped = [looks_transposed(a, b) for a, b in zip(amt, paid)]
        assign(left[pct_ok | pd.Series(swapped, index=left.index)], "Amount Mismatch")

    # ---- Rule 4: leftovers
    inv.loc[inv["status"].isna(), "status"] = "Unpaid Invoice"

    # ---- Build one tidy results table
    rows = []
    for i, r in inv.iterrows():
        p = pay.loc[matched[i]] if i in matched else None
        row = {
            "status": r["status"],
            "source_file": r["source_file"],
            "vendor_name": r["vendor_name"],
            "invoice_number": r["invoice_number"],
            "invoice_date": r["invoice_date"].date() if pd.notna(r["invoice_date"]) else None,
            "invoice_amount": r["total_amount"],
            "bank_reference": p["reference"] if p is not None else "",
            "bank_date": p["date"].date() if p is not None else None,
            "bank_description": p["description"] if p is not None else "",
            "paid_amount": p["debit"] if p is not None else None,
            "difference": (p["debit"] - r["total_amount"]) if p is not None else None,
            "note": r["note"],
        }
        if row["status"] == "Amount Mismatch":
            d = row["difference"]
            if looks_transposed(row["invoice_amount"], row["paid_amount"]):
                row["note"] = f"Paid {d:+,.0f}. Same digits in a different order: likely a typing error."
            elif d < 0:
                row["note"] = (f"Short-paid by {-d:,.0f} ({-d / row['invoice_amount']:.1%}). "
                               "Check for a withholding tax deduction or a partial payment.")
            else:
                row["note"] = f"Over-paid by {d:,.0f}. Recover from vendor or adjust next payment."
        elif row["status"] == "Unpaid Invoice":
            row["note"] = "No matching payment found in the statement period."
        if r.get("extraction_check", "OK") not in ("OK", None, ""):
            row["note"] = (row["note"] + f" Extraction check: {r['extraction_check']}.").strip()
        rows.append(row)

    for _, p in pay[~pay["used"]].iterrows():
        rows.append({
            "status": "Unexplained Payment", "source_file": "", "vendor_name": "", "invoice_number": "",
            "invoice_date": None, "invoice_amount": None, "bank_reference": p["reference"],
            "bank_date": p["date"].date(), "bank_description": p["description"], "paid_amount": p["debit"],
            "difference": None, "note": "Payment with no supporting invoice. Ask for documentation.",
        })

    out = pd.DataFrame(rows)
    out["status"] = pd.Categorical(out["status"], categories=STATUS_ORDER, ordered=True)
    return out.sort_values(["status", "vendor_name", "invoice_date"]).reset_index(drop=True)


def summary(results: pd.DataFrame) -> pd.DataFrame:
    """Count and total value per status: the first thing a finance manager wants to see."""
    g = results.groupby("status", observed=False).agg(
        items=("status", "size"),
        invoice_value=("invoice_amount", "sum"),
        paid_value=("paid_amount", "sum"),
    )
    return g.reset_index()
