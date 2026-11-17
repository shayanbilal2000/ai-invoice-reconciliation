"""
Generates FAKE test data so the app can be built and measured without real company documents.

Creates in sample_data/:
  invoices/*.pdf      50 supplier invoices in 3 different layouts (like real life: every vendor's invoice looks different)
  bank_statement.csv  the company's bank statement for the same period
  answer_key.csv      the "correct answers": which items we deliberately broke, so we can measure the app

Errors planted on purpose (this is what the app must catch):
  - 3 duplicate invoices      (vendor sent the same invoice twice; we must not pay it twice)
  - 4 amount mismatches       (2 typing mistakes when paying, 2 short-payments e.g. tax withheld)
  - 3 unpaid invoices         (invoice received, never paid)
  - 2 unexplained payments    (money left the bank with no invoice behind it)

All vendor names are fictional.

Run:  python scripts/generate_test_data.py
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

random.seed(42)  # same "random" data every time -> results are reproducible

ROOT = Path(__file__).resolve().parent.parent / "sample_data"
INV_DIR = ROOT / "invoices"

SALES_TAX_RATE = 0.18  # Pakistan general sales tax rate

# (Full legal name on the invoice, how the bank shortens it on the statement, layout used by this vendor)
VENDORS = [
    ("Margalla Office Supplies (Pvt) Ltd", "MARGALLA OFFICE SUPP", "classic"),
    ("Indus Cloud Hosting Services", "INDUS CLOUD HOST", "modern"),
    ("Rawal Logistics & Couriers", "RAWAL LOGISTICS", "compact"),
    ("Potohar Power Solutions", "POTOHAR POWER SOL", "classic"),
    ("Blue Area Facility Management", "BLUEAREA FACILITY MGT", "modern"),
    ("Kohsar Printing Press", "KOHSAR PRINTING", "compact"),
    ("Faisal Town Internet Services", "FAISALTOWN INTERNET", "modern"),
    ("Saddar IT Hardware Traders", "SADDAR IT HARDWARE", "classic"),
]

ITEMS = {
    "Margalla Office Supplies (Pvt) Ltd": [("A4 Paper Ream", 1450), ("Toner Cartridge", 8900), ("Stationery Pack", 2300)],
    "Indus Cloud Hosting Services": [("VPS Hosting - Monthly", 18500), ("Backup Storage 500GB", 6200), ("SSL Certificate", 4800)],
    "Rawal Logistics & Couriers": [("Intercity Courier", 650), ("Same-day Delivery", 1200), ("Cargo Shipment", 9800)],
    "Potohar Power Solutions": [("UPS Battery", 24500), ("Generator Service", 15000), ("Solar Panel Cleaning", 7000)],
    "Blue Area Facility Management": [("Office Cleaning - Monthly", 45000), ("Pest Control", 12000), ("AC Maintenance", 8500)],
    "Kohsar Printing Press": [("Business Cards (box)", 1800), ("Brochures (100)", 6500), ("Banner Printing", 4200)],
    "Faisal Town Internet Services": [("Fiber 100Mbps - Monthly", 22000), ("Static IP", 3500), ("Router Rental", 1500)],
    "Saddar IT Hardware Traders": [("Wireless Mouse", 2400), ("Keyboard", 3200), ("SSD 512GB", 14500), ("Monitor 24in", 38000)],
}


def make_invoice(n, vendor):
    """Create one invoice as a Python dict."""
    name, alias, layout = vendor
    lines = []
    for item, price in random.sample(ITEMS[name], k=random.randint(1, min(3, len(ITEMS[name])))):
        qty = random.randint(1, 6)
        lines.append((item, qty, price, qty * price))
    subtotal = sum(l[3] for l in lines)
    tax = round(subtotal * SALES_TAX_RATE)
    inv_date = date(2026, 7, 1) + timedelta(days=random.randint(0, 80))
    prefix = {"classic": "INV", "modern": "IC", "compact": "B"}[layout]
    return {
        "file": f"invoice_{n:03d}.pdf",
        "vendor": name, "alias": alias, "layout": layout,
        "invoice_number": f"{prefix}-{1000 + n}",
        "invoice_date": inv_date,
        "lines": lines, "subtotal": subtotal, "tax": tax, "total": subtotal + tax,
    }


# ---------------------------------------------------------------- PDF layouts
def money(x):
    return f"{x:,.0f}"


def draw_lines_table(c, inv, y, x0=20 * mm):
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x0, y, "Description"); c.drawString(x0 + 90 * mm, y, "Qty")
    c.drawString(x0 + 110 * mm, y, "Rate"); c.drawRightString(190 * mm, y, "Amount")
    c.setFont("Helvetica", 9)
    for item, qty, price, amt in inv["lines"]:
        y -= 6 * mm
        c.drawString(x0, y, item); c.drawString(x0 + 90 * mm, y, str(qty))
        c.drawString(x0 + 110 * mm, y, money(price)); c.drawRightString(190 * mm, y, money(amt))
    return y


def layout_classic(c, inv):
    c.setFont("Helvetica-Bold", 16); c.drawString(20 * mm, 270 * mm, inv["vendor"])
    c.setFont("Helvetica", 9); c.drawString(20 * mm, 264 * mm, "Islamabad, Pakistan  |  NTN 1234567-8")
    c.setFont("Helvetica-Bold", 20); c.drawRightString(190 * mm, 245 * mm, "TAX INVOICE")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, 245 * mm, "Bill To: Kestrel Digital (Pvt) Ltd")
    c.drawString(20 * mm, 235 * mm, f"Invoice No: {inv['invoice_number']}")
    c.drawString(20 * mm, 229 * mm, f"Invoice Date: {inv['invoice_date']:%d/%m/%Y}")
    y = draw_lines_table(c, inv, 210 * mm)
    y -= 12 * mm
    c.drawRightString(160 * mm, y, "Subtotal:"); c.drawRightString(190 * mm, y, money(inv["subtotal"]))
    c.drawRightString(160 * mm, y - 6 * mm, "Sales Tax (18%):"); c.drawRightString(190 * mm, y - 6 * mm, money(inv["tax"]))
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(160 * mm, y - 14 * mm, "Total Amount Due (PKR):"); c.drawRightString(190 * mm, y - 14 * mm, money(inv["total"]))


def layout_modern(c, inv):
    c.setFillGray(0.15); c.rect(0, 255 * mm, 210 * mm, 42 * mm, fill=1, stroke=0); c.setFillGray(1)
    c.setFont("Helvetica-Bold", 22); c.drawString(20 * mm, 275 * mm, "INVOICE")
    c.setFont("Helvetica", 11); c.drawString(20 * mm, 265 * mm, inv["vendor"])
    c.drawRightString(190 * mm, 275 * mm, f"INVOICE # {inv['invoice_number']}")
    c.drawRightString(190 * mm, 267 * mm, f"Date  {inv['invoice_date']:%d %b %Y}")
    c.setFillGray(0)
    c.setFont("Helvetica", 10); c.drawString(20 * mm, 242 * mm, "Billed to: Kestrel Digital Pvt. Ltd., Islamabad")
    y = draw_lines_table(c, inv, 225 * mm)
    y -= 12 * mm
    c.drawRightString(160 * mm, y, "Net amount"); c.drawRightString(190 * mm, y, money(inv["subtotal"]))
    c.drawRightString(160 * mm, y - 6 * mm, "GST @ 18%"); c.drawRightString(190 * mm, y - 6 * mm, money(inv["tax"]))
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(160 * mm, y - 15 * mm, "GRAND TOTAL  Rs."); c.drawRightString(190 * mm, y - 15 * mm, money(inv["total"]))


def layout_compact(c, inv):
    # Deliberately unusual: labels a simple rule-based parser won't expect.
    c.setFont("Times-Bold", 14); c.drawCentredString(105 * mm, 275 * mm, inv["vendor"].upper())
    c.setFont("Times-Roman", 10)
    c.drawCentredString(105 * mm, 269 * mm, "Bill / Cash Memo")
    c.drawString(20 * mm, 255 * mm, f"Bill No. {inv['invoice_number']}")
    c.drawRightString(190 * mm, 255 * mm, f"Dated: {inv['invoice_date']:%B %d, %Y}")
    c.drawString(20 * mm, 248 * mm, "M/s Kestrel Digital (Pvt) Ltd")
    y = draw_lines_table(c, inv, 232 * mm)
    y -= 12 * mm
    c.setFont("Times-Roman", 10)
    c.drawString(20 * mm, y, f"Amount before tax {money(inv['subtotal'])}  +  S.Tax {money(inv['tax'])}")
    c.setFont("Times-Bold", 12)
    c.drawString(20 * mm, y - 9 * mm, f"Net Payable: Rupees {money(inv['total'])}/-")


def write_pdf(inv):
    c = canvas.Canvas(str(INV_DIR / inv["file"]), pagesize=A4)
    {"classic": layout_classic, "modern": layout_modern, "compact": layout_compact}[inv["layout"]](c, inv)
    c.setFont("Helvetica-Oblique", 7); c.drawString(20 * mm, 15 * mm, "SAMPLE DATA - fictional vendor for testing")
    c.save()


# ---------------------------------------------------------------- bank statement
def bank_description(alias, inv_no):
    style = random.choice(["ibft", "ibft_ref", "chq", "online"])
    if style == "ibft":
        return f"IBFT TO {alias}"
    if style == "ibft_ref":
        return f"IBFT TO {alias} REF {inv_no}"
    if style == "chq":
        return f"CHQ {random.randint(100000, 999999)} {alias}"
    return f"ONLINE TRF {alias}"


def transpose_digits(amount):
    """Simulate a typing mistake: swap two neighbouring digits (12,500 -> 15,200 style)."""
    s = str(amount)
    for _ in range(20):
        i = random.randint(0, len(s) - 2)
        if s[i] != s[i + 1]:
            return int(s[:i] + s[i + 1] + s[i] + s[i + 2:])
    return amount + 90


def main():
    INV_DIR.mkdir(parents=True, exist_ok=True)
    for old in INV_DIR.glob("*.pdf"):
        old.unlink()

    # 47 unique invoices
    unique = [make_invoice(n, random.choice(VENDORS)) for n in range(1, 48)]

    # Choose which invoices get which planted problem
    idx = random.sample(range(len(unique)), 10)
    unpaid_idx, mismatch_idx, dup_idx = idx[:3], idx[3:7], idx[7:10]

    answer = []  # rows for answer_key.csv
    bank_rows = []

    for i, inv in enumerate(unique):
        if i in unpaid_idx:
            answer.append((inv["file"], "", "Unpaid Invoice"))
            continue
        pay_date = inv["invoice_date"] + timedelta(days=random.randint(1, 21))
        paid = inv["total"]
        status = "Matched"
        if i in mismatch_idx:
            k = mismatch_idx.index(i)
            # first two: typing mistakes; last two: ~4.5% short-paid (e.g. withholding tax deducted)
            paid = transpose_digits(inv["total"]) if k < 2 else round(inv["total"] * 0.955)
            status = "Amount Mismatch"
        bank_rows.append({"date": pay_date, "description": bank_description(inv["alias"], inv["invoice_number"]),
                          "debit": paid, "credit": 0})
        answer.append((inv["file"], "", status))

    # Duplicates: the same invoice arrives a second time as a separate file (paid only once)
    all_invoices = list(unique)
    for n, i in enumerate(dup_idx, start=48):
        copy = dict(unique[i])
        copy["file"] = f"invoice_{n:03d}.pdf"
        all_invoices.append(copy)
        answer.append((copy["file"], "", "Duplicate Invoice"))

    # Unexplained payments: money out, no invoice anywhere
    bank_rows.append({"date": date(2026, 8, 14), "description": "IBFT TO SAFA GENERAL TRADERS", "debit": 73500, "credit": 0})
    bank_rows.append({"date": date(2026, 9, 3), "description": "CHQ 552190 KOHSAR PRINTING", "debit": 41300, "credit": 0})

    # Noise a real statement has: customer receipts (money IN) that are not supplier payments
    for _ in range(6):
        bank_rows.append({"date": date(2026, 7, 1) + timedelta(days=random.randint(0, 90)),
                          "description": f"IBFT FROM CLIENT {random.choice(['ALPHA', 'NOVA', 'ZENITH'])} SOLUTIONS",
                          "debit": 0, "credit": random.randint(150, 900) * 1000})

    for inv in all_invoices:
        write_pdf(inv)

    # Sort statement by date, give each row a bank reference number and a running balance
    bank_rows.sort(key=lambda r: r["date"])
    balance = 2_500_000
    with open(ROOT / "bank_statement.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "reference", "description", "debit", "credit", "balance"])
        for n, r in enumerate(bank_rows, start=1):
            balance += r["credit"] - r["debit"]
            ref = f"TXN{n:04d}"
            r["reference"] = ref
            w.writerow([r["date"].isoformat(), ref, r["description"], r["debit"] or "", r["credit"] or "", balance])

    for r in bank_rows:
        if r["description"] in ("IBFT TO SAFA GENERAL TRADERS", "CHQ 552190 KOHSAR PRINTING"):
            answer.append(("", r["reference"], "Unexplained Payment"))

    with open(ROOT / "answer_key.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_file", "bank_reference", "expected_status"])
        w.writerows(sorted(answer))

    # The true field values printed on each invoice, used to measure extraction accuracy
    with open(ROOT / "invoice_truth.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_file", "vendor_name", "invoice_number", "invoice_date", "subtotal", "sales_tax", "total_amount"])
        for inv in sorted(all_invoices, key=lambda x: x["file"]):
            w.writerow([inv["file"], inv["vendor"], inv["invoice_number"], inv["invoice_date"].isoformat(),
                        inv["subtotal"], inv["tax"], inv["total"]])

    print(f"Wrote {len(all_invoices)} invoices, {len(bank_rows)} bank rows to {ROOT}")


if __name__ == "__main__":
    main()
