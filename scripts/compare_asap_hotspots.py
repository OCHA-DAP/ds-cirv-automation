from pathlib import Path
import zipfile
import unicodedata

import pandas as pd
from openpyxl import load_workbook


# ==================================================
# SETTINGS
# ==================================================

# The August CIRV workbook used the July 2026
# ASAP assessment.
VALIDATION_DATE = pd.Timestamp("2026-07-11")


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

input_folder = (
    project_folder
    / "input"
)

mapping_file = (
    project_folder
    / "config"
    / "countries.csv"
)

asap_zip = (
    project_folder
    / "data"
    / "raw"
    / "asap_hotspots"
    / "hotspots_ts.zip"
)


# ==================================================
# NORMALIZE COUNTRY NAMES
# ==================================================

def normalize_country_name(value):

    if pd.isna(value):
        return None

    text = str(value).strip()

    text = text.replace("’", "'")
    text = text.replace("‘", "'")

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.lower()

    for character in [
        ".",
        ",",
        "'",
        '"',
        "(",
        ")",
        "-",
        "_",
        "&",
        "/",
    ]:

        text = text.replace(
            character,
            " ",
        )

    return " ".join(
        text.split()
    )


# ==================================================
# READ ASAP HISTORICAL DATA
# ==================================================

with zipfile.ZipFile(
    asap_zip,
    "r",
) as zip_file:

    with zip_file.open(
        "hotspots_ts.csv"
    ) as csv_file:

        asap = pd.read_csv(
            csv_file,
            sep=";",
            quotechar='"',
            encoding="utf-8",
        )


print(
    f"ASAP historical rows loaded: "
    f"{len(asap)}"
)


# ==================================================
# CLEAN ASAP
# ==================================================

asap["date"] = pd.to_datetime(
    asap["date"],
    errors="coerce",
)

asap["hs_code"] = pd.to_numeric(
    asap["hs_code"],
    errors="coerce",
)

asap["Source_Country"] = (
    asap["asap0_name"]
    .astype(str)
    .str.strip()
)

asap["Normalized_Source"] = (
    asap["Source_Country"]
    .apply(normalize_country_name)
)


# ==================================================
# SELECT JULY 2026 ASSESSMENT CYCLE
# ==================================================

july = asap[
    asap["date"] == VALIDATION_DATE
].copy()


if july.empty:

    raise RuntimeError(
        "No ASAP records found for "
        "11 July 2026."
    )


print()
print(
    f"Historical assessment selected: "
    f"{VALIDATION_DATE.date()}"
)

print(
    f"ASAP rows in assessment cycle: "
    f"{len(july)}"
)


# ==================================================
# EXCLUDE NOT ASSESSED
# ==================================================

july = july[
    ~july["hs_name"]
    .astype(str)
    .str.strip()
    .str.lower()
    .eq("not assessed")
].copy()


# Valid ASAP scores only
july = july[
    july["hs_code"].isin(
        [0, 1, 2]
    )
].copy()


# ==================================================
# LOAD CENTRAL CERF COUNTRY MAPPING
# ==================================================

mapping = pd.read_csv(
    mapping_file
)

mapping["Normalized_Alias"] = (
    mapping["Source_Alias"]
    .apply(normalize_country_name)
)


mapping = (
    mapping[
        [
            "ISO3",
            "CERF_Country",
            "Normalized_Alias",
        ]
    ]
    .drop_duplicates()
)


# ==================================================
# MAP ASAP COUNTRIES TO CERF
# ==================================================

july = july.merge(
    mapping,
    left_on="Normalized_Source",
    right_on="Normalized_Alias",
    how="left",
)


# ==================================================
# CHECK FOR UNMATCHED ASAP COUNTRIES
# ==================================================

unmatched = (
    july[
        july["ISO3"].isna()
    ][
        [
            "Source_Country",
            "hs_code",
            "hs_name",
        ]
    ]
    .drop_duplicates()
)


print()
print(
    f"Unmatched July ASAP country names: "
    f"{len(unmatched)}"
)


if not unmatched.empty:

    print()
    print(
        "UNMATCHED ASAP COUNTRY NAMES"
    )

    print("-" * 70)

    print(
        unmatched.to_string(
            index=False
        )
    )


# ==================================================
# ONE ASAP VALUE PER ISO3
# ==================================================

duplicates = july[
    july["ISO3"].notna()
    & july.duplicated(
        subset=["ISO3"],
        keep=False,
    )
]


if not duplicates.empty:

    print()
    print(
        "WARNING: Duplicate mapped ISO3 "
        "values detected."
    )

    print(
        duplicates[
            [
                "Source_Country",
                "ISO3",
                "hs_code",
            ]
        ].to_string(index=False)
    )


source_data = (
    july[
        july["ISO3"].notna()
    ]
    .drop_duplicates(
        subset=["ISO3"],
        keep="first",
    )
    .copy()
)


source_data = source_data[
    [
        "ISO3",
        "CERF_Country",
        "Source_Country",
        "hs_code",
        "hs_name",
        "date",
        "asap0_id",
    ]
]


source_data = source_data.rename(
    columns={
        "hs_code": "Python_ASAP",
        "hs_name": "ASAP_Status",
        "date": "ASAP_Date",
    }
)


