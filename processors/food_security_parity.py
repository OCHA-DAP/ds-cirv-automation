from pathlib import Path
import math
import re

import pandas as pd

from processors.food_security import (
    IPC_BASE_WEIGHT,
    SHOCK_BASE_WEIGHT,
    SOFI_BASE_WEIGHT,
    IPC_OVERRIDES,
)


# ==================================================
# SETTINGS
# ==================================================

PARITY_TOLERANCE = 0.000001

WORKBOOK_SHEET = (
    "CERF UFE 2026-I All Data"
)

project_folder = (
    Path(__file__).parent.parent
)

processed_folder = (
    project_folder
    / "data"
    / "processed"
)

processed_folder.mkdir(
    parents=True,
    exist_ok=True,
)

output_file = (
    processed_folder
    / "food_security_august_parity.csv"
)


# ==================================================
# BASIC UTILITIES
# ==================================================

def normalize_text(value):

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass

    text = str(value).strip()

    text = (
        text
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("–", "-")
        .replace("—", "-")
    )

    return " ".join(
        text.split()
    ).lower()


def parse_numeric(value):

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

    except TypeError:

        pass

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):

        numeric = float(value)

        if math.isfinite(numeric):
            return numeric

        return None

    text = str(value).strip()

    if not text:
        return None

    text = (
        text
        .replace(",", "")
        .replace("<", "")
        .replace(">", "")
    )

    match = re.search(
        r"-?\d+(?:\.\d+)?",
        text,
    )

    if not match:
        return None

    numeric = float(
        match.group(0)
    )

    if not math.isfinite(numeric):
        return None

    return numeric


# ==================================================
# AUGUST WORKBOOK AVAILABILITY RULES
# ==================================================

def ipc_available(value):
    """
    August workbook IPC rule:

    1-5 = available.
    0 / blank / NaN = unavailable.
    """

    numeric = parse_numeric(
        value
    )

    if numeric is None:
        return False

    return (
        numeric > 0
        and
        numeric <= 5
    )


def shock_available(value):
    """
    August workbook FAO / ASAP rule:

    1-2 = available.
    0 / blank / NaN = unavailable.

    This reproduces the historical workbook formula.
    """

    numeric = parse_numeric(
        value
    )

    if numeric is None:
        return False

    return (
        numeric > 0
        and
        numeric <= 2
    )


def sofi_available(value):
    """
    August workbook SOFI rule:

    Positive 0-100 percentage = available.

    Zero / blank / NaN = unavailable.
    """

    numeric = parse_numeric(
        value
    )

    if numeric is None:
        return False

    return (
        numeric > 0
        and
        numeric <= 100
    )


# ==================================================
# FIND AUGUST WORKBOOK
# ==================================================

def find_workbook():

    candidates = list(
        project_folder.glob(
            "260810*.xlsx"
        )
    )

    if not candidates:

        raise FileNotFoundError(
            "Could not find a workbook beginning "
            "with 260810 in the project root."
        )

    if len(candidates) > 1:

        print()
        print(
            "Multiple 260810 workbooks found:"
        )

        for candidate in candidates:

            print(
                f"- {candidate.name}"
            )

        raise RuntimeError(
            "Keep only the intended August CIRV "
            "workbook in the project root."
        )

    workbook = candidates[0]

    print(
        "August parity workbook:"
    )

    print(
        workbook
    )

    return workbook


# ==================================================
# DETECT ACTUAL HEADER ROW
# ==================================================

def detect_header_row(
    workbook,
):

    preview = pd.read_excel(
        workbook,
        sheet_name=WORKBOOK_SHEET,
        header=None,
        engine="openpyxl",
        nrows=20,
    )

    print()
    print(
        "Inspecting workbook header rows..."
    )

    for row_index in preview.index:

        row_values = [
            normalize_text(value)
            for value in preview.loc[
                row_index
            ].tolist()
        ]

        has_country = any(
            value == "country"
            for value in row_values
        )

        has_iso3 = any(
            value == "iso3 country code"
            for value in row_values
        )

        if (
            has_country
            and
            has_iso3
        ):

            print(
                "Detected actual field header "
                f"at Excel row {row_index + 1}."
            )

            return int(
                row_index
            )

    print()
    print(
        "First 20 unformatted rows:"
    )

    print(
        preview.to_string(
            index=True,
            header=False,
        )
    )

    raise RuntimeError(
        "Could not automatically find the workbook "
        "header row containing Country and "
        "ISO3 Country Code."
    )


