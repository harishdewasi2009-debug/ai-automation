"""Creates sample_input.xlsx - REPLACE the example rows with 10 companies you know."""
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "Companies"
ws.append(["Company name", "Type", "Country"])
ws.append(["Example Company One", "Supplier", "Netherlands"])   # example row - replace
ws.append(["Example Company Two", "Buyer", "UAE"])              # example row - replace
wb.save("sample_input.xlsx")
print("Created sample_input.xlsx")