# ==================================================
# READ AUGUST CIRV WORKBOOK
# ==================================================

excel_files = list(
    input_folder.glob("*.xlsx")
)


if not excel_files:

    raise FileNotFoundError(
        "No CIRV workbook found."
    )


workbook_path = excel_files[0]


print()
print(
    f"Using CIRV workbook: "
    f"{workbook_path.name}"
)


workbook = load_workbook(
    workbook_path,
    read_only=True,
    data_only=True,
)


sheet = workbook[
    "CERF UFE 2026-I All Data"
]


workbook_records = []


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

    workbook_asap = sheet.cell(
        row=row_number,
        column=18,
    ).value


    if not country or not iso3:
        continue


    workbook_records.append(
        {
            "Country": str(
                country
            ).strip(),

            "ISO3": str(
                iso3
            ).strip().upper(),

            "Workbook_ASAP":
                workbook_asap,
        }
    )


workbook_data = pd.DataFrame(
    workbook_records
)


workbook_data[
    "Workbook_ASAP"
] = pd.to_numeric(
    workbook_data[
        "Workbook_ASAP"
    ],
    errors="coerce",
)


# ==================================================
# JOIN BY ISO3
# ==================================================

comparison = workbook_data.merge(
    source_data[
        [
            "ISO3",
            "Source_Country",
            "Python_ASAP",
            "ASAP_Status",
            "ASAP_Date",
            "asap0_id",
        ]
    ],
    on="ISO3",
    how="left",
)


# ==================================================
# VALIDATION STATUS
# ==================================================

def classify(row):

    workbook_value = row[
        "Workbook_ASAP"
    ]

    source_value = row[
        "Python_ASAP"
    ]


    workbook_has = pd.notna(
        workbook_value
    )

    source_has = pd.notna(
        source_value
    )


    # Both contain a value.
    if workbook_has and source_has:

        if workbook_value == source_value:

            return "MATCH"

        return "MISMATCH"


    # Neither contains data.
    if (
        not workbook_has
        and not source_has
    ):

        return "MATCH_NO_DATA"


    # Valid source data exists but the workbook
    # was blank.
    #
    # We treat the source as authoritative here
    # and flag the workbook omission.

    if (
        not workbook_has
        and source_has
    ):

        return "WORKBOOK_MISSING_VALUE"


    # Workbook has a value but the historical
    # source does not.
    #
    # This requires investigation.

    return "SOURCE_MISSING_VALUE"


comparison[
    "Validation_Status"
] = comparison.apply(
    classify,
    axis=1,
)


comparison["Difference"] = (
    comparison["Python_ASAP"]
    - comparison["Workbook_ASAP"]
)


# ==================================================
# FORMAT DATE
# ==================================================

comparison["ASAP_Date"] = (
    comparison["ASAP_Date"]
    .dt.strftime("%Y-%m-%d")
)


# ==================================================
# FINAL VALIDATION TABLE
# ==================================================

validation = comparison[
    [
        "Country",
        "ISO3",
        "Workbook_ASAP",
        "Python_ASAP",
        "Validation_Status",
        "Difference",
        "Source_Country",
        "ASAP_Date",
        "ASAP_Status",
        "asap0_id",
    ]
].copy()


# ==================================================
# SAVE OUTPUT
# ==================================================

output_file = (
    project_folder
    / "asap_historical_parity.xlsx"
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
    "ASAP HISTORICAL PARITY TEST"
)

print("=" * 80)


print(
    f"CIRV countries checked: "
    f"{len(validation)}"
)


statuses = [
    "MATCH",
    "MATCH_NO_DATA",
    "MISMATCH",
    "WORKBOOK_MISSING_VALUE",
    "SOURCE_MISSING_VALUE",
]


for status in statuses:

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
# SOURCE ACCURACY
# ==================================================

# These count as successful automation:
#
# MATCH
# MATCH_NO_DATA
# WORKBOOK_MISSING_VALUE
#
# because a valid source value takes precedence over
# an accidental blank in the workbook.

accepted = validation[
    "Validation_Status"
].isin(
    [
        "MATCH",
        "MATCH_NO_DATA",
        "WORKBOOK_MISSING_VALUE",
    ]
).sum()


print()
print(
    f"Automation validated: "
    f"{accepted}/{len(validation)}"
)


# ==================================================
# GENUINE PROBLEMS
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
                "Workbook_ASAP",
                "Python_ASAP",
                "Validation_Status",
                "Source_Country",
                "ASAP_Date",
                "ASAP_Status",
            ]
        ]
        .to_string(index=False)
    )


# ==================================================
# WORKBOOK OMISSIONS
# ==================================================

workbook_omissions = validation[
    validation[
        "Validation_Status"
    ]
    .eq(
        "WORKBOOK_MISSING_VALUE"
    )
]


print()
print(
    "LIKELY WORKBOOK OMISSIONS"
)

print("-" * 80)


if workbook_omissions.empty:

    print(
        "None."
    )

else:

    print(
        workbook_omissions[
            [
                "Country",
                "ISO3",
                "Workbook_ASAP",
                "Python_ASAP",
                "Source_Country",
                "ASAP_Date",
                "ASAP_Status",
            ]
        ]
        .to_string(index=False)
    )


print()
print(
    "Validation file saved to:"
)

print(output_file)