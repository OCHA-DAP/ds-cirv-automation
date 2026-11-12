from pathlib import Path
from openpyxl import load_workbook


project_folder = Path(__file__).parent.parent

inform_file = (
    project_folder
    / "data"
    / "raw"
    / "inform_risk"
    / "INFORM_Risk_Mid_2026.xlsx"
)

workbook = load_workbook(
    inform_file,
    read_only=True,
    data_only=True
)

sheet = workbook["INFORM Risk 2026 (a-z)"]

print("Inspecting:")
print(sheet.title)
print()

# Show the first 10 rows and first 15 columns
for row_number in range(1, 11):

    print(f"ROW {row_number}")

    for column_number in range(1, 16):

        value = sheet.cell(
            row=row_number,
            column=column_number
        ).value

        if value is not None:
            print(
                f"  Column {column_number}: {value}"
            )

    print()