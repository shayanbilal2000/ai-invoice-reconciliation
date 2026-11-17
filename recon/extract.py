"""
STEP 1 OF THE PIPELINE: read each invoice PDF and pull out the fields we need.

Two ways to do it:

  extract_with_gemini()  -> sends the PDF to Google's Gemini model and asks for JSON back.
                            Works on ANY invoice layout, because the model reads it like a human would.

  extract_with_rules()   -> the "old-school" way: pull the text out of the PDF and search for known labels
                            like "Invoice No:" with regular expressions. Free and fast, but it breaks as soon
                            as a vendor uses a label we didn't plan for.

Keeping both is deliberate. Comparing them on the same test set shows exactly what the AI adds
(a good interview talking point).
"""
import io
import json
import re
import time
from datetime import datetime

import pdfplumber
from pydantic import BaseModel, Field

# Check Google AI Studio for the newest "Flash" model name and change this if needed.
DEFAULT_MODEL = "gemini-2.5-flash"

# The columns every extractor must return, in this order.
FIELDS = ["source_file", "vendor_name", "invoice_number", "invoice_date", "subtotal", "sales_tax",
          "total_amount", "extraction_check"]


class Invoice(BaseModel):
    """The exact shape we want back from the AI. Gemini is forced to follow this schema."""
    vendor_name: str = Field(description="Name of the company that issued the invoice (the seller), not the buyer")
    invoice_number: str = Field(description="Invoice / bill number exactly as printed")
    invoice_date: str = Field(description="Invoice date in YYYY-MM-DD format")
    subtotal: float = Field(description="Amount before sales tax")
    sales_tax: float = Field(description="Sales tax / GST amount, 0 if none")
    total_amount: float = Field(description="Final amount payable including tax")


PROMPT = (
    "You are an accounts payable assistant. Extract the fields from this supplier invoice. "
    "Return amounts as plain numbers without commas or currency symbols. "
    "If a field is genuinely missing, use an empty string for text and 0 for numbers. Do not guess."
)


def check_totals(subtotal, sales_tax, total):
    """A simple control: subtotal + tax should equal the total. If not, a human should look at it.
    This catches AI misreads AND genuine errors on the invoice itself."""
    try:
        return "OK" if abs(float(subtotal) + float(sales_tax) - float(total)) <= 1 else "Totals don't add up"
    except (TypeError, ValueError):
        return "Missing amounts"


def extract_with_gemini(pdf_bytes, filename, api_key, model=DEFAULT_MODEL, retries=4):
    """Send one PDF to Gemini and get structured data back."""
    from google import genai          # imported here so the app still runs without the package/key
    from google.genai import types, errors

    client = genai.Client(api_key=api_key)
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"), PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=Invoice,   # forces valid JSON in exactly our shape
                    temperature=0,             # we want consistent answers, not creativity
                ),
            )
            inv = Invoice.model_validate_json(response.text)
            break
        except errors.APIError as e:
            # 429 = rate limit (free tier allows a limited number of requests per minute). Wait and retry.
            if getattr(e, "code", None) == 429 and attempt < retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            raise
    row = {"source_file": filename, **inv.model_dump()}
    row["extraction_check"] = check_totals(inv.subtotal, inv.sales_tax, inv.total_amount)
    return row


# ---------------------------------------------------------------- rule-based baseline
def _num(s):
    return float(s.replace(",", "")) if s else None


def _date(s):
    for fmt in ("%d/%m/%Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


# Each pattern only knows the labels we planned for. That's the weakness.
PATTERNS = {
    "invoice_number": r"(?:Invoice No:|INVOICE #)\s*([A-Z]+-\d+)",
    "invoice_date": r"(?:Invoice Date:|Date)\s+(\d{2}/\d{2}/\d{4}|\d{2} \w{3} \d{4})",
    "subtotal": r"(?:Subtotal:|Net amount)\s*([\d,]+)",
    "sales_tax": r"(?:Sales Tax \(18%\):|GST @ 18%)\s*([\d,]+)",
    "total_amount": r"(?:Total Amount Due \(PKR\):|GRAND TOTAL Rs\.)\s*([\d,]+)",
}


def extract_with_rules(pdf_bytes, filename):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    found = {k: (m.group(1) if (m := re.search(p, text)) else "") for k, p in PATTERNS.items()}
    lines = [l for l in text.splitlines() if l.strip()]
    # Guess: the vendor name is the first line that isn't an "INVOICE ..." or "Date ..." header line
    vendor = next((l for l in lines if not l.strip().upper().startswith(("INVOICE", "DATE"))), "")

    row = {
        "source_file": filename,
        "vendor_name": vendor.strip(),
        "invoice_number": found["invoice_number"],
        "invoice_date": _date(found["invoice_date"]) if found["invoice_date"] else "",
        "subtotal": _num(found["subtotal"]),
        "sales_tax": _num(found["sales_tax"]),
        "total_amount": _num(found["total_amount"]),
    }
    row["extraction_check"] = check_totals(row["subtotal"], row["sales_tax"], row["total_amount"])
    return row


if __name__ == "__main__":
    # Quick manual test:  python -m recon.extract sample_data/invoices/invoice_001.pdf
    import sys
    path = sys.argv[1]
    print(json.dumps(extract_with_rules(open(path, "rb").read(), path), indent=2))