# ==================================================
# READ AUGUST WORKBOOK
# ==================================================

def read_august_data(
    workbook,
):

    header_row = detect_header_row(
        workbook
    )

    print()
    print(
        f"Reading sheet: {WORKBOOK_SHEET}"
    )

    print(
        f"Pandas header row index: "
        f"{header_row}"
    )

    data = pd.read_excel(
        workbook,
        sheet_name=WORKBOOK_SHEET,
        header=header_row,
        engine="openpyxl",
    )

    print()
    print(
        f"Raw workbook rows: "
        f"{len(data)}"
    )

    print()
    print(
        "Workbook columns:"
    )

    for column in data.columns:

        print(
            f"- {column}"
        )

    return data


# ==================================================
# FIND COLUMN
# ==================================================

def find_column(
    data,
    candidates,
    description,
):

    normalized_columns = {
        normalize_text(column):
            column

        for column in data.columns
    }

    # Exact match first.

    for candidate in candidates:

        normalized_candidate = (
            normalize_text(
                candidate
            )
        )

        if (
            normalized_candidate
            in normalized_columns
        ):

            return normalized_columns[
                normalized_candidate
            ]

    # Partial match second.

    for candidate in candidates:

        normalized_candidate = (
            normalize_text(
                candidate
            )
        )

        for (
            normalized_column,
            original_column,
        ) in normalized_columns.items():

            if (
                normalized_candidate
                and
                normalized_candidate
                in normalized_column
            ):

                return original_column

    raise RuntimeError(
        f"Could not identify {description}.\n\n"
        f"Expected one of:\n"
        f"{candidates}\n\n"
        f"Available columns:\n"
        f"{list(data.columns)}"
    )


# ==================================================
# STANDARDIZE AUGUST INPUTS
# ==================================================

