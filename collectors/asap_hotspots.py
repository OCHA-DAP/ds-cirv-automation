from pathlib import Path
from urllib.parse import urljoin
import json
import zipfile
import unicodedata

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ==================================================
# SETTINGS
# ==================================================

ASAP_DOWNLOAD_PAGE = (
    "https://agricultural-production-hotspots.ec.europa.eu/"
    "download.php"
)


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

raw_folder = (
    project_folder
    / "data"
    / "raw"
    / "asap_hotspots"
)

raw_folder.mkdir(
    parents=True,
    exist_ok=True,
)

zip_output = (
    raw_folder
    / "hotspots_ts.zip"
)

current_output = (
    project_folder
    / "asap_hotspots_current.csv"
)

evidence_output = (
    raw_folder
    / "ASAP_current_evidence.csv"
)

unmatched_output = (
    raw_folder
    / "ASAP_unmatched_current.csv"
)

metadata_output = (
    raw_folder
    / "latest_asap_metadata.json"
)


# ==================================================
# NORMALIZE COUNTRY NAMES
# ==================================================

def normalize_country_name(value):

    if pd.isna(value):
        return None

    text = str(value).strip()

    text = text.replace(
        "’",
        "'",
    )

    text = text.replace(
        "‘",
        "'",
    )

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
            "Accept-Language":
                "en-US,en;q=0.9",
        }
    )

    return session


# ==================================================
# DYNAMIC DISCOVERY
# ==================================================

