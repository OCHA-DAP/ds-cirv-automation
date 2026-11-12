from pathlib import Path
from datetime import datetime, timezone
import json
import math
import re

import pandas as pd
import requests


# ==================================================
# SETTINGS
# ==================================================

TRENDS_API_URL = (
    "https://trendfinder-api.acledapps.com/"
    "api/v1/overview"
)

TRENDS_PAGE_URL = (
    "https://acleddata.com/platform/trends"
)

# --------------------------------------------------
# CIRV ACLED Trends methodology
# --------------------------------------------------
#
# outcome = organized_violence
#
# lead = 0
#     Most recent completed four-week measured period.
#
# lag = 1
#     Compare the measured period with the average
#     of the previous month.
#
# change_pct is a fractional change:
#
#     0.68  = +68%
#    -0.53  = -53%
# --------------------------------------------------

ACLED_OUTCOME = (
    "organized_violence"
)

ACLED_LEAD = 0

ACLED_LAG = 1

ACLED_COMPARISON_LABEL = (
    "Month"
)

MINIMUM_EXPECTED_MAPPED_COUNTRIES = 100

REQUEST_TIMEOUT_SECONDS = 120


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = (
    Path(__file__).parent.parent
)

mapping_file = (
    project_folder
    / "config"
    / "countries.csv"
)

raw_folder = (
    project_folder
    / "data"
    / "raw"
    / "acled"
    / "trends"
)

processed_folder = (
    project_folder
    / "data"
    / "processed"
)

raw_folder.mkdir(
    parents=True,
    exist_ok=True,
)

processed_folder.mkdir(
    parents=True,
    exist_ok=True,
)

raw_json_output = (
    raw_folder
    / "acled_trends_latest_response.json"
)

current_output = (
    project_folder
    / "acled_trends_current.csv"
)

evidence_output = (
    processed_folder
    / "acled_trends_evidence.csv"
)

unmatched_output = (
    processed_folder
    / "acled_trends_unmatched.csv"
)

metadata_output = (
    processed_folder
    / "acled_trends_metadata.json"
)


# ==================================================
# BASIC HELPERS
# ==================================================

def normalize_text(value):

    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
        .split()
    )


def is_missing(value):

    if value is None:
        return True

    try:

        if pd.isna(value):
            return True

    except TypeError:

        pass

    return (
        str(value)
        .strip()
        .lower()
        in {
            "",
            "nan",
            "none",
            "null",
            "na",
            "n/a",
            "<na>",
        }
    )


def parse_numeric(value):

    if is_missing(value):
        return None

    if isinstance(
        value,
        bool,
    ):

        return None

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):

        number = float(value)

        if math.isfinite(number):
            return number

        return None

    text = (
        str(value)
        .strip()
        .replace(",", "")
        .replace("%", "")
    )

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text,
    )

    if not match:
        return None

    number = float(
        match.group(0)
    )

    if not math.isfinite(number):
        return None

    return number


def normalize_iso3(value):

    if is_missing(value):
        return None

    text = (
        str(value)
        .strip()
        .upper()
    )

    if (
        len(text) == 3
        and
        text.isalpha()
    ):

        return text

    return None


# ==================================================
# ROBUST DATE PARSING
# ==================================================