def standardize_august_data(
    data,
):

    country_column = find_column(
        data,
        [
            "Country",
        ],
        "country column",
    )

    iso3_column = find_column(
        data,
        [
            "ISO3 Country Code",
        ],
        "ISO3 column",
    )

    hdx_column = find_column(
        data,
        [
            "HDX IPC Aug 2026",
        ],
        "HDX IPC column",
    )

    fewsnet_column = find_column(
        data,
        [
            (
                "FEWSNet Food Assistance "
                "Outlook Brief (Jul 26)"
            ),
            (
                "FEWSNet Food Assistance "
                "Outlook Brief"
            ),
        ],
        "FEWS NET column",
    )

    grfc_column = find_column(
        data,
        [
            (
                "Global Report on Food "
                "Crises 2025 (0-5)"
            ),
            (
                "Global Report on Food Crises 2025"
            ),
        ],
        "GRFC column",
    )

    workbook_ipc_column = find_column(
        data,
        [
            "IPC Classification",
        ],
        (
            "workbook IPC "
            "Classification column"
        ),
    )

    # ----------------------------------------------
    # IMPORTANT:
    #
    # March 2026 contains the numeric FAO score.
    #
    # April 2026 contains qualitative FAO status
    # information and must not be used as the
    # numeric Food Security input.
    # ----------------------------------------------

    fao_column = find_column(
        data,
        [
            (
                "FAO Crop Prospects and "
                "Food Situation (Mar 2026)"
            ),
        ],
        "March 2026 numeric FAO score column",
    )

    asap_column = find_column(
        data,
        [
            (
                "ASAP Hostpot "
                "July 2026 (0-2)"
            ),
            (
                "ASAP Hotspot "
                "July 2026 (0-2)"
            ),
        ],
        "July 2026 ASAP column",
    )

    sofi_column = find_column(
        data,
        [
            (
                "State of Food Insecurity Report - "
                "Prevalence of moderate or severe "
                "food insecurity 2025 (0-100)"
            ),
            (
                "Prevalence of moderate or severe "
                "food insecurity 2025"
            ),
        ],
        "SOFI column",
    )

    food_security_column = find_column(
        data,
        [
            "CERF Food Insecurity",
        ],
        "CERF Food Insecurity column",
    )

    print()
    print(
        "August Food Security columns selected:"
    )

    selected = {
        "Country":
            country_column,

        "ISO3":
            iso3_column,

        "HDX IPC":
            hdx_column,

        "FEWS NET":
            fewsnet_column,

        "GRFC":
            grfc_column,

        "IPC Classification":
            workbook_ipc_column,

        "FAO":
            fao_column,

        "ASAP":
            asap_column,

        "SOFI":
            sofi_column,

        "CERF Food Insecurity":
            food_security_column,
    }

    for key, value in selected.items():

        print(
            f"{key}: {value}"
        )

    august = pd.DataFrame(
        {
            "Country":
                data[
                    country_column
                ],

            "ISO3":
                data[
                    iso3_column
                ],

            "August_HDX_IPC":
                data[
                    hdx_column
                ].apply(
                    parse_numeric
                ),

            "August_FEWSNET":
                data[
                    fewsnet_column
                ].apply(
                    parse_numeric
                ),

            "August_GRFC":
                data[
                    grfc_column
                ].apply(
                    parse_numeric
                ),

            "Workbook_IPC_Classification":
                data[
                    workbook_ipc_column
                ].apply(
                    parse_numeric
                ),

            "August_FAO":
                data[
                    fao_column
                ].apply(
                    parse_numeric
                ),

            "August_ASAP":
                data[
                    asap_column
                ].apply(
                    parse_numeric
                ),

            "August_SOFI":
                data[
                    sofi_column
                ].apply(
                    parse_numeric
                ),

            "Workbook_CERF_Food_Insecurity":
                data[
                    food_security_column
                ].apply(
                    parse_numeric
                ),
        }
    )

    august["Country"] = (
        august[
            "Country"
        ]
        .astype(str)
        .str.strip()
    )

    august["ISO3"] = (
        august[
            "ISO3"
        ]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # ----------------------------------------------
    # Keep actual country rows only.
    # ----------------------------------------------

    august = august[
        august[
            "ISO3"
        ]
        .str.fullmatch(
            r"[A-Z]{3}",
            na=False,
        )
    ].copy()

    duplicates = august[
        august.duplicated(
            subset=["ISO3"],
            keep=False,
        )
    ]

    if not duplicates.empty:

        print()
        print(
            "Duplicate country rows:"
        )

        print(
            duplicates[
                [
                    "Country",
                    "ISO3",
                ]
            ]
            .to_string(
                index=False
            )
        )

    august = (
        august
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .reset_index(
            drop=True
        )
    )

    print()
    print(
        f"August countries retained: "
        f"{len(august)}"
    )

    return august


# ==================================================
# CALCULATE AUGUST IPC
# ==================================================

def calculate_august_ipc(
    row,
):

    iso3 = row[
        "ISO3"
    ]

    hdx = row[
        "August_HDX_IPC"
    ]

    fewsnet = row[
        "August_FEWSNET"
    ]

    grfc = row[
        "August_GRFC"
    ]

    # ----------------------------------------------
    # Workbook IPC priority:
    #
    # HDX
    # FEWS NET
    # GRFC
    # ----------------------------------------------

    if ipc_available(
        hdx
    ):

        selected = float(
            hdx
        )

        source = (
            "HDX IPC"
        )

    elif ipc_available(
        fewsnet
    ):

        selected = float(
            fewsnet
        )

        source = (
            "FEWS NET"
        )

    elif ipc_available(
        grfc
    ):

        selected = float(
            grfc
        )

        source = (
            "GRFC"
        )

    else:

        selected = None
        source = None

    override = IPC_OVERRIDES.get(
        iso3
    )

    if override is not None:

        selected = float(
            override["score"]
        )

        source = (
            "CERF manual override"
        )

        override_reason = (
            override[
                "reason"
            ]
        )

    else:

        override_reason = None

    return pd.Series(
        {
            "Python_IPC_Classification":
                selected,

            "Python_IPC_Source":
                source,

            "Python_IPC_Override_Reason":
                override_reason,
        }
    )


# ==================================================
# IPC PARITY
# ==================================================

def calculate_ipc_parity(
    row,
):

    workbook_value = row[
        "Workbook_IPC_Classification"
    ]

    python_value = row[
        "Python_IPC_Classification"
    ]

    workbook_has_value = (
        ipc_available(
            workbook_value
        )
    )

    python_has_value = (
        ipc_available(
            python_value
        )
    )

    if (
        not workbook_has_value
        and
        not python_has_value
    ):

        difference = 0.0
        status = "MATCH"

    elif (
        workbook_has_value
        !=
        python_has_value
    ):

        difference = None
        status = "MISMATCH"

    else:

        difference = (
            float(
                python_value
            )
            -
            float(
                workbook_value
            )
        )

        if (
            abs(
                difference
            )
            <= PARITY_TOLERANCE
        ):

            status = "MATCH"

        else:

            status = "MISMATCH"

    return pd.Series(
        {
            "IPC_Difference":
                difference,

            "IPC_Parity_Status":
                status,
        }
    )


# ==================================================
# CALCULATE AUGUST FAO / ASAP BLOCK
# ==================================================

def calculate_august_shock_block(
    row,
):

    fao = row[
        "August_FAO"
    ]

    asap = row[
        "August_ASAP"
    ]

    # ----------------------------------------------
    # The August workbook excludes zero values from
    # weighting.
    #
    # Therefore:
    #
    # 1 or 2 = available
    # 0 = unavailable
    # blank = unavailable
    # ----------------------------------------------

    fao_is_available = (
        shock_available(
            fao
        )
    )

    asap_is_available = (
        shock_available(
            asap
        )
    )

    if fao_is_available:

        fao_100 = (
            float(
                fao
            )
            * 50.0
        )

    else:

        fao_100 = None

    if asap_is_available:

        asap_100 = (
            float(
                asap
            )
            * 50.0
        )

    else:

        asap_100 = None

    if (
        fao_is_available
        and
        asap_is_available
    ):

        shock_score = (
            fao_100
            +
            asap_100
        ) / 2.0

        method = (
            "FAO and ASAP split block equally"
        )

    elif fao_is_available:

        shock_score = (
            fao_100
        )

        method = (
            "FAO takes full shock block"
        )

    elif asap_is_available:

        shock_score = (
            asap_100
        )

        method = (
            "ASAP takes full shock block"
        )

    else:

        shock_score = None

        method = (
            "Shock block unavailable"
        )

    return pd.Series(
        {
            "August_FAO_Available":
                fao_is_available,

            "August_ASAP_Available":
                asap_is_available,

            "August_FAO_Score_100":
                fao_100,

            "August_ASAP_Score_100":
                asap_100,

            "August_Shock_Block":
                shock_score,

            "August_Shock_Method":
                method,
        }
    )


# ==================================================
# CALCULATE AUGUST FOOD SECURITY
# ==================================================

def calculate_august_food_security(
    row,
):

    ipc = row[
        "Python_IPC_Classification"
    ]

    shock_score = row[
        "August_Shock_Block"
    ]

    sofi = row[
        "August_SOFI"
    ]

    ipc_is_available = (
        ipc_available(
            ipc
        )
    )

    shock_is_available = (
        row[
            "August_FAO_Available"
        ]
        or
        row[
            "August_ASAP_Available"
        ]
    )

    sofi_is_available = (
        sofi_available(
            sofi
        )
    )

    numerator = 0.0
    denominator = 0.0

    # ----------------------------------------------
    # IPC block = 60%
    # ----------------------------------------------

    if ipc_is_available:

        ipc_100 = (
            float(
                ipc
            )
            * 20.0
        )

        numerator += (
            ipc_100
            * IPC_BASE_WEIGHT
        )

        denominator += (
            IPC_BASE_WEIGHT
        )

    else:

        ipc_100 = None

    # ----------------------------------------------
    # FAO / ASAP block = 20%
    # ----------------------------------------------

    if shock_is_available:

        numerator += (
            float(
                shock_score
            )
            * SHOCK_BASE_WEIGHT
        )

        denominator += (
            SHOCK_BASE_WEIGHT
        )

    # ----------------------------------------------
    # SOFI block = 20%
    # ----------------------------------------------

    if sofi_is_available:

        numerator += (
            float(
                sofi
            )
            * SOFI_BASE_WEIGHT
        )

        denominator += (
            SOFI_BASE_WEIGHT
        )

    # ----------------------------------------------
    # Exclude unavailable blocks and renormalize.
    #
    # When NO food-security block is available,
    # the historical workbook returns zero.
    # ----------------------------------------------

    if denominator > 0:

        score = (
            numerator
            /
            denominator
        )

    else:

        score = 0.0

    return pd.Series(
        {
            "August_IPC_Score_100":
                ipc_100,

            "August_SOFI_Available":
                sofi_is_available,

            "August_Available_Base_Weight":
                denominator,

            "Python_CERF_Food_Insecurity":
                score,
        }
    )


# ==================================================
# FOOD SECURITY PARITY
# ==================================================

def calculate_food_security_parity(
    row,
):

    workbook_score = parse_numeric(
        row[
            "Workbook_CERF_Food_Insecurity"
        ]
    )

    python_score = parse_numeric(
        row[
            "Python_CERF_Food_Insecurity"
        ]
    )

    if (
        workbook_score is None
        and
        python_score is None
    ):

        difference = 0.0
        absolute_difference = 0.0
        status = "MATCH"

    elif (
        workbook_score is None
        or
        python_score is None
    ):

        difference = None
        absolute_difference = None
        status = "MISMATCH"

    else:

        difference = (
            python_score
            -
            workbook_score
        )

        absolute_difference = abs(
            difference
        )

        if (
            absolute_difference
            <= PARITY_TOLERANCE
        ):

            status = "MATCH"

        else:

            status = "MISMATCH"

    return pd.Series(
        {
            "Food_Security_Difference":
                difference,

            "Food_Security_Absolute_Difference":
                absolute_difference,

            "Food_Security_Parity_Status":
                status,
        }
    )


# ==================================================
# RUN PARITY
# ==================================================

def run_parity():

    workbook = find_workbook()

    raw = read_august_data(
        workbook
    )

    results = standardize_august_data(
        raw
    )

    # ----------------------------------------------
    # IPC
    # ----------------------------------------------

    ipc_results = results.apply(
        calculate_august_ipc,
        axis=1,
    )

    results = pd.concat(
        [
            results,
            ipc_results,
        ],
        axis=1,
    )

    ipc_parity = results.apply(
        calculate_ipc_parity,
        axis=1,
    )

    results = pd.concat(
        [
            results,
            ipc_parity,
        ],
        axis=1,
    )

    # ----------------------------------------------
    # FAO / ASAP
    # ----------------------------------------------

    shock_results = results.apply(
        calculate_august_shock_block,
        axis=1,
    )

    results = pd.concat(
        [
            results,
            shock_results,
        ],
        axis=1,
    )

    # ----------------------------------------------
    # Food Security
    # ----------------------------------------------

    food_results = results.apply(
        calculate_august_food_security,
        axis=1,
    )

    results = pd.concat(
        [
            results,
            food_results,
        ],
        axis=1,
    )

    # ----------------------------------------------
    # Parity
    # ----------------------------------------------

    parity_results = results.apply(
        calculate_food_security_parity,
        axis=1,
    )

    results = pd.concat(
        [
            results,
            parity_results,
        ],
        axis=1,
    )

    results.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig",
    )

    return results


