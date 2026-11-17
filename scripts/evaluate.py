"""
Measures how well the app works on the sample data. These are the numbers that go on the resume.

  python scripts/evaluate.py --method rules     # rule-based extraction (no API key needed)
  python scripts/evaluate.py --method gemini    # AI extraction (needs GEMINI_API_KEY)
  python scripts/evaluate.py --method truth     # perfect extraction -> tests the matching logic alone

Prints:
  1. Extraction accuracy: % of invoices where each field was read correctly
  2. Reconciliation accuracy: how many of the 12 planted errors were caught, and any false alarms
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from recon.extract import DEFAULT_MODEL, check_totals, extract_with_gemini, extract_with_rules  # noqa: E402
from recon.match import clean_vendor, reconcile  # noqa: E402

DATA = ROOT / "sample_data"


def extract_all(method, model):
    if method == "truth":
        df = pd.read_csv(DATA / "invoice_truth.csv")
        df["extraction_check"] = "OK"
        return df
    rows = []
    files = sorted((DATA / "invoices").glob("*.pdf"))
    key = os.environ.get("GEMINI_API_KEY")
    if method == "gemini" and not key:
        sys.exit("Set GEMINI_API_KEY first:  export GEMINI_API_KEY=your_key")
    for n, f in enumerate(files, 1):
        data = f.read_bytes()
        rows.append(extract_with_gemini(data, f.name, key, model) if method == "gemini"
                    else extract_with_rules(data, f.name))
        if n % 10 == 0 or n == len(files):
            print(f"Extracted {n}/{len(files)}", flush=True)
    return pd.DataFrame(rows)


def field_accuracy(extracted, truth):
    m = truth.merge(extracted, on="source_file", suffixes=("_true", "_got"))
    scores = {}
    for field in ["vendor_name", "invoice_number", "invoice_date", "subtotal", "sales_tax", "total_amount"]:
        t, g = m[f"{field}_true"], m[f"{field}_got"]
        if field == "vendor_name":
            ok = t.map(clean_vendor) == g.fillna("").map(clean_vendor)
        elif field in ("invoice_number", "invoice_date"):
            ok = t.astype(str).str.strip().str.upper() == g.fillna("").astype(str).str.strip().str.upper()
        else:
            ok = (pd.to_numeric(g, errors="coerce") - t).abs() <= 1
        scores[field] = ok.mean()
    return scores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["rules", "gemini", "truth"], default="rules")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    truth = pd.read_csv(DATA / "invoice_truth.csv")
    bank = pd.read_csv(DATA / "bank_statement.csv")
    key = pd.read_csv(DATA / "answer_key.csv").fillna("")

    extracted = extract_all(args.method, args.model)
    extracted.to_csv(ROOT / f"extracted_{args.method}.csv", index=False)

    print(f"\n=== 1. Extraction accuracy ({args.method}, {len(extracted)} invoices) ===")
    for field, acc in field_accuracy(extracted, truth).items():
        print(f"  {field:<16} {acc:6.1%}")

    results = reconcile(extracted, bank).fillna({"source_file": "", "bank_reference": ""})
    got_inv = dict(zip(results["source_file"], results["status"].astype(str)))
    got_bank = dict(zip(results.loc[results["status"] == "Unexplained Payment", "bank_reference"],
                        ["Unexplained Payment"] * len(results)))

    print("\n=== 2. Reconciliation vs answer key ===")
    correct, wrong = 0, []
    for r in key.itertuples():
        got = got_inv.get(r.source_file) if r.source_file else got_bank.get(r.bank_reference, "(matched)")
        if got == r.expected_status:
            correct += 1
        else:
            wrong.append(f"  {r.source_file or r.bank_reference}: expected {r.expected_status}, got {got}")
    planted = key[key["expected_status"] != "Matched"]
    caught = sum(
        (got_inv.get(r.source_file) if r.source_file else got_bank.get(r.bank_reference)) == r.expected_status
        for r in planted.itertuples()
    )
    false_unexplained = set(got_bank) - set(key["bank_reference"])
    print(f"  Items classified correctly: {correct}/{len(key)} ({correct / len(key):.0%})")
    print(f"  Planted errors caught:      {caught}/{len(planted)}")
    print(f"  False 'Unexplained Payment' alarms: {len(false_unexplained)}")
    if wrong:
        print("  Misclassified:")
        print("\n".join(wrong))


if __name__ == "__main__":
    main()
