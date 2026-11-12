from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from collectors.fewsnet_faob import (
    extract_july_2026_fewsnet,
)


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

input_folder = (
    project_folder
    / "input"
)

output_file = (
    project_folder
    / "fewsnet_faob_historical_parity.xlsx"
)


# ==================================================
# EXTRACT JULY 2026 FEWS NET RESULTS
# ==================================================

print(
    "Extracting FEWS NET July 2026 data..."
)

(
    report,
    pdf_file,
    python_results,
    evidence_file,
) = extract_july_2026_fewsnet()


python_data = python_results[
    [
        "ISO3",
        "CERF_Country",
        "FEWSNET_IPC",
        "FEWSNET_Classification",
        "PDF_Page",
        "Evidence",
    ]
].copy()


python_data = python_data.rename(
    columns={
        "CERF_Country":
            "Python_Country",

        "FEWSNET_IPC":
            "Python_FEWSNET_IPC",

        "FEWSNET_Classification":
            "Python_Classification",
    }
)


# ==================================================
# FIND CIRV WORKBOOK
# ==================================================

excel_files = list(
    input_folder.glob("*.xlsx")
)

if not excel_files:

    raise FileNotFoundError(
        "No CIRV workbook was found "
        "in the input folder."
    )


workbook_path = excel_files[0]


print(
    f"Using CIRV workbook: "
    f"{workbook_path.name}"
)


# ==================================================
# READ WORKBOOK FEWS NET VALUES
# ==================================================

workbook = load_workbook(
    workbook_path,
    read_only=True,
    data_only=True,
)


sheet = workbook[
    "CERF UFE 2026-I All Data"
]


records = []


for row_number in range(
    5,
    sheet.max_row + 1,
):

    country = sheet.cell(
        row=row_number,
        column=1,
    ).value

    iso3 = sheet.cell(
        row=row_number,
        column=2,
    ).value

    # Column 12:
    # FEWSNet Food Assistance Outlook Brief
    # July 2026
    workbook_fewsnet = sheet.cell(
        row=row_number,
        column=12,
    ).value


    if not country or not iso3:
        continue


    records.append(
        {
            "Country":
                str(country).strip(),

            "ISO3":
                str(iso3)
                .strip()
                .upper(),

            "Workbook_FEWSNET_IPC":
                workbook_fewsnet,
        }
    )


workbook_data = pd.DataFrame(
    records
)


workbook_data[
    "Workbook_FEWSNET_IPC"
] = pd.to_numeric(
    workbook_data[
        "Workbook_FEWSNET_IPC"
    ],
    errors="coerce",
)


# ==================================================
# TREAT ZERO AS NO FEWS NET DATA
# ==================================================

# In the workbook's Food methodology, FEWS NET
# contributes only when its value is greater than 0.
#
# Therefore:
#
# blank = unavailable
# zero  = unavailable
#
# Neither should be interpreted as IPC Phase 0.

workbook_data.loc[
    workbook_data[
        "Workbook_FEWSNET_IPC"
    ] <= 0,
    "Workbook_FEWSNET_IPC",
] = pd.NA


# ==================================================
# JOIN BY ISO3
# ==================================================

comparison = workbook_data.merge(
    python_data,
    on="ISO3",
    how="left",
)


# ==================================================
# VALIDATION STATUS
# ==================================================

def classify_result(row):

    workbook_value = row[
        "Workbook_FEWSNET_IPC"
    ]

    python_value = row[
        "Python_FEWSNET_IPC"
    ]


    workbook_has_value = pd.notna(
        workbook_value
    )

    python_has_value = pd.notna(
        python_value
    )


    # Both sources contain an IPC value.
    if (
        workbook_has_value
        and python_has_value
    ):

        if (
            float(workbook_value)
            == float(python_value)
        ):

            return "MATCH"

        return "MISMATCH"


    # Neither has FEWS NET data.
    if (
        not workbook_has_value
        and not python_has_value
    ):

        return "MATCH_NO_DATA"


    # Valid report value was omitted from Excel.
    if (
        not workbook_has_value
        and python_has_value
    ):

        return "WORKBOOK_MISSING_VALUE"


    # Excel has a value that Python did not extract.
    return "SOURCE_MISSING_VALUE"