def discover_hotspots_download():

    print(
        "Checking ASAP website for latest "
        "hotspot dataset..."
    )

    session = create_session()

    response = session.get(
        ASAP_DOWNLOAD_PAGE,
        timeout=60,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    for link in soup.find_all(
        "a",
        href=True,
    ):

        href = link["href"]

        if (
            "hotspots_ts.zip"
            in href.lower()
        ):

            url = urljoin(
                ASAP_DOWNLOAD_PAGE,
                href,
            )

            print(
                "ASAP hotspot dataset discovered:"
            )

            print(
                url
            )

            return url

    raise RuntimeError(
        "Could not find hotspots_ts.zip."
    )


# ==================================================
# DOWNLOAD
# ==================================================

def download_hotspots():

    url = discover_hotspots_download()

    print()
    print(
        "Downloading current ASAP dataset..."
    )

    session = create_session()

    response = session.get(
        url,
        timeout=120,
    )

    response.raise_for_status()

    if not response.content.startswith(
        b"PK"
    ):

        raise RuntimeError(
            "ASAP download did not return "
            "a valid ZIP file."
        )

    zip_output.write_bytes(
        response.content
    )

    print(
        "Download successful."
    )

    return (
        zip_output,
        url,
    )


# ==================================================
# READ DATA
# ==================================================

def read_hotspots(zip_path):

    with zipfile.ZipFile(
        zip_path,
        "r",
    ) as zip_file:

        members = zip_file.namelist()

        if (
            "hotspots_ts.csv"
            not in members
        ):

            raise RuntimeError(
                "hotspots_ts.csv was not found "
                "inside the ASAP ZIP."
            )

        with zip_file.open(
            "hotspots_ts.csv"
        ) as csv_file:

            data = pd.read_csv(
                csv_file,
                sep=";",
                quotechar='"',
                encoding="utf-8",
            )

    required_columns = [
        "date",
        "hs_code",
        "hs_name",
        "asap0_id",
        "asap0_name",
    ]

    missing_columns = [
        column
        for column
        in required_columns
        if column not in data.columns
    ]

    if missing_columns:

        raise RuntimeError(
            "ASAP dataset is missing "
            "required columns:\n"
            f"{missing_columns}"
        )

    data["date"] = pd.to_datetime(
        data["date"],
        errors="coerce",
    )

    data["hs_code"] = pd.to_numeric(
        data["hs_code"],
        errors="coerce",
    )

    data["Source_Country"] = (
        data["asap0_name"]
        .astype(str)
        .str.strip()
    )

    data["Normalized_Source"] = (
        data["Source_Country"]
        .apply(
            normalize_country_name
        )
    )

    return data


# ==================================================
# LOAD CENTRAL CERF COUNTRY MAPPING
# ==================================================

def load_country_mapping():

    mapping_file = (
        project_folder
        / "config"
        / "countries.csv"
    )

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
        for column
        in required_columns
        if column not in mapping.columns
    ]

    if missing_columns:

        raise RuntimeError(
            "CERF country mapping is missing "
            "required columns:\n"
            f"{missing_columns}"
        )

    mapping["Normalized_Alias"] = (
        mapping["Source_Alias"]
        .apply(
            normalize_country_name
        )
    )

    return (
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
# STANDARDIZE COUNTRY NAMES
# ==================================================

def standardize_countries(
    asap_data,
    mapping,
):

    return asap_data.merge(
        mapping,
        left_on="Normalized_Source",
        right_on="Normalized_Alias",
        how="left",
    )


# ==================================================
# SELECT CURRENT ASAP ASSESSMENT CYCLE
# ==================================================

def calculate_current_asap(data):
    """
    CIRV ASAP rule:

    1. Determine newest ASAP assessment date.

    2. Use only that assessment cycle.

    3. Exclude countries marked "Not assessed".

    4. Retain:
       0 = No hotspot
       1 = Hotspot
       2 = Major hotspot

    5. Keep CERF-mapped countries.

    IMPORTANT:

    ASAP_Hotspot = 0 is a genuine assessed result.
    It must not be treated as missing.
    """

    if data.empty:

        raise RuntimeError(
            "ASAP returned no data."
        )

    # ----------------------------------------------
    # Latest assessment cycle
    # ----------------------------------------------

    latest_date = (
        data["date"]
        .max()
    )

    if pd.isna(
        latest_date
    ):

        raise RuntimeError(
            "Could not determine latest "
            "ASAP assessment date."
        )

    print()
    print(
        "Latest ASAP assessment cycle:"
    )

    print(
        latest_date.strftime(
            "%Y-%m-%d"
        )
    )

    # ----------------------------------------------
    # Latest cycle only
    # ----------------------------------------------

    current = data[
        data[
            "date"
        ].eq(
            latest_date
        )
    ].copy()

    # ----------------------------------------------
    # Exclude Not assessed
    # ----------------------------------------------

    current = current[
        ~current[
            "hs_name"
        ]
        .astype(str)
        .str.strip()
        .str.lower()
        .eq(
            "not assessed"
        )
    ].copy()

    # ----------------------------------------------
    # Retain valid scoring values
    # ----------------------------------------------

    current = current[
        current[
            "hs_code"
        ].isin(
            [
                0,
                1,
                2,
            ]
        )
    ].copy()

    # ----------------------------------------------
    # Mapped countries only
    # ----------------------------------------------

    current = current[
        current[
            "ISO3"
        ].notna()
    ].copy()

    # ----------------------------------------------
    # Duplicate safety check
    # ----------------------------------------------

    duplicates = current[
        current.duplicated(
            subset=["ISO3"],
            keep=False,
        )
    ]

    if not duplicates.empty:

        print()
        print(
            "WARNING: Duplicate ASAP countries "
            "found in latest assessment."
        )

        print(
            duplicates[
                [
                    "Source_Country",
                    "ISO3",
                    "date",
                    "hs_code",
                ]
            ]
            .to_string(
                index=False
            )
        )

    current = (
        current
        .sort_values(
            [
                "ISO3",
                "date",
            ],
            ascending=[
                True,
                False,
            ],
        )
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .copy()
    )

    # ----------------------------------------------
    # Final standardized output
    # ----------------------------------------------

    current = current[
        [
            "ISO3",
            "CERF_Country",
            "Source_Country",
            "date",
            "hs_code",
            "hs_name",
            "asap0_id",
        ]
    ].copy()

    current = current.rename(
        columns={
            "date":
                "ASAP_Date",

            "hs_code":
                "ASAP_Hotspot",

            "hs_name":
                "ASAP_Status",
        }
    )

    current[
        "ASAP_Hotspot"
    ] = (
        current[
            "ASAP_Hotspot"
        ]
        .astype(int)
    )

    return (
        current
        .sort_values(
            "CERF_Country"
        )
        .reset_index(
            drop=True
        )
    )


# ==================================================
# VALIDATE CURRENT OUTPUT
# ==================================================

def validate_current_asap(current):

    problems = []

    if current.empty:

        problems.append(
            "No current ASAP observations."
        )

    if current[
        "ISO3"
    ].duplicated().any():

        problems.append(
            "Duplicate ISO3 records."
        )

    if not current[
        "ASAP_Hotspot"
    ].isin(
        [
            0,
            1,
            2,
        ]
    ).all():

        problems.append(
            "ASAP score outside 0-2."
        )

    if current[
        "ASAP_Date"
    ].nunique() != 1:

        problems.append(
            "More than one assessment date "
            "is present in current output."
        )

    if problems:

        print()
        print(
            "ASAP VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "Current ASAP output failed "
            "validation and was not saved."
        )

    print()
    print(
        "ASAP VALIDATION PASSED"
    )


# ==================================================
# SAVE CURRENT OUTPUT
# ==================================================

def save_current_output(
    current,
    unmatched,
    source_url,
):

    # ----------------------------------------------
    # Production collector output
    # ----------------------------------------------

    csv_data = current.copy()

    csv_data[
        "ASAP_Date"
    ] = (
        csv_data[
            "ASAP_Date"
        ]
        .dt.strftime(
            "%Y-%m-%d"
        )
    )

    csv_data.to_csv(
        current_output,
        index=False,
        encoding="utf-8-sig",
    )

    # ----------------------------------------------
    # Evidence copy
    # ----------------------------------------------

    csv_data.to_csv(
        evidence_output,
        index=False,
        encoding="utf-8-sig",
    )

    # ----------------------------------------------
    # Unmatched names
    # ----------------------------------------------

    unmatched_copy = (
        unmatched.copy()
    )

    if (
        not unmatched_copy.empty
    ):

        unmatched_copy[
            "date"
        ] = (
            pd.to_datetime(
                unmatched_copy[
                    "date"
                ],
                errors="coerce",
            )
            .dt.strftime(
                "%Y-%m-%d"
            )
        )

    unmatched_copy.to_csv(
        unmatched_output,
        index=False,
        encoding="utf-8-sig",
    )

    # ----------------------------------------------
    # Metadata
    # ----------------------------------------------

    latest_date = (
        current[
            "ASAP_Date"
        ]
        .iloc[0]
        .strftime(
            "%Y-%m-%d"
        )
    )

    score_counts = (
        current[
            "ASAP_Hotspot"
        ]
        .value_counts()
        .sort_index()
        .to_dict()
    )

    metadata = {
        "source":
            (
                "ASAP Agricultural "
                "Production Hotspots"
            ),

        "source_url":
            source_url,

        "latest_assessment_cycle":
            latest_date,

        "countries_assessed":
            int(
                len(current)
            ),

        "unmatched_countries":
            int(
                len(unmatched)
            ),

        "score_scale":
            {
                "0":
                    "No hotspot",

                "1":
                    "Hotspot",

                "2":
                    "Major hotspot",
            },

        "score_counts":
            {
                str(key):
                    int(value)

                for key, value
                in score_counts.items()
            },

        "important_missingness_rule":
            (
                "ASAP score 0 is a genuine "
                "assessed No hotspot result. "
                "Only countries absent from the "
                "latest assessed cycle are missing."
            ),
    }

    metadata_output.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "Current ASAP CSV saved to:"
    )

    print(
        current_output
    )


