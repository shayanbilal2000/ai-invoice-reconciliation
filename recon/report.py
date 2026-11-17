"""STEP 3: export the reconciliation to an Excel file the finance team can actually use."""
import io

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from recon.match import summary

COLORS = {
    "Matched": "E2F0D9",
    "Amount Mismatch": "FFF2CC",
    "Duplicate Invoice": "FCE4D6",
    "Unpaid Invoice": "DDEBF7",
    "Unexplained Payment": "F8CBAD",
}


def to_excel(results: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        summary(results).to_excel(xl, sheet_name="Summary", index=False)
        results.to_excel(xl, sheet_name="Details", index=False)
        for status in ["Amount Mismatch", "Duplicate Invoice", "Unpaid Invoice", "Unexplained Payment"]:
            part = results[results["status"] == status]
            if not part.empty:
                part.to_excel(xl, sheet_name=status[:31], index=False)

        for ws in xl.book.worksheets:
            for cell in ws[1]:
                cell.font = Font(bold=True)
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col) + 2
                ws.column_dimensions[get_column_letter(col[0].column)].width = min(width, 60)
            ws.freeze_panes = "A2"
            # Colour each row by its status (status is always column A)
            for row in ws.iter_rows(min_row=2):
                color = COLORS.get(str(row[0].value))
                if color:
                    for c in row:
                        c.fill = PatternFill("solid", fgColor=color)
            # Thousands separators on money columns
            for row in ws.iter_rows(min_row=2):
                for c in row:
                    if isinstance(c.value, (int, float)):
                        c.number_format = "#,##0"
    return buf.getvalue()
