from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from collectors.fao_crop_prospects import (
    extract_july_2026_fao,
)


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

input_folder = (
    project_folder
    / "input"
)


# ==================================================
# EXTRACT FAO JULY 2026 DATA
# ==================================================

print(
    "Extracting FAO July 2026 data..."
)

python_fao = (
    extract_july_2026_fao()
)


# ==================================================
# FIND CIRV WORKBOOK
# ==================================================

excel_files = list(
    input_folder.glob("*.xlsx")
)

if not excel_files:

    raise FileNotFoundError(
        "No CIRV workbook found."
    )

workbook_path = excel_files[0]

print(
    f"Using CIRV workbook: "
    f"{workbook_path.name}"
)


# ==================================================
# READ CERF ALL DATA
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

    workbook_score = sheet.cell(
        row=row_number,
        column=16,
    ).value

    workbook_category = sheet.cell(
        row=row_number,
        column=17,
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

            "Workbook_FAO_Score":
                workbook_score,

            "Workbook_FAO_Category":
                workbook_category,
        }
    )


cerf = pd.DataFrame(
    records
)


# ==================================================
# CLEAN WORKBOOK SCORE
# ==================================================

cerf[
    "Workbook_FAO_Score"
] = pd.to_numeric(
    cerf[
        "Workbook_FAO_Score"
    ],
    errors="coerce",
)


# FAO methodology:
#
# Country not listed = 0
#
# Therefore a blank workbook score, if any,
# is also represented explicitly for validation.

cerf[
    "Workbook_FAO_Score"
] = cerf[
    "Workbook_FAO_Score"
].fillna(0)


# ==================================================
# PREPARE PYTHON FAO RESULTS
# ==================================================

python_data = python_fao[
    [
        "ISO3",
        "FAO_Score",
        "FAO_Category",
        "PDF_Page",
        "Evidence",
    ]
].copy()


python_data = python_data.rename(
    columns={
        "FAO_Score":
            "Python_FAO_Score",

        "FAO_Category":
            "Python_FAO_Category",
    }
)


# ==================================================
# JOIN BY ISO3
# ==================================================

comparison = cerf.merge(
    python_data,
    on="ISO3",
    how="left",
)


# ==================================================
# APPLY FAO ZERO RULE
# ==================================================

# A country absent from FAO's list receives zero.
#
# This is intentionally different from sources
# such as IPC where missing source data must
# remain missing.

comparison[
    "Python_FAO_Score"
] = comparison[
    "Python_FAO_Score"
].fillna(0)


# ==================================================
# NORMALIZE CATEGORIES
# ==================================================

def normalize_category(value):

    if pd.isna(value):
        return ""

    text = str(
        value
    ).strip().lower()

    if text in [
        "",
        "0",
        "nan",
        "none",
    ]:
        return ""

    if "localized" in text:
        return "Localized"

    if "access" in text:
        return "Access"

    if "shortfall" in text:
        return "Shortfall"

    return str(value).strip()


comparison[
    "Workbook_Category"
] = comparison[
    "Workbook_FAO_Category"
].apply(
    normalize_category
)


comparison[
    "Python_Category"
] = comparison[
    "Python_FAO_Category"
].apply(
    normalize_category
)


# ==================================================
# SCORE VALIDATION
# ==================================================

comparison[
    "Score_Status"
] = comparison.apply(
    lambda row:
        "MATCH"
        if row["Workbook_FAO_Score"]
        == row["Python_FAO_Score"]
        else "MISMATCH",
    axis=1,
)


# ==================================================
# CATEGORY VALIDATION
# ==================================================