def parse_date(value):
    """
    Parse ordinary date strings and Unix timestamps.

    ACLED Trends metadata currently contains Unix
    timestamps in seconds, such as:

        1787961600

    Calling pd.to_datetime() without a unit treats
    that number as nanoseconds and incorrectly
    returns a date near 1 January 1970.

    This function detects:
        seconds
        milliseconds
        microseconds
        nanoseconds
    """

    if is_missing(value):
        return pd.NaT

    if isinstance(
        value,
        bool,
    ):

        return pd.NaT

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):

        number = float(value)

        if not math.isfinite(
            number
        ):

            return pd.NaT

        absolute = abs(
            number
        )

        try:

            if absolute < 100000000000:

                # Unix seconds.

                return pd.to_datetime(
                    number,
                    unit="s",
                    errors="coerce",
                    utc=True,
                ).tz_localize(None)

            if absolute < 100000000000000:

                # Unix milliseconds.

                return pd.to_datetime(
                    number,
                    unit="ms",
                    errors="coerce",
                    utc=True,
                ).tz_localize(None)

            if absolute < 100000000000000000:

                # Unix microseconds.

                return pd.to_datetime(
                    number,
                    unit="us",
                    errors="coerce",
                    utc=True,
                ).tz_localize(None)

            # Unix nanoseconds.

            return pd.to_datetime(
                number,
                unit="ns",
                errors="coerce",
                utc=True,
            ).tz_localize(None)

        except Exception:

            return pd.NaT

    text = str(value).strip()

    # Numeric timestamp supplied as text.

    if re.fullmatch(
        r"-?\d+(?:\.\d+)?",
        text,
    ):

        try:

            return parse_date(
                float(text)
            )

        except ValueError:

            return pd.NaT

    parsed = pd.to_datetime(
        text,
        errors="coerce",
        utc=True,
    )

    if pd.isna(parsed):

        return pd.NaT

    if isinstance(
        parsed,
        pd.Timestamp,
    ):

        if parsed.tzinfo is not None:

            parsed = (
                parsed
                .tz_convert("UTC")
                .tz_localize(None)
            )

    return parsed


def valid_modern_date(value):
    """
    Reject accidental epoch dates and implausible
    dates caused by selecting the wrong metadata.
    """

    parsed = parse_date(
        value
    )

    if pd.isna(parsed):
        return pd.NaT

    if (
        parsed.year < 2000
        or
        parsed.year > 2100
    ):

        return pd.NaT

    return parsed


# ==================================================
# FLATTEN JSON
# ==================================================

def flatten_record(
    value,
    parent_key="",
):

    output = {}

    if isinstance(
        value,
        dict,
    ):

        for key, nested in (
            value.items()
        ):

            new_key = (
                f"{parent_key}.{key}"

                if parent_key

                else

                str(key)
            )

            output.update(
                flatten_record(
                    nested,
                    new_key,
                )
            )

    elif isinstance(
        value,
        list,
    ):

        output[
            parent_key
        ] = value

    else:

        output[
            parent_key
        ] = value

    return output


def first_present(
    record,
    candidates,
):

    lookup = {
        normalize_text(key):
            key

        for key
        in record.keys()
    }

    # Exact leaf-name match first.

    for candidate in candidates:

        normalized_candidate = (
            normalize_text(
                candidate
            )
        )

        for (
            normalized_key,
            actual_key,
        ) in lookup.items():

            leaf_name = (
                normalized_key
                .split(".")[-1]
            )

            if (
                leaf_name
                ==
                normalized_candidate
            ):

                value = record.get(
                    actual_key
                )

                if not is_missing(
                    value
                ):

                    return value

    # Controlled nested-key suffix match.

    for candidate in candidates:

        normalized_candidate = (
            normalize_text(
                candidate
            )
        )

        for (
            normalized_key,
            actual_key,
        ) in lookup.items():

            if normalized_key.endswith(
                normalized_candidate
            ):

                value = record.get(
                    actual_key
                )

                if not is_missing(
                    value
                ):

                    return value

    return None


# ==================================================
# COUNTRY FIELD CANDIDATES
# ==================================================

COUNTRY_NAME_CANDIDATES = [
    "country",
    "country_name",
    "countryName",
    "name",
]

COUNTRY_ID_CANDIDATES = [
    "country_id",
    "countryId",
    "m49",
    "un_m49",
    "location_id",
]

ISO3_CANDIDATES = [
    "iso3",
    "iso_a3",
    "country_iso3",
    "country_code",
]

REGION_CANDIDATES = [
    "region",
    "region_name",
]

EVENT_COUNT_CANDIDATES = [
    "event_count",
    "eventCount",
    "events",
    "count",
    "value",
]

CHANGE_PERCENT_CANDIDATES = [
    "change_pct",
    "changePct",
    "change_percent",
    "changePercent",
    "percentage_change",
    "percent_change",
]

CHANGE_ABSOLUTE_CANDIDATES = [
    "change_abs",
    "changeAbs",
    "absolute_change",
    "change_absolute",
]


# ==================================================
# DATE METADATA CANDIDATES
# ==================================================

PERIOD_START_CANDIDATES = [
    "period_start",
    "periodStart",
    "measured_period_start",
    "current_period_start",
]

PERIOD_END_CANDIDATES = [
    "period_end",
    "periodEnd",
    "measured_period_end",
    "current_period_end",
]

