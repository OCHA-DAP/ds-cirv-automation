import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from openpyxl import load_workbook


# ==================================================
# HISTORICAL VALIDATION SETTINGS
# ==================================================

# The uploaded CIRV workbook is dated 10 August 2026.
VALIDATION_DATE = pd.Timestamp("2026-08-10")

# Strict nominal 12-month lookback.
LOOKBACK_START = VALIDATION_DATE - pd.DateOffset(months=12)


# ==================================================
# HDX SETTINGS
# ==================================================

load_dotenv()

HDX_APP_IDENTIFIER = os.getenv(
    "HDX_APP_IDENTIFIER"
)

HDX_IPC_URL = (
    "https://hapi.humdata.org/api/v2/"
    "food-security-nutrition-poverty/"
    "food-security"
)

if not HDX_APP_IDENTIFIER:
    raise RuntimeError(
        "HDX_APP_IDENTIFIER was not found in .env"
    )


# ==================================================
# LOCATE THE AUGUST CIRV WORKBOOK
# ==================================================

project_folder = Path(__file__).parent.parent
input_folder = project_folder / "input"

excel_files = list(
    input_folder.glob("*.xlsx")
)

if not excel_files:
    raise FileNotFoundError(
        "No CIRV workbook was found in the input folder."
    )

workbook_path = excel_files[0]

print(f"Using CIRV workbook: {workbook_path.name}")
print(f"Validation date: {VALIDATION_DATE.date()}")
print(
    f"Strict lookback: "
    f"{LOOKBACK_START.date()} to "
    f"{VALIDATION_DATE.date()}"
)


# ==================================================
# READ THE AUGUST WORKBOOK IPC VALUES
# ==================================================

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
    sheet.max_row + 1
):

    country = sheet.cell(
        row=row_number,
        column=1,
    ).value

    iso3 = sheet.cell(
        row=row_number,
        column=2,
    ).value

    workbook_ipc = sheet.cell(
        row=row_number,
        column=11,
    ).value

    if not country or not iso3:
        continue

    workbook_records.append(
        {
            "Country": country,
            "ISO3": str(iso3).strip().upper(),
            "Workbook_HDX_IPC": workbook_ipc,
        }
    )

workbook_data = pd.DataFrame(
    workbook_records
)

workbook_data["Workbook_HDX_IPC"] = pd.to_numeric(
    workbook_data["Workbook_HDX_IPC"],
    errors="coerce",
)


# ==================================================
# DOWNLOAD HISTORICAL HDX IPC RECORDS
# ==================================================

def download_historical_hdx_ipc():
    """
    Retrieve HDX IPC records for the historical
    August 2026 validation window.

    The API can return periods that overlap the
    requested dates. A strict nominal date filter
    is therefore applied locally afterward.
    """

    all_rows = []

    limit = 10000
    offset = 0

    while True:

        params = {
            "app_identifier": HDX_APP_IDENTIFIER,

            # CERF rule:
            # current-period analyses only
            "ipc_type": "current",

            # Historical validation period
            "start_date": (
                LOOKBACK_START
                .date()
                .isoformat()
            ),

            "end_date": (
                VALIDATION_DATE
                .date()
                .isoformat()
            ),

            "output_format": "json",
            "limit": limit,
            "offset": offset,
        }

        response = requests.get(
            HDX_IPC_URL,
            params=params,
            timeout=120,
        )

        response.raise_for_status()

        payload = response.json()

        rows = payload.get(
            "data",
            []
        )

        all_rows.extend(rows)

        print(
            f"Retrieved {len(all_rows)} "
            f"historical IPC rows..."
        )

        if len(rows) < limit:
            break

        offset += limit

    return pd.DataFrame(all_rows)


api = download_historical_hdx_ipc()

if api.empty:
    raise RuntimeError(
        "HDX returned no IPC records "
        "for the validation period."
    )


# ==================================================
# APPLY CERF IPC RULES
# ==================================================

# Dates
api["Reference_Start"] = pd.to_datetime(
    api["reference_period_start"],
    errors="coerce",
).dt.tz_localize(None)

api["Reference_End"] = pd.to_datetime(
    api["reference_period_end"],
    errors="coerce",
).dt.tz_localize(None)


# --------------------------------------------------
# Strict nominal lookback
#
# The reference period must begin on or after
# 10 August 2025 and on or before 10 August 2026.
#
# This prevents an older analysis from entering
# merely because its period overlaps the cutoff.
# --------------------------------------------------

api = api[
    (
        api["Reference_Start"]
        >= LOOKBACK_START
    )
    &
    (
        api["Reference_Start"]
        <= VALIDATION_DATE
    )
].copy()


# Current periods only.
# This is also requested through the API, but we
# enforce it locally as a validation safeguard.

api = api[
    api["ipc_type"]
    .astype(str)
    .str.lower()
    .eq("current")
].copy()


# Valid phases 1–5 only.
# This excludes "all" and "3+" aggregate categories.

api["IPC_Phase"] = pd.to_numeric(
    api["ipc_phase"],
    errors="coerce",
)

api = api[
    api["IPC_Phase"].isin(
        [1, 2, 3, 4, 5]
    )
].copy()


# Population must be greater than zero.

api["Population_In_Phase"] = pd.to_numeric(
    api["population_in_phase"],
    errors="coerce",
)

api = api[
    api["Population_In_Phase"] > 0
].copy()


# Clean ISO3 codes.

api["ISO3"] = (
    api["location_code"]
    .astype(str)
    .str.strip()
    .str.upper()
)

api = api[
    api["ISO3"].str.match(
        r"^[A-Z]{3}$"
    )
].copy()