def validate_category(row):

    workbook_score = row[
        "Workbook_FAO_Score"
    ]

    python_score = row[
        "Python_FAO_Score"
    ]

    workbook_category = row[
        "Workbook_Category"
    ]

    python_category = row[
        "Python_Category"
    ]


    # ----------------------------------------------
    # NOT LISTED BY FAO
    #
    # Score 0 means no FAO vulnerability category
    # is required.
    # ----------------------------------------------

    if (
        workbook_score == 0
        and python_score == 0
    ):

        return "MATCH"


    # ----------------------------------------------
    # LISTED BY FAO
    # ----------------------------------------------

    if (
        workbook_category
        == python_category
    ):

        return "MATCH"


    return "MISMATCH"


comparison[
    "Category_Status"
] = comparison.apply(
    validate_category,
    axis=1,
)


# ==================================================
# OVERALL VALIDATION
# ==================================================

comparison[
    "Overall_Status"
] = comparison.apply(
    lambda row:
        "VALIDATED"
        if (
            row["Score_Status"]
            == "MATCH"
            and
            row["Category_Status"]
            == "MATCH"
        )
        else "REVIEW",
    axis=1,
)


# ==================================================
# OUTPUT TABLE
# ==================================================

validation = comparison[
    [
        "Country",
        "ISO3",

        "Workbook_FAO_Score",
        "Python_FAO_Score",
        "Score_Status",

        "Workbook_Category",
        "Python_Category",
        "Category_Status",

        "PDF_Page",
        "Evidence",

        "Overall_Status",
    ]
].copy()


# ==================================================
# SAVE VALIDATION
# ==================================================

output_file = (
    project_folder
    / "fao_historical_parity.xlsx"
)


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
    "FAO HISTORICAL PARITY TEST"
)
print("=" * 80)


print(
    f"CIRV countries checked: "
    f"{len(validation)}"
)


# ==================================================
# SCORE RESULTS
# ==================================================

score_matches = (
    validation[
        "Score_Status"
    ]
    .eq("MATCH")
    .sum()
)


score_mismatches = (
    validation[
        "Score_Status"
    ]
    .eq("MISMATCH")
    .sum()
)


print()
print(
    "SCORE VALIDATION"
)

print("-" * 40)

print(
    f"MATCH: {score_matches}"
)

print(
    f"MISMATCH: {score_mismatches}"
)


# ==================================================
# CATEGORY RESULTS
# ==================================================

category_matches = (
    validation[
        "Category_Status"
    ]
    .eq("MATCH")
    .sum()
)


category_mismatches = (
    validation[
        "Category_Status"
    ]
    .eq("MISMATCH")
    .sum()
)


print()
print(
    "CATEGORY VALIDATION"
)

print("-" * 40)

print(
    f"MATCH: {category_matches}"
)

print(
    f"MISMATCH: {category_mismatches}"
)


# ==================================================
# OVERALL
# ==================================================

validated = (
    validation[
        "Overall_Status"
    ]
    .eq("VALIDATED")
    .sum()
)


review = (
    validation[
        "Overall_Status"
    ]
    .eq("REVIEW")
    .sum()
)


print()
print(
    "OVERALL"
)

print("-" * 40)


print(
    f"Validated: "
    f"{validated}/{len(validation)}"
)

print(
    f"Requires review: "
    f"{review}"
)


# ==================================================
# FAO LIST SUMMARY
# ==================================================

listed_countries = validation[
    validation[
        "Python_FAO_Score"
    ]
    .eq(2)
]


print()
print(
    "FAO COUNTRIES REQUIRING "
    "EXTERNAL ASSISTANCE"
)

print("-" * 40)


print(
    f"Countries extracted: "
    f"{len(listed_countries)}"
)


print()

print(
    listed_countries[
        [
            "Country",
            "ISO3",
            "Python_FAO_Score",
            "Python_Category",
            "PDF_Page",
        ]
    ]
    .to_string(index=False)
)


# ==================================================
# GENUINE PROBLEMS
# ==================================================

problems = validation[
    validation[
        "Overall_Status"
    ]
    .eq("REVIEW")
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

                "Workbook_FAO_Score",
                "Python_FAO_Score",

                "Workbook_Category",
                "Python_Category",

                "Score_Status",
                "Category_Status",
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