COMPARISON_START_CANDIDATES = [
    "comparison_start",
    "comparisonStart",
    "baseline_start",
]

COMPARISON_END_CANDIDATES = [
    "comparison_end",
    "comparisonEnd",
    "baseline_end",
]

LATEST_UPDATE_CANDIDATES = [
    "latest_update",
    "latestUpdate",
    "update_date",
    "updated",
    "last_updated",
]


# ==================================================
# DISCOVER COUNTRY ARRAY
# ==================================================

def extract_country_records(
    payload,
):

    if not isinstance(
        payload,
        dict,
    ):

        raise RuntimeError(
            "Unexpected ACLED Trends response."
        )

    display_data = (
        payload.get(
            "displayData"
        )
        or
        payload.get(
            "display_data"
        )
    )

    if (
        isinstance(
            display_data,
            dict,
        )
        and
        isinstance(
            display_data.get(
                "countries"
            ),
            list,
        )
    ):

        return (
            display_data[
                "countries"
            ],
            "displayData.countries",
        )

    candidates = []

    def search(
        value,
        path="root",
    ):

        if isinstance(
            value,
            dict,
        ):

            for key, nested in (
                value.items()
            ):

                search(
                    nested,
                    f"{path}.{key}",
                )

        elif isinstance(
            value,
            list,
        ):

            dictionaries = [
                item

                for item
                in value

                if isinstance(
                    item,
                    dict,
                )
            ]

            if dictionaries:

                flattened = (
                    flatten_record(
                        dictionaries[0]
                    )
                )

                country = first_present(
                    flattened,
                    COUNTRY_NAME_CANDIDATES,
                )

                change = first_present(
                    flattened,
                    CHANGE_PERCENT_CANDIDATES,
                )

                if (
                    country is not None
                    and
                    change is not None
                ):

                    candidates.append(
                        (
                            path,
                            value,
                        )
                    )

    search(
        payload
    )

    if not candidates:

        raise RuntimeError(
            "Could not locate the ACLED Trends "
            "country records."
        )

    candidates.sort(
        key=lambda item:
            len(
                item[1]
            ),
        reverse=True,
    )

    return candidates[0]


# ==================================================
# COLLECT SCALAR METADATA
# ==================================================

def collect_scalar_metadata(
    value,
    path="root",
):

    output = []

    if isinstance(
        value,
        dict,
    ):

        for key, nested in (
            value.items()
        ):

            new_path = (
                f"{path}.{key}"
            )

            # Do not recursively search the country
            # array for global period metadata.

            if normalize_text(
                new_path
            ).endswith(
                "displaydata countries"
            ):

                continue

            if isinstance(
                nested,
                dict,
            ):

                output.extend(
                    collect_scalar_metadata(
                        nested,
                        new_path,
                    )
                )

            elif isinstance(
                nested,
                list,
            ):

                # Skip repetitive country lists.

                continue

            else:

                output.append(
                    (
                        new_path,
                        key,
                        nested,
                    )
                )

    return output


def find_exact_metadata_value(
    scalars,
    candidates,
):

    normalized_candidates = {
        normalize_text(
            candidate
        )

        for candidate
        in candidates
    }

    # Match exact leaf key only.

    for (
        path,
        leaf_key,
        value,
    ) in scalars:

        normalized_leaf = (
            normalize_text(
                leaf_key
            )
        )

        if (
            normalized_leaf
            in normalized_candidates
            and
            not is_missing(
                value
            )
        ):

            return value

    return None


def print_date_metadata_candidates(
    scalars,
):

    print()
    print(
        "Date-like metadata fields found:"
    )

    found = False

    for (
        path,
        leaf_key,
        value,
    ) in scalars:

        normalized = (
            normalize_text(
                leaf_key
            )
        )

        if any(
            keyword in normalized
            for keyword in [
                "date",
                "start",
                "end",
                "update",
                "period",
                "comparison",
            ]
        ):

            print(
                f"- {path}: {value}"
            )

            found = True

    if not found:

        print(
            "- None"
        )


# ==================================================
# EXTRACT GLOBAL PERIOD METADATA
# ==================================================