# ==================================================
# PRINT REFERENCE COUNTRIES
# ==================================================

def print_reference_countries(
    results,
):

    reference_iso3 = [
        "AFG",
        "BGD",
        "CMR",
        "CAF",
        "TCD",
        "COD",
        "HTI",
        "MLI",
        "NGA",
        "SSD",
        "YEM",
        "ZWE",
    ]

    reference = results[
        results[
            "ISO3"
        ].isin(
            reference_iso3
        )
    ].copy()

    reference = (
        reference
        .sort_values(
            "Country"
        )
    )

    print()
    print(
        "Reference countries:"
    )

    print()

    print(
        reference[
            [
                "Country",
                "ISO3",

                "August_HDX_IPC",
                "August_FEWSNET",
                "August_GRFC",

                "Workbook_IPC_Classification",
                "Python_IPC_Classification",
                "Python_IPC_Source",
                "IPC_Parity_Status",

                "August_FAO",
                "August_ASAP",
                "August_SOFI",

                "August_Shock_Block",
                "August_Available_Base_Weight",

                "Workbook_CERF_Food_Insecurity",
                "Python_CERF_Food_Insecurity",

                "Food_Security_Difference",
                "Food_Security_Parity_Status",
            ]
        ]
        .to_string(
            index=False
        )
    )


