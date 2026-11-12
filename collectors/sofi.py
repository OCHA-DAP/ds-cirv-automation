from pathlib import Path
import json
import re
import zipfile

import pandas as pd
import requests


# ==================================================
# SETTINGS
# ==================================================

FAOSTAT_FS_ZIP_URL = (
    "https://bulks-faostat.fao.org/"
    "production/Food_Security_Data_E_All_Data_"
    "(Normalized).zip"
)

TARGET_ITEM = (
    "Prevalence of moderate or severe food insecurity "
    "in the total population (percent) (3-year average)"
)

TARGET_ELEMENT = "Value"
TARGET_UNIT = "%"

# CIRV should use only the latest common SOFI round.
# Do not backfill from older country observations.
MINIMUM_LATEST_ROUND_AREAS = 150
MINIMUM_MAPPED_CERF_COUNTRIES = 90


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

raw_folder = (
    project_folder
    / "data"
    / "raw"
    / "sofi"
)

raw_folder.mkdir(
    parents=True,
    exist_ok=True,
)

mapping_file = (
    project_folder
    / "config"
    / "countries.csv"
)

zip_file = (
    raw_folder
    / "FAOSTAT_Food_Security_Indicators.zip"
)

raw_csv_file = (
    raw_folder
    / "FAOSTAT_Food_Security_Indicators.csv"
)

current_output = (
    project_folder
    / "sofi_current.csv"
)

evidence_output = (
    raw_folder
    / "SOFI_extraction_evidence.csv"
)

metadata_output = (
    raw_folder
    / "latest_sofi_metadata.json"
)

unmapped_output = (
    raw_folder
    / "SOFI_unmapped_latest_round.csv"
)

missing_cerf_output = (
    raw_folder
    / "SOFI_missing_CERF_countries.csv"
)

diagnostic_output = (
    raw_folder
    / "SOFI_failed_extraction.csv"
)


# ==================================================
# HTTP SESSION
# ==================================================

def create_session():

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            ),

            "Accept":
                "*/*",

            "Accept-Language":
                "en-US,en;q=0.9",
        }
    )

    return session


# ==================================================
# DOWNLOAD FAOSTAT DATASET
# ==================================================

def download_dataset():

    print(
        "Downloading FAOSTAT Food Security Indicators..."
    )

    session = create_session()

    response = session.get(
        FAOSTAT_FS_ZIP_URL,
        timeout=180,
        allow_redirects=True,
    )

    response.raise_for_status()

    print(
        f"HTTP status: "
        f"{response.status_code}"
    )

    print(
        f"Content type: "
        f"{response.headers.get('Content-Type')}"
    )

    print(
        f"Downloaded bytes: "
        f"{len(response.content):,}"
    )

    if not response.content.startswith(
        b"PK"
    ):

        raise RuntimeError(
            "FAOSTAT response is not a ZIP file."
        )

    zip_file.write_bytes(
        response.content
    )

    print()
    print(
        "FAOSTAT Food Security dataset "
        "downloaded successfully."
    )

    print(
        zip_file
    )

    return zip_file


# ==================================================
# EXTRACT NORMALIZED CSV
# ==================================================

def extract_csv(downloaded_zip):

    print()
    print(
        "Inspecting FAOSTAT ZIP..."
    )

    with zipfile.ZipFile(
        downloaded_zip,
        "r",
    ) as archive:

        members = archive.namelist()

        candidates = [
            member
            for member in members
            if (
                member.lower().endswith(
                    ".csv"
                )
                and
                "all_data"
                in member.lower()
                and
                "normalized"
                in member.lower()
            )
        ]

        if not candidates:

            raise RuntimeError(
                "Normalized FAOSTAT All Data CSV "
                "was not found in the ZIP file."
            )

        selected = candidates[0]

        print(
            f"Selected CSV: "
            f"{selected}"
        )

        raw_csv_file.write_bytes(
            archive.read(
                selected
            )
        )

    return raw_csv_file


# ==================================================
# READ DATA
# ==================================================