def extract_global_metadata(
    payload,
):

    scalars = (
        collect_scalar_metadata(
            payload
        )
    )

    print_date_metadata_candidates(
        scalars
    )

    period_start_raw = (
        find_exact_metadata_value(
            scalars,
            PERIOD_START_CANDIDATES,
        )
    )

    period_end_raw = (
        find_exact_metadata_value(
            scalars,
            PERIOD_END_CANDIDATES,
        )
    )

    comparison_start_raw = (
        find_exact_metadata_value(
            scalars,
            COMPARISON_START_CANDIDATES,
        )
    )

    comparison_end_raw = (
        find_exact_metadata_value(
            scalars,
            COMPARISON_END_CANDIDATES,
        )
    )

    latest_update_raw = (
        find_exact_metadata_value(
            scalars,
            LATEST_UPDATE_CANDIDATES,
        )
    )

    period_start = valid_modern_date(
        period_start_raw
    )

    period_end = valid_modern_date(
        period_end_raw
    )

    comparison_start = (
        valid_modern_date(
            comparison_start_raw
        )
    )

    comparison_end = (
        valid_modern_date(
            comparison_end_raw
        )
    )

    latest_update = (
        valid_modern_date(
            latest_update_raw
        )
    )

    # ----------------------------------------------
    # The API sometimes exposes the comparison
    # window but not the measured window.
    #
    # The most recent measured four-week window
    # immediately follows the comparison month:
    #
    # measured start = comparison end + 1 day
    # measured end   = measured start + 27 days
    # ----------------------------------------------

    if (
        pd.isna(
            period_start
        )
        and
        not pd.isna(
            comparison_end
        )
    ):

        period_start = (
            comparison_end
            +
            pd.Timedelta(
                days=1
            )
        )

    if (
        pd.isna(
            period_end
        )
        and
        not pd.isna(
            period_start
        )
    ):

        period_end = (
            period_start
            +
            pd.Timedelta(
                days=27
            )
        )

    # If only measured period end is supplied,
    # derive its 28-day inclusive start.

    if (
        pd.isna(
            period_start
        )
        and
        not pd.isna(
            period_end
        )
    ):

        period_start = (
            period_end
            -
            pd.Timedelta(
                days=27
            )
        )

    # ----------------------------------------------
    # Do not infer the comparison label from a
    # numeric metadata field.
    #
    # lag=1 is explicitly configured as Month.
    # ----------------------------------------------

    comparison = (
        ACLED_COMPARISON_LABEL
    )

    return {
        "period_start":
            period_start,

        "period_end":
            period_end,

        "comparison":
            comparison,

        "comparison_start":
            comparison_start,

        "comparison_end":
            comparison_end,

        "latest_update":
            latest_update,

        "raw_period_start":
            period_start_raw,

        "raw_period_end":
            period_end_raw,

        "raw_comparison_start":
            comparison_start_raw,

        "raw_comparison_end":
            comparison_end_raw,

        "raw_latest_update":
            latest_update_raw,
    }


# ==================================================
# LOAD CERF COUNTRY MAPPING
# ==================================================

def load_country_mapping():

    if not mapping_file.exists():

        raise FileNotFoundError(
            "CERF mapping file not found:\n"
            f"{mapping_file}"
        )

    mapping = pd.read_csv(
        mapping_file,
        encoding="utf-8-sig",
        low_memory=False,
    )

    required = [
        "ISO3",
        "CERF_Country",
    ]

    missing = [
        column

        for column
        in required

        if column
        not in mapping.columns
    ]

    if missing:

        raise RuntimeError(
            "config/countries.csv is missing:\n"
            f"{missing}"
        )

    mapping[
        "ISO3"
    ] = mapping[
        "ISO3"
    ].apply(
        normalize_iso3
    )

    mapping = mapping[
        mapping[
            "ISO3"
        ].notna()
    ].copy()

    universe = (
        mapping[
            [
                "ISO3",
                "CERF_Country",
            ]
        ]
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
    )

    if (
        "Source_Alias"
        in mapping.columns
    ):

        aliases = mapping[
            [
                "ISO3",
                "CERF_Country",
                "Source_Alias",
            ]
        ].copy()

    else:

        aliases = (
            universe.copy()
        )

        aliases[
            "Source_Alias"
        ] = aliases[
            "CERF_Country"
        ]

    aliases[
        "Normalized_Alias"
    ] = aliases[
        "Source_Alias"
    ].apply(
        normalize_text
    )

    return (
        universe,
        aliases,
    )


