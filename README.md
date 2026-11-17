# AI Invoice Reconciliation Assistant

Reconciling supplier invoices against the bank statement is slow, manual work for accounts payable teams. This app automates the routine part and leaves the judgement calls to a person:

1. **AI reads the invoices.** Google Gemini extracts the vendor, invoice number, date, subtotal, sales tax and total from PDF invoices in any layout.
2. **Rules do the matching.** Each invoice is matched to a bank payment using vendor name similarity, amount, and a payment date window. These rules are deterministic, so every match can be explained to an auditor.
3. **Exceptions are flagged.** Duplicate invoices, amount mismatches, unpaid invoices and payments with no supporting invoice are highlighted, each with a suggested next step.
4. **Excel report.** The output downloads as a colour-coded workbook with a summary sheet and one sheet per exception type.

**Live demo:** coming soon &nbsp;·&nbsp; **Author:** Shayan Bilal

<!-- Add a screenshot: save it as docs/screenshot.png and uncomment the next line -->
<!-- ![App screenshot](docs/screenshot.png) -->

## How it works

```
Invoice PDFs ──► extract.py ──► invoice table ──► match.py ──► status per item ──► report.py ──► Excel
                (Gemini AI or                    (duplicates, exact match,
                 rule-based baseline)             near match, leftovers)
Bank statement CSV ─────────────────────────────────┘
```

| Status | Meaning | What finance should do |
|---|---|---|
| Matched | Paid the exact invoice amount | Nothing |
| Amount Mismatch | Paid, but a different amount | Check for a typing error (same digits swapped) or tax withheld |
| Duplicate Invoice | Same vendor and invoice number already received | Don't pay it again |
| Unpaid Invoice | No payment found | Check whether it's due, or schedule payment |
| Unexplained Payment | Money left the bank with no invoice | Request supporting documents |

Three controls are built in:

- **Totals check:** subtotal + tax must equal the total, which catches AI misreads.
- **Transposition check:** a classic accounting test for swapped digits.
- **Human review:** the extracted data can be edited in the app before reconciling.

## Results on the test set

The sample data has 50 invoices in 3 different layouts, a bank statement, and **12 planted errors** (3 duplicates, 4 amount mismatches, 3 unpaid invoices, 2 unexplained payments). All of it is fictional.

| Extraction method | Fields read correctly | Items classified correctly | Planted errors caught |
|---|---|---|---|
| Rule-based (regex) baseline | 84% (fails on the unfamiliar layout) | 44 / 52 | 11 / 12 |
| Gemini AI | _run `python scripts/evaluate.py --method gemini`_ | | |
| Perfect extraction (tests matching logic only) | 100% | 52 / 52 | 12 / 12 |

## Run it locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GEMINI_API_KEY=your_key     # free key from Google AI Studio (optional: rule-based mode works without one)
streamlit run app.py
```

Other commands:

```bash
pytest                                        # run the tests
python scripts/generate_test_data.py          # rebuild the sample data
python scripts/evaluate.py --method gemini    # measure accuracy
```

## Deploy (free)

1. Push this folder to a public GitHub repository.
2. Go to share.streamlit.io, choose **New app**, and select the repo with `app.py` as the main file.
3. In the app's **Settings → Secrets**, add `GEMINI_API_KEY = "..."`.

## Project structure

```
app.py                       Streamlit web app
recon/extract.py             Step 1: AI and rule-based invoice extraction
recon/match.py               Step 2: reconciliation rules
recon/report.py              Step 3: Excel export
scripts/generate_test_data.py   builds the fictional sample data with planted errors
scripts/evaluate.py          measures accuracy against the answer key
tests/test_recon.py          unit tests
sample_data/                 invoices, bank statement, answer key
```

**Tech:** Python, pandas, Google Gemini API (structured JSON output), RapidFuzz, pdfplumber, Streamlit, openpyxl, pytest