def read_data(csv_path):

    data = pd.read_csv(
        csv_path,
        encoding="utf-8-sig",
        low_memory=False,
        dtype={
            "Area Code": str,
            "Area Code (M49)": str,
            "Item Code": str,
            "Element Code": str,
            "Year Code": str,
            "Year": str,
            "Value": str,
            "Flag": str,
            "Note": str,
        },
    )

    print(
        f"Rows loaded: "
        f"{len(data):,}"
    )

    required_columns = [
        "Area Code",
        "Area Code (M49)",
        "Area",
        "Item Code",
        "Item",
        "Element Code",
        "Element",
        "Year Code",
        "Year",
        "Unit",
        "Value",
        "Flag",
        "Note",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in data.columns
    ]

    if missing_columns:

        raise RuntimeError(
            "FAOSTAT dataset is missing "
            "required columns:\n"
            f"{missing_columns}"
        )

    return data


# ==================================================
# FILTER EXACT SOFI INDICATOR
# ==================================================

def filter_sofi_indicator(data):

    filtered = data[
        (
            data["Item"].eq(
                TARGET_ITEM
            )
        )
        &
        (
            data["Element"].eq(
                TARGET_ELEMENT
            )
        )
        &
        (
            data["Unit"].eq(
                TARGET_UNIT
            )
        )
    ].copy()

    if filtered.empty:

        raise RuntimeError(
            "The target SOFI 3-year-average "
            "indicator was not found."
        )

    print()
    print(
        "Target indicator:"
    )

    print(
        TARGET_ITEM
    )

    print(
        f"Indicator rows: "
        f"{len(filtered):,}"
    )

    return filtered


# ==================================================
# PARSE SOFI VALUE
# ==================================================

def parse_value(value):

    if pd.isna(value):

        return pd.NA

    text = str(value).strip()

    if not text:

        return pd.NA

    # FAOSTAT sometimes publishes bounded values
    # such as "<2.5" or ">90".
    #
    # CIRV stores the published numeric component.

    text = (
        text
        .replace("<", "")
        .replace(">", "")
        .replace(",", "")
    )

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text,
    )

    if not match:

        return pd.NA

    return float(
        match.group(0)
    )


# ==================================================
# PARSE 3-YEAR PERIOD
# ==================================================

def parse_period_start(year_value):

    if pd.isna(year_value):

        return pd.NA

    years = re.findall(
        r"\d{4}",
        str(year_value),
    )

    if not years:

        return pd.NA

    return int(
        years[0]
    )


def parse_period_end(year_value):

    if pd.isna(year_value):

        return pd.NA

    years = re.findall(
        r"\d{4}",
        str(year_value),
    )

    if not years:

        return pd.NA

    return int(
        years[-1]
    )


def validate_three_year_period(row):

    start = row[
        "Period_Start"
    ]

    end = row[
        "Period_End"
    ]

    if pd.isna(start) or pd.isna(end):

        return False

    return (
        int(end)
        - int(start)
        == 2
    )


# ==================================================
# CLEAN INDICATOR OBSERVATIONS
# ==================================================

def clean_indicator_data(filtered):

    filtered = filtered.copy()

    filtered["SOFI_Score"] = (
        filtered["Value"]
        .apply(parse_value)
    )

    filtered["Period_Start"] = (
        filtered["Year"]
        .apply(parse_period_start)
    )

    filtered["Period_End"] = (
        filtered["Year"]
        .apply(parse_period_end)
    )

    filtered = filtered[
        filtered[
            "SOFI_Score"
        ].notna()
        &
        filtered[
            "Period_Start"
        ].notna()
        &
        filtered[
            "Period_End"
        ].notna()
    ].copy()

    filtered["Period_Start"] = (
        filtered[
            "Period_Start"
        ].astype(int)
    )

    filtered["Period_End"] = (
        filtered[
            "Period_End"
        ].astype(int)
    )

    filtered = filtered[
        filtered.apply(
            validate_three_year_period,
            axis=1,
        )
    ].copy()

    invalid_values = filtered[
        ~filtered[
            "SOFI_Score"
        ].between(
            0,
            100,
        )
    ]

    if not invalid_values.empty:

        invalid_values.to_csv(
            diagnostic_output,
            index=False,
            encoding="utf-8-sig",
        )

        raise RuntimeError(
            "SOFI values outside the "
            "0-100 range were detected."
        )

    return filtered


# ==================================================
# DETERMINE LATEST COMMON SOFI ROUND
# ==================================================