# ==================================================
# REQUEST ACLED TRENDS
# ==================================================

def request_trends_data():

    parameters = {
        "outcome":
            ACLED_OUTCOME,

        "lead":
            ACLED_LEAD,

        "lag":
            ACLED_LAG,
    }

    headers = {
        "User-Agent":
            (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            ),

        "Accept":
            "application/json",

        "Referer":
            TRENDS_PAGE_URL,
    }

    print(
        "Requesting ACLED Trends..."
    )

    print(
        f"Outcome: {ACLED_OUTCOME}"
    )

    print(
        "Lead: 0 "
        "(latest completed four-week period)"
    )

    print(
        "Lag: 1 "
        "(previous month average)"
    )

    response = requests.get(
        TRENDS_API_URL,
        params=parameters,
        headers=headers,
        timeout=(
            REQUEST_TIMEOUT_SECONDS
        ),
    )

    if response.status_code != 200:

        raise RuntimeError(
            "ACLED Trends request failed.\n\n"
            f"HTTP status: "
            f"{response.status_code}\n"
            f"URL: {response.url}\n"
            f"Response:\n"
            f"{response.text[:1000]}"
        )

    try:

        payload = (
            response.json()
        )

    except ValueError as exc:

        raise RuntimeError(
            "ACLED Trends returned "
            "non-JSON content."
        ) from exc

    raw_json_output.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return (
        payload,
        response.url,
    )


# ==================================================
# STANDARDIZE ONE COUNTRY
# ==================================================

def standardize_country_record(
    record,
    global_metadata,
):

    flattened = (
        flatten_record(
            record
        )
    )

    country = first_present(
        flattened,
        COUNTRY_NAME_CANDIDATES,
    )

    if is_missing(
        country
    ):

        return None

    change_fraction = parse_numeric(
        first_present(
            flattened,
            CHANGE_PERCENT_CANDIDATES,
        )
    )

    if change_fraction is None:

        return None

    country_id = first_present(
        flattened,
        COUNTRY_ID_CANDIDATES,
    )

    iso3 = normalize_iso3(
        first_present(
            flattened,
            ISO3_CANDIDATES,
        )
    )

    region = first_present(
        flattened,
        REGION_CANDIDATES,
    )

    event_count = parse_numeric(
        first_present(
            flattened,
            EVENT_COUNT_CANDIDATES,
        )
    )

    change_absolute = parse_numeric(
        first_present(
            flattened,
            CHANGE_ABSOLUTE_CANDIDATES,
        )
    )

    # The date fields describe the dashboard
    # assessment, not country-specific observations.

    period_start = (
        global_metadata[
            "period_start"
        ]
    )

    period_end = (
        global_metadata[
            "period_end"
        ]
    )

    comparison_start = (
        global_metadata[
            "comparison_start"
        ]
    )

    comparison_end = (
        global_metadata[
            "comparison_end"
        ]
    )

    latest_update = (
        global_metadata[
            "latest_update"
        ]
    )

    change_percentage = (
        change_fraction
        *
        100.0
    )

    return {
        "ACLED_Country":
            str(
                country
            ).strip(),

        "ACLED_Country_ID":
            (
                str(
                    country_id
                ).strip()

                if not is_missing(
                    country_id
                )

                else

                None
            ),

        "ACLED_ISO3":
            iso3,

        "ACLED_Region":
            (
                str(
                    region
                ).strip()

                if not is_missing(
                    region
                )

                else

                None
            ),

        "ACLED_Trends_Event_Count":
            event_count,

        "ACLED_Trends_Change_Fraction":
            change_fraction,

        "ACLED_Trends_Percent":
            change_percentage,

        "ACLED_Trends_Absolute_Change":
            change_absolute,

        "ACLED_Trends_Period_Start":
            period_start,

        "ACLED_Trends_Period_End":
            period_end,

        "ACLED_Trends_Comparison":
            ACLED_COMPARISON_LABEL,

        "ACLED_Trends_Comparison_Start":
            comparison_start,

        "ACLED_Trends_Comparison_End":
            comparison_end,

        "ACLED_Trends_Latest_Update":
            latest_update,

        "Normalized_Country":
            normalize_text(
                country
            ),
    }