# ==================================================
# COMPLETE DYNAMIC ASAP UPDATE
# ==================================================

def update_asap_hotspots():

    (
        zip_path,
        source_url,
    ) = download_hotspots()

    raw_data = read_hotspots(
        zip_path
    )

    mapping = load_country_mapping()

    standardized = standardize_countries(
        raw_data,
        mapping,
    )

    # ----------------------------------------------
    # Unmatched names from latest cycle only
    # ----------------------------------------------

    latest_date = (
        standardized[
            "date"
        ]
        .max()
    )

    latest_cycle = standardized[
        standardized[
            "date"
        ].eq(
            latest_date
        )
    ].copy()

    unmatched = (
        latest_cycle[
            latest_cycle[
                "ISO3"
            ].isna()
        ][
            [
                "Source_Country",
                "date",
                "hs_code",
                "hs_name",
            ]
        ]
        .drop_duplicates(
            subset=[
                "Source_Country"
            ]
        )
        .sort_values(
            "Source_Country"
        )
    )

    current = (
        calculate_current_asap(
            standardized
        )
    )

    validate_current_asap(
        current
    )

    save_current_output(
        current,
        unmatched,
        source_url,
    )

    return (
        raw_data,
        current,
        unmatched,
    )


# ==================================================
# RUN DIRECTLY
# ==================================================

if __name__ == "__main__":

    (
        raw_data,
        current,
        unmatched,
    ) = update_asap_hotspots()

    print()
    print("=" * 70)

    print(
        "ASAP HOTSPOT UPDATE SUCCESSFUL"
    )

    print("=" * 70)

    print(
        f"Historical ASAP records: "
        f"{len(raw_data)}"
    )

    print(
        f"CERF countries assessed "
        f"in latest cycle: "
        f"{len(current)}"
    )

    print(
        f"Unmatched current ASAP countries: "
        f"{len(unmatched)}"
    )

    print()
    print(
        "ASAP score distribution:"
    )

    print(
        current[
            "ASAP_Hotspot"
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print()
    print(
        "Current ASAP country data:"
    )

    print()

    display = (
        current.copy()
    )

    display[
        "ASAP_Date"
    ] = (
        display[
            "ASAP_Date"
        ]
        .dt.strftime(
            "%Y-%m-%d"
        )
    )

    print(
        display.to_string(
            index=False
        )
    )

    print()
    print("=" * 70)

    print(
        "UNMATCHED CURRENT SOURCE COUNTRIES"
    )

    print("=" * 70)

    if unmatched.empty:

        print(
            "None. All current ASAP country "
            "names were mapped to CERF."
        )

    else:

        print(
            unmatched.to_string(
                index=False
            )
        )

    print()
    print(
        f"Production output:\n"
        f"{current_output}"
    )