def determine_latest_round(filtered):
    """
    Determine the latest global 3-year SOFI round.

    This uses the maximum reporting-period end year
    available for the exact target indicator.

    It then selects the most common period among
    observations ending in that year.

    Current expected result:
    2023-2025
    """

    if filtered.empty:

        raise RuntimeError(
            "No cleaned SOFI observations "
            "are available."
        )

    latest_end_year = int(
        filtered[
            "Period_End"
        ].max()
    )

    latest_end_rows = filtered[
        filtered[
            "Period_End"
        ].eq(
            latest_end_year
        )
    ].copy()

    period_counts = (
        latest_end_rows[
            "Year"
        ]
        .value_counts()
    )

    if period_counts.empty:

        raise RuntimeError(
            "Unable to determine the latest "
            "SOFI reporting round."
        )

    latest_round = str(
        period_counts.index[0]
    )

    latest_round_count = int(
        period_counts.iloc[0]
    )

    print()
    print(
        "Latest global SOFI round:"
    )

    print(
        latest_round
    )

    print(
        f"FAOSTAT areas reported in "
        f"latest round: "
        f"{latest_round_count}"
    )

    if (
        latest_round_count
        < MINIMUM_LATEST_ROUND_AREAS
    ):

        raise RuntimeError(
            "The newest SOFI period has "
            "implausibly low global coverage.\n"
            f"Period: {latest_round}\n"
            f"Areas: {latest_round_count}\n"
            f"Minimum required: "
            f"{MINIMUM_LATEST_ROUND_AREAS}"
        )

    return (
        latest_round,
        latest_end_year,
        period_counts,
    )


# ==================================================
# FILTER TO LATEST ROUND ONLY
# ==================================================

def select_latest_round_only(
    filtered,
    latest_round,
):
    """
    Use only countries reported in the latest
    common SOFI reporting round.

    Do not search backwards for older country data.
    """

    latest = filtered[
        filtered[
            "Year"
        ].eq(
            latest_round
        )
    ].copy()

    if latest.empty:

        raise RuntimeError(
            "No SOFI observations were found "
            "for the latest reporting round."
        )

    # A country/area should normally have one Value
    # record for the selected item, element and year.
    #
    # Keep one record per FAOSTAT area if duplicates
    # exist.

    duplicates = latest[
        latest.duplicated(
            subset=[
                "Area Code",
                "Area",
                "Year",
            ],
            keep=False,
        )
    ]

    if not duplicates.empty:

        print()
        print(
            "Duplicate latest-round FAOSTAT "
            "area records detected:"
        )

        print(
            duplicates[
                [
                    "Area",
                    "Area Code",
                    "Year",
                    "Value",
                    "Flag",
                ]
            ]
            .sort_values(
                [
                    "Area",
                    "Year",
                ]
            )
            .to_string(
                index=False
            )
        )

    latest = (
        latest
        .sort_values(
            [
                "Area",
                "Area Code",
            ]
        )
        .drop_duplicates(
            subset=[
                "Area Code",
                "Area",
            ],
            keep="first",
        )
        .reset_index(
            drop=True
        )
    )

    print()
    print(
        "Latest-round observations retained:"
    )

    print(
        len(latest)
    )

    return latest


# ==================================================
# COUNTRY NAME NORMALIZATION
# ==================================================

def normalize_name(value):

    if pd.isna(value):

        return ""

    text = str(value).strip()

    text = (
        text
        .replace("’", "'")
        .replace("‘", "'")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
    )

    import unicodedata

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(
            character
        )
    )

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return " ".join(
        text.split()
    )


# ==================================================
# LOAD CERF COUNTRY MAPPING
# ==================================================

def load_country_mapping():

    if not mapping_file.exists():

        raise FileNotFoundError(
            "CERF country mapping not found:\n"
            f"{mapping_file}"
        )

    mapping = pd.read_csv(
        mapping_file
    )

    required_columns = [
        "ISO3",
        "CERF_Country",
        "Source_Alias",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in mapping.columns
    ]

    if missing_columns:

        raise RuntimeError(
            "CERF country mapping is missing "
            "required columns:\n"
            f"{missing_columns}"
        )

    return mapping


# ==================================================
# CREATE COUNTRY LOOKUP
# ==================================================