# ==================================================
# MAP COUNTRIES
# ==================================================

def map_countries(
    prepared,
    universe,
    aliases,
):

    direct = prepared.merge(
        universe,
        left_on="ACLED_ISO3",
        right_on="ISO3",
        how="left",
    )

    direct_hits = direct[
        direct[
            "CERF_Country"
        ].notna()
    ].copy()

    alias_needed = direct[
        direct[
            "CERF_Country"
        ].isna()
    ].copy()

    alias_needed = alias_needed.drop(
        columns=[
            "ISO3",
            "CERF_Country",
        ],
        errors="ignore",
    )

    alias_needed = alias_needed.merge(
        aliases[
            [
                "ISO3",
                "CERF_Country",
                "Normalized_Alias",
            ]
        ],
        left_on=(
            "Normalized_Country"
        ),
        right_on=(
            "Normalized_Alias"
        ),
        how="left",
    )

    return pd.concat(
        [
            direct_hits,
            alias_needed,
        ],
        ignore_index=True,
        sort=False,
    )


# ==================================================
# STANDARDIZE RESPONSE
# ==================================================

def standardize_trends(
    payload,
    universe,
    aliases,
):

    (
        country_records,
        record_path,
    ) = extract_country_records(
        payload
    )

    print()
    print(
        "Country records found at:"
    )

    print(
        record_path
    )

    print(
        f"Raw country records: "
        f"{len(country_records)}"
    )

    global_metadata = (
        extract_global_metadata(
            payload
        )
    )

    print()
    print(
        "ACLED Trends period metadata:"
    )

    print(
        "Period start: "
        f"{global_metadata['period_start']}"
    )

    print(
        "Period end: "
        f"{global_metadata['period_end']}"
    )

    print(
        "Comparison: "
        f"{global_metadata['comparison']}"
    )

    print(
        "Comparison start: "
        f"{global_metadata['comparison_start']}"
    )

    print(
        "Comparison end: "
        f"{global_metadata['comparison_end']}"
    )

    print(
        "Latest update: "
        f"{global_metadata['latest_update']}"
    )

    standardized_records = []

    for record in (
        country_records
    ):

        if not isinstance(
            record,
            dict,
        ):

            continue

        standardized = (
            standardize_country_record(
                record,
                global_metadata,
            )
        )

        if (
            standardized
            is not None
        ):

            standardized_records.append(
                standardized
            )

    prepared = pd.DataFrame(
        standardized_records
    )

    if prepared.empty:

        raise RuntimeError(
            "No valid ACLED Trends "
            "country records were parsed."
        )

    mapped = map_countries(
        prepared,
        universe,
        aliases,
    )

    unmatched = (
        mapped[
            mapped[
                "CERF_Country"
            ].isna()
        ][
            [
                "ACLED_Country",
                "ACLED_Country_ID",
                "ACLED_Region",
                "ACLED_Trends_Event_Count",
                "ACLED_Trends_Change_Fraction",
                "ACLED_Trends_Percent",
                "ACLED_Trends_Absolute_Change",
                "ACLED_Trends_Period_Start",
                "ACLED_Trends_Period_End",
            ]
        ]
        .drop_duplicates()
        .sort_values(
            "ACLED_Country"
        )
    )

    current = mapped[
        mapped[
            "CERF_Country"
        ].notna()
    ].copy()

    current = (
        current
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .reset_index(
            drop=True
        )
    )

    current = current[
        [
            "ISO3",
            "CERF_Country",
            "ACLED_Country",
            "ACLED_Country_ID",
            "ACLED_Region",
            "ACLED_Trends_Event_Count",
            "ACLED_Trends_Change_Fraction",
            "ACLED_Trends_Percent",
            "ACLED_Trends_Absolute_Change",
            "ACLED_Trends_Period_Start",
            "ACLED_Trends_Period_End",
            "ACLED_Trends_Comparison",
            "ACLED_Trends_Comparison_Start",
            "ACLED_Trends_Comparison_End",
            "ACLED_Trends_Latest_Update",
        ]
    ].copy()

    return (
        current,
        unmatched,
        record_path,
        len(
            country_records
        ),
        global_metadata,
    )


# ==================================================
# VALIDATION
# ==================================================

