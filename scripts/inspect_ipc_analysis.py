from pathlib import Path
from openpyxl import load_workbook


project_folder = Path(__file__).parent.parent
input_folder = project_folder / "input"

excel_files = list(input_folder.glob("*.xlsx"))

if not excel_files:
    raise FileNotFoundError(
        "No CIRV workbook found in input."
    )

workbook_path = excel_files[0]

workbook = load_workbook(
    workbook_path,
    read_only=True,
    data_only=True,
)

sheet = workbook["IPC Analysis"]

print("Inspecting:")
print(sheet.title)
print("=" * 80)

# Show the first 12 rows and first 20 columns
for row_number in range(1, 13):

    print()
    print(f"ROW {row_number}")

    for column_number in range(
        1,
        min(sheet.max_column, 20) + 1
    ):

        value = sheet.cell(
            row=row_number,
            column=column_number,
        ).value

        if value is not None:
            print(
                f"Column {column_number}: {value}"
            )