def create_mapping_lookup(mapping):

    lookup = {}

    for _, row in mapping.iterrows():

        alias = normalize_name(
            row["Source_Alias"]
        )

        if not alias:
            continue

        lookup[alias] = {
            "ISO3":
                row["ISO3"],

            "CERF_Country":
                row["CERF_Country"],
        }

    canonical = (
        mapping[
            [
                "ISO3",
                "CERF_Country",
            ]
        ]
        .drop_duplicates(
            subset=["ISO3"]
        )
        .set_index("ISO3")[
            "CERF_Country"
        ]
        .to_dict()
    )

    faostat_aliases = {

        "bolivia plurinational state of":
            "BOL",

        "cabo verde":
            "CPV",

        "cote d ivoire":
            "CIV",

        "democratic republic of the congo":
            "COD",

        "iran islamic republic of":
            "IRN",

        "lao people s democratic republic":
            "LAO",

        "republic of korea":
            "KOR",

        "democratic people s republic of korea":
            "PRK",

        "republic of moldova":
            "MDA",

        "state of palestine":
            "PSE",

        "palestine":
            "PSE",

        "syrian arab republic":
            "SYR",

        "united republic of tanzania":
            "TZA",

        "venezuela bolivarian republic of":
            "VEN",

        "viet nam":
            "VNM",

        "turkiye":
            "TUR",

        "timor leste":
            "TLS",
    }

    for alias, iso3 in faostat_aliases.items():

        if iso3 not in canonical:
            continue

        lookup[
            normalize_name(alias)
        ] = {
            "ISO3":
                iso3,

            "CERF_Country":
                canonical[iso3],
        }

    return lookup


# ==================================================
# MAP LATEST ROUND TO CERF COUNTRIES
# ==================================================

def map_to_cerf(
    latest_round_data,
    mapping,
):

    lookup = create_mapping_lookup(
        mapping
    )

    observations = []
    unmapped = []

    for _, row in latest_round_data.iterrows():

        normalized_area = normalize_name(
            row["Area"]
        )

        country = lookup.get(
            normalized_area
        )

        if country is None:

            unmapped.append(
                {
                    "FAOSTAT_Area":
                        row["Area"],

                    "Area_Code":
                        row["Area Code"],

                    "M49":
                        row[
                            "Area Code (M49)"
                        ],

                    "SOFI_Period":
                        row["Year"],

                    "SOFI_Score":
                        row["SOFI_Score"],
                }
            )

            continue

        observations.append(
            {
                "ISO3":
                    country["ISO3"],

                "CERF_Country":
                    country[
                        "CERF_Country"
                    ],

                "FAOSTAT_Area":
                    row["Area"],

                "FAOSTAT_Area_Code":
                    row["Area Code"],

                "M49":
                    row[
                        "Area Code (M49)"
                    ],

                "SOFI_Score":
                    row[
                        "SOFI_Score"
                    ],

                "SOFI_Period":
                    row["Year"],

                "Period_Start":
                    row[
                        "Period_Start"
                    ],

                "Period_End":
                    row[
                        "Period_End"
                    ],

                "Flag":
                    row["Flag"],

                "Note":
                    row["Note"],

                "Item":
                    row["Item"],

                "Element":
                    row["Element"],

                "Unit":
                    row["Unit"],

                "Selection_Method":
                    (
                        "Reported in latest "
                        "global SOFI round"
                    ),
            }
        )

    results = pd.DataFrame(
        observations
    )

    unmapped_data = pd.DataFrame(
        unmapped
    )

    if results.empty:

        raise RuntimeError(
            "No latest-round SOFI observations "
            "mapped to CERF countries."
        )

    duplicates = results[
        results.duplicated(
            subset=["ISO3"],
            keep=False,
        )
    ]

    if not duplicates.empty:

        print()
        print(
            "Duplicate mapped ISO3 records:"
        )

        print(
            duplicates[
                [
                    "CERF_Country",
                    "ISO3",
                    "FAOSTAT_Area",
                    "SOFI_Score",
                    "SOFI_Period",
                ]
            ]
            .sort_values(
                [
                    "ISO3",
                    "FAOSTAT_Area",
                ]
            )
            .to_string(
                index=False
            )
        )

    results = (
        results
        .sort_values(
            [
                "ISO3",
                "FAOSTAT_Area",
            ]
        )
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .sort_values(
            "CERF_Country"
        )
        .reset_index(
            drop=True
        )
    )

    if not unmapped_data.empty:

        unmapped_data.to_csv(
            unmapped_output,
            index=False,
            encoding="utf-8-sig",
        )

    print()
    print(
        f"CERF countries mapped in "
        f"latest round: "
        f"{len(results)}"
    )

    print(
        f"Latest-round FAOSTAT areas "
        f"not mapped to CERF: "
        f"{len(unmapped_data)}"
    )

    return (
        results,
        unmapped_data,
    )


# ==================================================
# IDENTIFY CERF COUNTRIES WITHOUT LATEST ROUND DATA
# ==================================================