def validate_results(
    current,
):

    problems = []

    if (
        len(current)
        <
        MINIMUM_EXPECTED_MAPPED_COUNTRIES
    ):

        problems.append(
            (
                f"Only {len(current)} CERF "
                "countries received Trends values."
            )
        )

    if current[
        "ISO3"
    ].duplicated().any():

        problems.append(
            "Duplicate Trends ISO3 records."
        )

    if current[
        "ACLED_Trends_Percent"
    ].isna().any():

        problems.append(
            "Missing Trends percentages."
        )

    expected = (
        current[
            "ACLED_Trends_Change_Fraction"
        ]
        *
        100.0
    )

    conversion_difference = (
        current[
            "ACLED_Trends_Percent"
        ]
        -
        expected
    ).abs()

    if conversion_difference.gt(
        0.000001
    ).any():

        problems.append(
            "Fraction-to-percentage conversion failed."
        )

    # Validate four-week period only where metadata
    # exists.

    dated_rows = current[
        current[
            "ACLED_Trends_Period_Start"
        ].notna()
        &
        current[
            "ACLED_Trends_Period_End"
        ].notna()
    ].copy()

    if not dated_rows.empty:

        duration = (
            dated_rows[
                "ACLED_Trends_Period_End"
            ]
            -
            dated_rows[
                "ACLED_Trends_Period_Start"
            ]
        ).dt.days

        invalid_duration = dated_rows[
            ~duration.eq(
                27
            )
        ]

        if not invalid_duration.empty:

            problems.append(
                (
                    f"{len(invalid_duration)} records "
                    "do not represent a 28-day "
                    "four-week period."
                )
            )

    # Explicitly reject the epoch-date bug.

    date_columns = [
        "ACLED_Trends_Period_Start",
        "ACLED_Trends_Period_End",
        "ACLED_Trends_Comparison_Start",
        "ACLED_Trends_Comparison_End",
        "ACLED_Trends_Latest_Update",
    ]

    for column in date_columns:

        invalid_epoch = current[
            current[
                column
            ].notna()
            &
            current[
                column
            ].dt.year.lt(
                2000
            )
        ]

        if not invalid_epoch.empty:

            problems.append(
                (
                    f"{len(invalid_epoch)} values in "
                    f"{column} are invalid epoch dates."
                )
            )

    if problems:

        print()
        print(
            "ACLED TRENDS VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "ACLED Trends validation failed."
        )

    print()
    print(
        "ACLED TRENDS VALIDATION PASSED"
    )

    print(
        f"CERF countries mapped: "
        f"{len(current)}"
    )


# ==================================================
# SAVE OUTPUTS
# ==================================================

