"""Run with:  pytest
Each test is a small, hand-made scenario with a known right answer."""
import json
from types import SimpleNamespace

import pandas as pd

from recon import extract
from recon.match import looks_transposed, reconcile, vendor_similarity
from recon.report import to_excel


def make(invoices, payments):
    inv = pd.DataFrame(invoices, columns=["source_file", "vendor_name", "invoice_number", "invoice_date", "total_amount"])
    inv["extraction_check"] = "OK"
    bank = pd.DataFrame(payments, columns=["date", "reference", "description", "debit"])
    return inv, bank


def status_of(results, file):
    return str(results.loc[results["source_file"] == file, "status"].iloc[0])


def test_exact_match():
    inv, bank = make([("a.pdf", "Rawal Logistics & Couriers", "B-1", "2026-07-01", 28261)],
                     [("2026-07-05", "T1", "CHQ 123456 RAWAL LOGISTICS", 28261)])
    assert status_of(reconcile(inv, bank), "a.pdf") == "Matched"


def test_duplicate_invoice():
    inv, bank = make([("a.pdf", "Kohsar Printing Press", "B-7", "2026-07-01", 5000),
                      ("b.pdf", "Kohsar Printing Press", "B-7", "2026-07-01", 5000)],
                     [("2026-07-03", "T1", "IBFT TO KOHSAR PRINTING", 5000)])
    r = reconcile(inv, bank)
    assert status_of(r, "a.pdf") == "Matched"
    assert status_of(r, "b.pdf") == "Duplicate Invoice"


def test_transposed_amount_is_mismatch():
    assert looks_transposed(12500, 15200)
    inv, bank = make([("a.pdf", "Potohar Power Solutions", "INV-1", "2026-07-01", 12500)],
                     [("2026-07-04", "T1", "IBFT TO POTOHAR POWER SOL", 15200)])
    r = reconcile(inv, bank)
    assert status_of(r, "a.pdf") == "Amount Mismatch"
    assert "typing error" in r.loc[0, "note"]


def test_unpaid_and_unexplained():
    inv, bank = make([("a.pdf", "Kohsar Printing Press", "B-1", "2026-07-01", 9000)],
                     [("2026-07-03", "T1", "IBFT TO SAFA GENERAL TRADERS", 73500)])
    r = reconcile(inv, bank)
    assert status_of(r, "a.pdf") == "Unpaid Invoice"
    assert (r["status"] == "Unexplained Payment").sum() == 1


def test_payment_outside_date_window_not_matched():
    inv, bank = make([("a.pdf", "Kohsar Printing Press", "B-1", "2026-07-01", 9000)],
                     [("2026-12-01", "T1", "IBFT TO KOHSAR PRINTING", 9000)])
    assert status_of(reconcile(inv, bank), "a.pdf") == "Unpaid Invoice"


def test_vendor_similarity_handles_bank_abbreviations():
    assert vendor_similarity("Blue Area Facility Management", "IBFT TO BLUEAREA FACILITY MGT") >= 80
    assert vendor_similarity("Blue Area Facility Management", "IBFT TO SAFA GENERAL TRADERS") < 80


def test_excel_export_has_summary_sheet():
    inv, bank = make([("a.pdf", "Kohsar Printing Press", "B-1", "2026-07-01", 9000)],
                     [("2026-07-03", "T1", "IBFT TO KOHSAR PRINTING", 9000)])
    data = to_excel(reconcile(inv, bank))
    assert data[:2] == b"PK"  # .xlsx files are zip archives


def test_gemini_extraction_parses_response(monkeypatch):
    """Fakes the Gemini API so we can test our code without a key or internet."""
    fake_json = json.dumps({"vendor_name": "Rawal Logistics & Couriers", "invoice_number": "B-1005",
                            "invoice_date": "2026-07-14", "subtotal": 23950, "sales_tax": 4311,
                            "total_amount": 28261})
    calls = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls["model"], calls["config"] = model, config
            return SimpleNamespace(text=fake_json)

    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()

    from google import genai
    monkeypatch.setattr(genai, "Client", FakeClient)
    row = extract.extract_with_gemini(b"%PDF-fake", "x.pdf", api_key="test")
    assert row["invoice_number"] == "B-1005"
    assert row["extraction_check"] == "OK"
    assert calls["config"].response_mime_type == "application/json"
