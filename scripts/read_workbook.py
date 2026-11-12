from pathlib import Path

import pandas as pd
from openpyxl import load_workbook


# Locate the CIRV project and input folder
project_folder = Path(__file__).parent.parent
input_folder = project_folder / "input"

# Find the Excel workbook
excel_files = list(input_folder.glob("*.xlsx"))

if not excel_files:
    raise FileNotFoundError("No Excel workbook found in the input folder.")

workbook_path = excel_files[0]

print(f"Opening: {workbook_path.name}")


# Open the workbook using Excel's saved calculated values
workbook = load_workbook(
    workbook_path,
    read_only=True,
    data_only=True
)

# Open the main CIRV calculation sheet
sheet = workbook["CERF UFE 2026-I All Data"]

records = []

# Country data starts on row 5
for row_number in range(5, sheet.max_row + 1):

    country = sheet.cell(row=row_number, column=1).value
    iso3 = sheet.cell(row=row_number, column=2).value

    # Ignore empty rows
    if not country or not iso3:
        continue

    records.append(
        {
            "Country": country,
            "ISO3": iso3,

            # Main CIRV components
            "INFORM_Risk": sheet.cell(
                row=row_number,
                column=5
            ).value,

            "INFORM_Severity": sheet.cell(
                row=row_number,
                column=7
            ).value,

            "Early_Warning": sheet.cell(
                row=row_number,
                column=10
            ).value,

            "Food": sheet.cell(
                row=row_number,
                column=20
            ).value,

            "Conflict": sheet.cell(
                row=row_number,
                column=24
            ).value,

            "CERF_Component": sheet.cell(
                row=row_number,
                column=25
            ).value,

            # CIRV results
            "CIRV_Without_Severity": sheet.cell(
                row=row_number,
                column=26
            ).value,

            "CIRV_With_Severity": sheet.cell(
                row=row_number,
                column=27
            ).value,

            "Final_CIRV": sheet.cell(
                row=row_number,
                column=28
            ).value,
        }
    )


# Convert everything into a table
df = pd.DataFrame(records)


# Save the Excel results as our permanent comparison baseline
output_path = project_folder / "cirv_baseline.csv"

df.to_csv(
    output_path,
    index=False
)


# Tell us what happened
print()
print("BASELINE CREATED SUCCESSFULLY")
print(f"Countries: {len(df)}")
print(f"Saved to: {output_path}")
print()

print("First 10 countries:")
print()

print(
    df.head(10)
    .round(2)
    .to_string(index=False)
)