comparison[
    "Validation_Status"
] = comparison.apply(
    classify_result,
    axis=1,
)


comparison["Difference"] = (
    comparison["Python_FEWSNET_IPC"]
    - comparison["Workbook_FEWSNET_IPC"]
)


# ==================================================
# OUTPUT TABLE
# ==================================================

validation = comparison[
    [
        "Country",
        "ISO3",

        "Workbook_FEWSNET_IPC",
        "Python_FEWSNET_IPC",

        "Validation_Status",
        "Difference",

        "Python_Classification",
        "PDF_Page",
        "Evidence",
    ]
].copy()


status_order = {
    "MISMATCH": 1,
    "SOURCE_MISSING_VALUE": 2,
    "WORKBOOK_MISSING_VALUE": 3,
    "MATCH": 4,
    "MATCH_NO_DATA": 5,
}


validation[
    "Status_Order"
] = validation[
    "Validation_Status"
].map(
    status_order
)


validation = validation.sort_values(
    [
        "Status_Order",
        "Country",
    ]
)


validation = validation.drop(
    columns=[
        "Status_Order"
    ]
)


# ==================================================
# SAVE VALIDATION FILE
# ==================================================

validation.to_excel(
    output_file,
    index=False,
)


# ==================================================
# SUMMARY
# ==================================================

print()
print("=" * 80)
print(
    "FEWS NET HISTORICAL PARITY TEST"
)
print("=" * 80)


print(
    f"CIRV countries checked: "
    f"{len(validation)}"
)


for status in [
    "MATCH",
    "MATCH_NO_DATA",
    "MISMATCH",
    "WORKBOOK_MISSING_VALUE",
    "SOURCE_MISSING_VALUE",
]:

    count = (
        validation[
            "Validation_Status"
        ]
        .eq(status)
        .sum()
    )

    print(
        f"{status}: {count}"
    )


# ==================================================
# ACCEPTED VALIDATION
# ==================================================

accepted_statuses = [
    "MATCH",
    "MATCH_NO_DATA",
    "WORKBOOK_MISSING_VALUE",
]


accepted = validation[
    "Validation_Status"
].isin(
    accepted_statuses
).sum()


print()
print(
    f"Automation validated: "
    f"{accepted}/{len(validation)}"
)


# ==================================================
# EXTRACTED REPORT COUNTRIES
# ==================================================

report_countries = validation[
    validation[
        "Python_FEWSNET_IPC"
    ].notna()
]


print()
print(
    "FEWS NET COUNTRIES EXTRACTED"
)

print("-" * 80)


print(
    f"Countries extracted: "
    f"{len(report_countries)}"
)


print()


print(
    report_countries[
        [
            "Country",
            "ISO3",
            "Python_FEWSNET_IPC",
            "Python_Classification",
            "PDF_Page",
        ]
    ]
    .to_string(index=False)
)


# ==================================================
# GENUINE VALIDATION PROBLEMS
# ==================================================

problems = validation[
    validation[
        "Validation_Status"
    ].isin(
        [
            "MISMATCH",
            "SOURCE_MISSING_VALUE",
        ]
    )
]


print()
print(
    "GENUINE VALIDATION PROBLEMS"
)

print("-" * 80)


if problems.empty:

    print(
        "None."
    )

else:

    print(
        problems[
            [
                "Country",
                "ISO3",

                "Workbook_FEWSNET_IPC",
                "Python_FEWSNET_IPC",

                "Validation_Status",
                "Python_Classification",
                "PDF_Page",
            ]
        ]
        .to_string(index=False)
    )


# ==================================================
# LIKELY WORKBOOK OMISSIONS
# ==================================================

omissions = validation[
    validation[
        "Validation_Status"
    ].eq(
        "WORKBOOK_MISSING_VALUE"
    )
]


print()
print(
    "LIKELY WORKBOOK OMISSIONS"
)

print("-" * 80)


if omissions.empty:

    print(
        "None."
    )

else:

    print(
        omissions[
            [
                "Country",
                "ISO3",

                "Workbook_FEWSNET_IPC",
                "Python_FEWSNET_IPC",

                "Python_Classification",
                "PDF_Page",
            ]
        ]
        .to_string(index=False)
    )


print()
print(
    "Validation file saved to:"
)

print(
    output_file
)