def save_outputs(
    current,
    unmatched,
    request_url,
    record_path,
    raw_record_count,
    global_metadata,
):

    output = (
        current.copy()
    )

    date_columns = [
        "ACLED_Trends_Period_Start",
        "ACLED_Trends_Period_End",
        "ACLED_Trends_Comparison_Start",
        "ACLED_Trends_Comparison_End",
        "ACLED_Trends_Latest_Update",
    ]

    for column in date_columns:

        output[column] = (
            pd.to_datetime(
                output[
                    column
                ],
                errors="coerce",
            )
            .dt.strftime(
                "%Y-%m-%d"
            )
        )

    unmatched_copy = (
        unmatched.copy()
    )

    for column in date_columns:

        if (
            column
            in unmatched_copy.columns
        ):

            unmatched_copy[
                column
            ] = (
                pd.to_datetime(
                    unmatched_copy[
                        column
                    ],
                    errors="coerce",
                )
                .dt.strftime(
                    "%Y-%m-%d"
                )
            )

    output.to_csv(
        current_output,
        index=False,
        encoding="utf-8-sig",
    )

    output.to_csv(
        evidence_output,
        index=False,
        encoding="utf-8-sig",
    )

    unmatched_copy.to_csv(
        unmatched_output,
        index=False,
        encoding="utf-8-sig",
    )

    def metadata_date(
        value,
    ):

        if pd.isna(
            value
        ):

            return None

        return (
            pd.Timestamp(
                value
            )
            .strftime(
                "%Y-%m-%d"
            )
        )

    metadata = {
        "source":
            "ACLED Trends",

        "source_page":
            TRENDS_PAGE_URL,

        "api_url":
            request_url,

        "retrieved_at_utc":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "cirv_method":
            (
                "Use organized-violence activity "
                "during the latest completed "
                "four-week period and compare it "
                "with the previous-month average."
            ),

        "api_parameters":
            {
                "outcome":
                    ACLED_OUTCOME,

                "lead":
                    ACLED_LEAD,

                "lag":
                    ACLED_LAG,
            },

        "comparison":
            ACLED_COMPARISON_LABEL,

        "change_pct_handling":
            (
                "ACLED change_pct is fractional. "
                "The collector multiplies it by "
                "100 to produce an ordinary signed "
                "percentage."
            ),

        "country_records_path":
            record_path,

        "raw_country_records":
            int(
                raw_record_count
            ),

        "mapped_countries":
            int(
                len(output)
            ),

        "unmatched_countries":
            int(
                len(unmatched_copy)
            ),

        "measured_period_start":
            metadata_date(
                global_metadata[
                    "period_start"
                ]
            ),

        "measured_period_end":
            metadata_date(
                global_metadata[
                    "period_end"
                ]
            ),

        "comparison_period_start":
            metadata_date(
                global_metadata[
                    "comparison_start"
                ]
            ),

        "comparison_period_end":
            metadata_date(
                global_metadata[
                    "comparison_end"
                ]
            ),

        "latest_acled_update":
            metadata_date(
                global_metadata[
                    "latest_update"
                ]
            ),

        "raw_api_metadata":
            {
                "period_start":
                    global_metadata[
                        "raw_period_start"
                    ],

                "period_end":
                    global_metadata[
                        "raw_period_end"
                    ],

                "comparison_start":
                    global_metadata[
                        "raw_comparison_start"
                    ],

                "comparison_end":
                    global_metadata[
                        "raw_comparison_end"
                    ],

                "latest_update":
                    global_metadata[
                        "raw_latest_update"
                    ],
            },
    }

    metadata_output.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )

    return output


# ==================================================
# COMPLETE UPDATE
# ==================================================

def update_acled_trends():

    (
        payload,
        request_url,
    ) = request_trends_data()

    (
        universe,
        aliases,
    ) = load_country_mapping()

    (
        current,
        unmatched,
        record_path,
        raw_record_count,
        global_metadata,
    ) = standardize_trends(
        payload,
        universe,
        aliases,
    )

    validate_results(
        current
    )

    return save_outputs(
        current,
        unmatched,
        request_url,
        record_path,
        raw_record_count,
        global_metadata,
    )


# ==================================================
# MAIN
# ==================================================

if __name__ == "__main__":

    current = (
        update_acled_trends()
    )

    print()
    print("=" * 70)

    print(
        "ACLED TRENDS UPDATE COMPLETE"
    )

    print("=" * 70)

    print(
        f"CERF countries mapped: "
        f"{len(current)}"
    )

    period_rows = current[
        current[
            "ACLED_Trends_Period_End"
        ].notna()
    ]

    if not period_rows.empty:

        first = (
            period_rows.iloc[0]
        )

        print(
            "Measured four-week period: "
            f"{first['ACLED_Trends_Period_Start']} "
            "to "
            f"{first['ACLED_Trends_Period_End']}"
        )

    print()
    print(
        "Largest increases in organized violence:"
    )

    print()

    display_columns = [
        "CERF_Country",
        "ISO3",
        "ACLED_Trends_Event_Count",
        "ACLED_Trends_Percent",
        "ACLED_Trends_Absolute_Change",
        "ACLED_Trends_Period_Start",
        "ACLED_Trends_Period_End",
        "ACLED_Trends_Comparison",
        "ACLED_Trends_Comparison_Start",
        "ACLED_Trends_Comparison_End",
        "ACLED_Trends_Latest_Update",
    ]

    print(
        current[
            display_columns
        ]
        .sort_values(
            "ACLED_Trends_Percent",
            ascending=False,
        )
        .head(50)
        .to_string(
            index=False
        )
    )

    print()
    print(
        "Largest decreases in organized violence:"
    )

    print()

    print(
        current[
            display_columns
        ]
        .sort_values(
            "ACLED_Trends_Percent",
            ascending=True,
        )
        .head(25)
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
        f"Metadata saved to:\n"
        f"{metadata_output}"
    )