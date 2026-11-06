import io
import re

import pandas as pd

from agent import COLUMNS

ALIASES = {
    "company name": "name", "company": "name", "name": "name",
    "type": "type", "target": "type", "buyer / supplier": "type", "buyer/supplier": "type",
    "country": "country",
}


def read_input(file) -> tuple[list[dict], list[str]]:
    """Read an uploaded Excel file. Returns (companies, warnings)."""
    df = pd.read_excel(file, dtype=str).fillna("")
    df.columns = [ALIASES.get(str(c).strip().lower(), str(c).strip().lower()) for c in df.columns]
    if "name" not in df.columns:
        raise ValueError("Excel needs a 'Company name' column (plus optional 'Type' and 'Country').")
    warnings, seen, out = [], set(), []
    for _, r in df.iterrows():
        name = re.sub(r"\s+", " ", r["name"]).strip()
        if not name:
            continue
        ctype = r.get("type", "").strip().title() or "Unknown"
        key = (name.lower(), ctype.lower())
        if key in seen:
            warnings.append(f"Duplicate skipped: {name}")
            continue
        seen.add(key)
        out.append({"name": name, "type": ctype, "country": r.get("country", "").strip()})
    return out, warnings


def export_excel(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows).reindex(columns=COLUMNS).fillna("")
    sheets = {
        "All companies": df,
        "Suppliers": df[df["Buyer / Supplier"].str.lower().str.contains("suppl")],
        "Buyers": df[df["Buyer / Supplier"].str.lower().str.contains("buyer")],
        "Missing contacts": df[(df["Business email"] == "") & (df["Contact number"] == "")],
        "Emails ready for approval": df[(df["Email draft"] != "") & (df["Email sending status"].isin(["Pending approval", "Approved"]))],
        "Research errors": df[df["Notes"] != ""],
    }
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, d in sheets.items():
            d.to_excel(xw, sheet_name=name, index=False)
            ws = xw.sheets[name]
            ws.freeze_panes = "A2"
            for i, col in enumerate(d.columns, start=1):
                width = min(60, max(14, len(col) + 2))
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    return buf.getvalue()