def identify_missing_cerf_countries(
    results,
    mapping,
    latest_round,
):

    cerf_countries = (
        mapping[
            [
                "ISO3",
                "CERF_Country",
            ]
        ]
        .drop_duplicates(
            subset=["ISO3"]
        )
        .copy()
    )

    mapped_iso3 = set(
        results["ISO3"]
    )

    missing = cerf_countries[
        ~cerf_countries[
            "ISO3"
        ].isin(
            mapped_iso3
        )
    ].copy()

    missing["SOFI_Score"] = pd.NA

    missing["SOFI_Period"] = (
        latest_round
    )

    missing["SOFI_Status"] = (
        "Not reported in latest SOFI round"
    )

    missing = (
        missing
        .sort_values(
            "CERF_Country"
        )
        .reset_index(
            drop=True
        )
    )

    missing.to_csv(
        missing_cerf_output,
        index=False,
        encoding="utf-8-sig",
    )

    print()
    print(
        "CERF countries without an observation "
        f"in {latest_round}: "
        f"{len(missing)}"
    )

    return missing


# ==================================================
# VALIDATE RESULTS
# ==================================================

def validate_results(
    results,
    latest_round,
):

    problems = []

    if (
        len(results)
        < MINIMUM_MAPPED_CERF_COUNTRIES
    ):

        problems.append(
            (
                f"Only {len(results)} CERF "
                "countries mapped in the "
                "latest SOFI round."
            )
        )

    if (
        results["ISO3"]
        .duplicated()
        .any()
    ):

        problems.append(
            "Duplicate ISO3 values detected."
        )

    if not results[
        "SOFI_Score"
    ].between(
        0,
        100,
    ).all():

        problems.append(
            "A SOFI score falls outside 0-100."
        )

    if not results[
        "SOFI_Period"
    ].eq(
        latest_round
    ).all():

        invalid_periods = sorted(
            results.loc[
                ~results[
                    "SOFI_Period"
                ].eq(
                    latest_round
                ),
                "SOFI_Period",
            ]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        problems.append(
            (
                "Historical SOFI periods were "
                "included unexpectedly: "
                f"{invalid_periods}"
            )
        )

    if problems:

        results.to_csv(
            diagnostic_output,
            index=False,
            encoding="utf-8-sig",
        )

        print()
        print(
            "SOFI VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "SOFI results failed validation. "
            "sofi_current.csv was not overwritten."
        )

    print()
    print(
        "SOFI VALIDATION PASSED"
    )

    print(
        f"Reporting round: "
        f"{latest_round}"
    )

    print(
        f"CERF countries reported: "
        f"{len(results)}"
    )


# ==================================================
# SAVE OUTPUTS
# ==================================================

def save_outputs(
    results,
    missing_cerf,
    unmapped_data,
    latest_round,
    latest_end_year,
    period_counts,
):

    output_columns = [
        "ISO3",
        "CERF_Country",
        "SOFI_Score",
        "SOFI_Period",
        "FAOSTAT_Area",
        "FAOSTAT_Area_Code",
        "M49",
        "Flag",
        "Note",
        "Selection_Method",
    ]

    results[
        output_columns
    ].to_csv(
        current_output,
        index=False,
        encoding="utf-8-sig",
    )

    results.to_csv(
        evidence_output,
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "source":
            (
                "FAOSTAT Suite of "
                "Food Security Indicators"
            ),

        "source_url":
            FAOSTAT_FS_ZIP_URL,

        "indicator":
            TARGET_ITEM,

        "element":
            TARGET_ELEMENT,

        "unit":
            TARGET_UNIT,

        "latest_global_round":
            str(
                latest_round
            ),

        "latest_period_end_year":
            int(
                latest_end_year
            ),

        "selection_method":
            (
                "Use only countries reported in "
                "the latest global 3-year SOFI "
                "round. No historical backfilling."
            ),

        "absence_method":
            (
                "Countries without an observation "
                "in the latest round remain missing "
                "and are not assigned an older value."
            ),

        "score_method":
            (
                "Raw FAOSTAT prevalence percentage "
                "retained on the 0-100 scale."
            ),

        "latest_round_cerf_countries":
            int(
                len(results)
            ),

        "cerf_countries_missing_latest_round":
            int(
                len(missing_cerf)
            ),

        "unmapped_faostat_areas":
            int(
                len(unmapped_data)
            ),

        "latest_end_year_period_counts":
            {
                str(period):
                    int(count)

                for period, count in (
                    period_counts.items()
                )
            },
    }

    metadata_output.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ==================================================
# UPDATE SOFI
# ==================================================

def update_sofi():

    downloaded_zip = (
        download_dataset()
    )

    csv_path = extract_csv(
        downloaded_zip
    )

    data = read_data(
        csv_path
    )

    indicator_data = (
        filter_sofi_indicator(
            data
        )
    )

    cleaned_data = (
        clean_indicator_data(
            indicator_data
        )
    )

    (
        latest_round,
        latest_end_year,
        period_counts,
    ) = determine_latest_round(
        cleaned_data
    )

    latest_round_data = (
        select_latest_round_only(
            cleaned_data,
            latest_round,
        )
    )

    mapping = load_country_mapping()

    (
        results,
        unmapped_data,
    ) = map_to_cerf(
        latest_round_data,
        mapping,
    )

    missing_cerf = (
        identify_missing_cerf_countries(
            results,
            mapping,
            latest_round,
        )
    )

    validate_results(
        results,
        latest_round,
    )

    save_outputs(
        results,
        missing_cerf,
        unmapped_data,
        latest_round,
        latest_end_year,
        period_counts,
    )

    return (
        results,
        missing_cerf,
        unmapped_data,
        latest_round,
    )


# ==================================================
# MAIN
# ==================================================

if __name__ == "__main__":

    (
        results,
        missing_cerf,
        unmapped_data,
        latest_round,
    ) = update_sofi()

    print()
    print("=" * 70)

    print(
        "SOFI UPDATE COMPLETE"
    )

    print("=" * 70)

    print(
        f"Latest SOFI round: "
        f"{latest_round}"
    )

    print(
        f"CERF countries reported: "
        f"{len(results)}"
    )

    print(
        f"CERF countries missing: "
        f"{len(missing_cerf)}"
    )

    print()
    print(
        "Reported latest-round countries:"
    )

    print()

    print(
        results[
            [
                "CERF_Country",
                "ISO3",
                "SOFI_Score",
                "SOFI_Period",
            ]
        ]
        .to_string(
            index=False
        )
    )

    print()
    print(
        "Key CIRV validation countries:"
    )

    validation_iso3 = [
        "AFG",
        "AGO",
        "BGD",
        "BDI",
        "CMR",
        "CAF",
        "TCD",
        "COD",
        "DJI",
        "GIN",
        "HTI",
        "KEN",
        "MWI",
        "NGA",
        "SOM",
        "SSD",
        "SDN",
        "YEM",
        "ZWE",
    ]

    displayed = results.loc[
        results[
            "ISO3"
        ].isin(
            validation_iso3
        ),
        [
            "CERF_Country",
            "ISO3",
            "SOFI_Score",
            "SOFI_Period",
        ],
    ].copy()

    missing_validation = (
        missing_cerf.loc[
            missing_cerf[
                "ISO3"
            ].isin(
                validation_iso3
            ),
            [
                "CERF_Country",
                "ISO3",
                "SOFI_Score",
                "SOFI_Period",
            ],
        ]
        .copy()
    )

    validation_display = pd.concat(
        [
            displayed,
            missing_validation,
        ],
        ignore_index=True,
    )

    validation_display = (
        validation_display
        .sort_values(
            "CERF_Country"
        )
        .reset_index(
            drop=True
        )
    )

    print()

    print(
        validation_display.to_string(
            index=False
        )
    )

    print()
    print(
        "Expected workbook-style missing cases:"
    )

    expected_missing_iso3 = [
        "CAF",
        "DJI",
        "GIN",
        "SOM",
        "SDN",
    ]

    print(
        missing_cerf.loc[
            missing_cerf[
                "ISO3"
            ].isin(
                expected_missing_iso3
            ),
            [
                "CERF_Country",
                "ISO3",
                "SOFI_Status",
                "SOFI_Period",
            ],
        ]
        .sort_values(
            "CERF_Country"
        )
        .to_string(
            index=False
        )
    )

    print()
    print(
        f"Current output saved to:\n"
        f"{current_output}"
    )

    print()
    print(
        f"Evidence saved to:\n"
        f"{evidence_output}"
    )

    print()
    print(
        f"Missing CERF countries saved to:\n"
        f"{missing_cerf_output}"
    )

    print()
    print(
        f"Unmapped FAOSTAT areas saved to:\n"
        f"{unmapped_output}"
    )

    print()
    print(
        f"Metadata saved to:\n"
        f"{metadata_output}"
    )