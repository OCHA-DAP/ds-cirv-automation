from pathlib import Path
from openpyxl import load_workbook


project_folder = Path(__file__).parent.parent

severity_folder = (
    project_folder
    / "data"
    / "raw"
    / "inform_severity"
)

excel_files = list(
    severity_folder.glob("*.xlsx")
)

if not excel_files:
    raise FileNotFoundError(
        "No INFORM Severity workbook found."
    )

severity_file = max(
    excel_files,
    key=lambda file: file.stat().st_mtime
)

workbook = load_workbook(
    severity_file,
    read_only=True,
    data_only=True
)

sheet = workbook[
    "INFORM Severity - all crises"
]

print("Inspecting:")
print(sheet.title)
print("-" * 80)

for row_number in range(1, 11):

    print()
    print(f"ROW {row_number}")

    for column_number in range(
        1,
        min(sheet.max_column, 20) + 1
    ):

        value = sheet.cell(
            row=row_number,
            column=column_number
        ).value

        if value is not None:

            print(
                f"Column {column_number}: {value}"
            )