# ==================================================
# SELECT THE HIGHEST IPC PHASE PER COUNTRY
# ==================================================

# Highest phase first.
#
# Where several records contain the same highest
# phase, retain the record with the newest reference
# start/end date and highest population. This gives
# us one transparent evidence row for each country.

api = api.sort_values(
    [
        "ISO3",
        "IPC_Phase",
        "Reference_Start",
        "Reference_End",
        "Population_In_Phase",
    ],
    ascending=[
        True,
        False,
        False,
        False,
        False,
    ],
)

selected = (
    api
    .drop_duplicates(
        subset=["ISO3"],
        keep="first",
    )
    .copy()
)


selected = selected[
    [
        "ISO3",
        "location_name",
        "IPC_Phase",
        "Population_In_Phase",
        "Reference_Start",
        "Reference_End",
        "ipc_type",
        "resource_hdx_id",
    ]
].rename(
    columns={
        "location_name": "HDX_Country",
        "IPC_Phase": "Python_HDX_IPC",
        "ipc_type": "IPC_Type",
        "resource_hdx_id": "HDX_Resource_ID",
    }
)


# ==================================================
# COMPARE PYTHON RESULT TO AUGUST WORKBOOK
# ==================================================

comparison = workbook_data.merge(
    selected,
    on="ISO3",
    how="left",
)


def classify_result(row):
    """
    Determine whether Python reproduced the
    August workbook input.
    """

    workbook_value = row[
        "Workbook_HDX_IPC"
    ]

    python_value = row[
        "Python_HDX_IPC"
    ]

    workbook_has_value = (
        pd.notna(workbook_value)
        and workbook_value > 0
    )

    python_has_value = (
        pd.notna(python_value)
        and python_value > 0
    )

    if (
        workbook_has_value
        and python_has_value
    ):

        if workbook_value == python_value:
            return "MATCH"

        return "MISMATCH"

    if (
        not workbook_has_value
        and not python_has_value
    ):
        return "MATCH_NO_DATA"

    if (
        not workbook_has_value
        and python_has_value
    ):
        return "PYTHON_ONLY"

    return "WORKBOOK_ONLY"


comparison["Validation_Status"] = (
    comparison.apply(
        classify_result,
        axis=1,
    )
)


comparison["Difference"] = (
    comparison["Python_HDX_IPC"]
    - comparison["Workbook_HDX_IPC"]
)


# Make dates readable.

comparison["Reference_Start"] = (
    comparison["Reference_Start"]
    .dt.strftime("%Y-%m-%d")
)

comparison["Reference_End"] = (
    comparison["Reference_End"]
    .dt.strftime("%Y-%m-%d")
)


# ==================================================
# CREATE VALIDATION TABLE
# ==================================================

validation = comparison[
    [
        "Country",
        "ISO3",
        "Workbook_HDX_IPC",
        "Python_HDX_IPC",
        "Validation_Status",
        "Difference",
        "Population_In_Phase",
        "Reference_Start",
        "Reference_End",
        "IPC_Type",
        "HDX_Resource_ID",
    ]
].copy()


status_order = {
    "MISMATCH": 1,
    "PYTHON_ONLY": 2,
    "WORKBOOK_ONLY": 3,
    "MATCH": 4,
    "MATCH_NO_DATA": 5,
}

validation["Status_Order"] = (
    validation["Validation_Status"]
    .map(status_order)
)

validation = validation.sort_values(
    [
        "Status_Order",
        "Country",
    ]
)

validation = validation.drop(
    columns=["Status_Order"]
)


# ==================================================
# SAVE RESULTS
# ==================================================

csv_output = (
    project_folder
    / "hdx_ipc_historical_parity.csv"
)

excel_output = (
    project_folder
    / "hdx_ipc_historical_parity.xlsx"
)

validation.to_csv(
    csv_output,
    index=False,
)

validation.to_excel(
    excel_output,
    index=False,
)


# ==================================================
# SUMMARY
# ==================================================

print()
print("=" * 80)
print("HDX IPC HISTORICAL PARITY TEST")
print("=" * 80)

print(
    f"Workbook countries checked: "
    f"{len(validation)}"
)

for status in [
    "MATCH",
    "MATCH_NO_DATA",
    "MISMATCH",
    "PYTHON_ONLY",
    "WORKBOOK_ONLY",
]:

    count = (
        validation["Validation_Status"]
        == status
    ).sum()

    print(f"{status}: {count}")


# Exact overall parity, including correctly matching
# countries where neither source has data.

parity_count = validation[
    "Validation_Status"
].isin(
    [
        "MATCH",
        "MATCH_NO_DATA",
    ]
).sum()

print()
print(
    f"Exact parity: "
    f"{parity_count}/{len(validation)}"
)


# ==================================================
# PRINT NON-MATCHING COUNTRIES
# ==================================================

differences = validation[
    ~validation["Validation_Status"].isin(
        [
            "MATCH",
            "MATCH_NO_DATA",
        ]
    )
]

print()
print("COUNTRIES NOT REPRODUCED EXACTLY")
print("-" * 80)

if differences.empty:

    print(
        "None. Python reproduced the August "
        "workbook HDX IPC values exactly."
    )

else:

    print(
        differences[
            [
                "Country",
                "ISO3",
                "Workbook_HDX_IPC",
                "Python_HDX_IPC",
                "Validation_Status",
                "Population_In_Phase",
                "Reference_Start",
                "Reference_End",
            ]
        ]
        .to_string(index=False)
    )


print()
print("Validation files saved to:")
print(csv_output)
print(excel_output)