# ==================================================
# MAIN
# ==================================================

if __name__ == "__main__":

    results = run_parity()

    print()
    print("=" * 70)

    print(
        "AUGUST FOOD SECURITY PARITY TEST"
    )

    print("=" * 70)

    print()
    print(
        "IPC parity:"
    )

    print(
        results[
            "IPC_Parity_Status"
        ]
        .value_counts(
            dropna=False
        )
        .to_string()
    )

    print()
    print(
        "Food Security parity:"
    )

    print(
        results[
            "Food_Security_Parity_Status"
        ]
        .value_counts(
            dropna=False
        )
        .to_string()
    )

    print_reference_countries(
        results
    )

    # ----------------------------------------------
    # IPC mismatches
    # ----------------------------------------------

    ipc_mismatches = results[
        results[
            "IPC_Parity_Status"
        ].eq(
            "MISMATCH"
        )
    ].copy()

    print()
    print(
        f"IPC mismatches: "
        f"{len(ipc_mismatches)}"
    )

    if not ipc_mismatches.empty:

        print()

        print(
            ipc_mismatches[
                [
                    "Country",
                    "ISO3",

                    "August_HDX_IPC",
                    "August_FEWSNET",
                    "August_GRFC",

                    "Workbook_IPC_Classification",
                    "Python_IPC_Classification",
                    "Python_IPC_Source",

                    "IPC_Difference",
                ]
            ]
            .head(50)
            .to_string(
                index=False
            )
        )

    # ----------------------------------------------
    # Food Security mismatches
    # ----------------------------------------------

    mismatches = results[
        results[
            "Food_Security_Parity_Status"
        ].eq(
            "MISMATCH"
        )
    ].copy()

    mismatches = (
        mismatches
        .sort_values(
            "Food_Security_Absolute_Difference",
            ascending=False,
            na_position="last",
        )
    )

    print()
    print(
        f"Food Security mismatches: "
        f"{len(mismatches)}"
    )

    if not mismatches.empty:

        print()

        print(
            mismatches[
                [
                    "Country",
                    "ISO3",

                    "August_HDX_IPC",
                    "August_FEWSNET",
                    "August_GRFC",

                    "Workbook_IPC_Classification",
                    "Python_IPC_Classification",

                    "August_FAO",
                    "August_ASAP",
                    "August_SOFI",

                    "August_Shock_Block",
                    "August_Available_Base_Weight",

                    "Workbook_CERF_Food_Insecurity",
                    "Python_CERF_Food_Insecurity",

                    "Food_Security_Difference",
                ]
            ]
            .head(50)
            .to_string(
                index=False
            )
        )

    # ----------------------------------------------
    # Maximum absolute difference
    # ----------------------------------------------

    comparable = results[
        results[
            "Food_Security_Absolute_Difference"
        ].notna()
    ]

    print()
    print(
        "Maximum absolute Food Security difference:"
    )

    if comparable.empty:

        print(
            "No comparable rows."
        )

    else:

        print(
            comparable[
                "Food_Security_Absolute_Difference"
            ].max()
        )

    print()
    print(
        f"Parity report saved to:\n"
        f"{output_file}"
    )