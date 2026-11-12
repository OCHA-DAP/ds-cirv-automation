from pathlib import Path
import json
import math
import re

import pandas as pd


# ==================================================
# SETTINGS
# ==================================================

IPC_BASE_WEIGHT = 0.60
SHOCK_BASE_WEIGHT = 0.20
SOFI_BASE_WEIGHT = 0.20

FAO_SHARE_WHEN_BOTH = 0.50
ASAP_SHARE_WHEN_BOTH = 0.50

EXPECTED_COUNTRY_COUNT = 150
MINIMUM_SCORE = 0.0
MAXIMUM_SCORE = 100.0


# ==================================================
# MANUAL IPC OVERRIDES
# ==================================================

IPC_OVERRIDES = {
    "YEM": {
        "score": 5.0,
        "reason": (
            "CERF manual adjustment reflecting the "
            "likely prevalence of IPC Phase 5 in "
            "DFA-controlled areas where current IPC "
            "analysis was unavailable."
        ),
    },
}


# ==================================================
# PROJECT FILES
# ==================================================

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

mapping_file = (
    project_folder
    / "config"
    / "countries.csv"
)

current_output = (
    project_folder
    / "food_security_current.csv"
)

evidence_output = (
    processed_folder
    / "food_security_evidence.csv"
)

metadata_output = (
    processed_folder
    / "food_security_metadata.json"
)

missingness_output = (
    processed_folder
    / "food_security_missingness.csv"
)

validation_output = (
    processed_folder
    / "food_security_validation.csv"
)


# ==================================================
# COLLECTOR OUTPUT CONFIGURATION
# ==================================================

SOURCE_CONFIG = {
    "ipc": {
        "file":
            "hdx_ipc_update_comparison.csv",

        "value_columns": [
            "New_HDX_IPC",
        ],

        "country_columns": [
            "Country",
            "HDX_Country",
        ],
    },

    "fewsnet": {
        "file":
            "fewsnet_faob_current.csv",

        "value_columns": [
            "FEWSNET_IPC",
            "FEWSNET_Phase",
            "FEWSNET_Classification",
            "FEWSNET",
            "FAOB_Phase",
            "FAOB_Score",
            "IPC_Phase",
            "Phase",
            "Score",
        ],

        "country_columns": [
            "CERF_Country",
            "Country",
            "FEWSNET_Country",
            "Source_Country",
        ],
    },

    "grfc": {
        "file":
            "grfc_current.csv",

        "value_columns": [
            "GRFC_Phase",
        ],

        "country_columns": [
            "CERF_Country",
            "GRFC_Country",
        ],
    },

    "fao": {
        "file":
            "fao_crop_prospects_current.csv",

        "value_columns": [
            "FAO_Score",
            "FAO_Crop_Prospects",
            "FAO_Crop_Prospects_Score",
            "Crop_Prospects_Score",
            "Current_Score",
            "Score",
        ],

        "country_columns": [
            "CERF_Country",
            "Country",
            "FAO_Country",
            "Source_Country",
        ],
    },

    "asap": {
        "file":
            "asap_hotspots_current.csv",

        "value_columns": [
            "ASAP_Hotspot",
        ],

        "country_columns": [
            "CERF_Country",
            "Source_Country",
        ],
    },

    "sofi": {
        "file":
            "sofi_current.csv",

        "value_columns": [
            "SOFI_Score",
        ],

        "country_columns": [
            "CERF_Country",
            "FAOSTAT_Area",
        ],
    },
}


ISO3_COLUMNS = [
    "ISO3",
    "iso3",
    "ISO",
    "Iso3",
    "ISO_Code",
]


# ==================================================
# BASIC UTILITIES
# ==================================================

def is_missing(value):

    if value is None:
        return True

    try:

        if pd.isna(value):
            return True

    except TypeError:

        pass

    text = str(value).strip().lower()

    return text in {
        "",
        "nan",
        "none",
        "null",
        "na",
        "n/a",
        "<na>",
    }


def parse_numeric(value):

    if is_missing(value):
        return None

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


def normalize_iso3(value):

    if is_missing(value):
        return None

    text = (
        str(value)
        .strip()
        .upper()
    )

    if (
        len(text) != 3
        or
        not text.isalpha()
    ):

        return None

    return text


# ==================================================
# SOURCE AVAILABILITY RULES
# ==================================================

def ipc_value_available(value):
    """
    IPC, FEWS NET, and GRFC:

    1-5 = available.
    0, blank, or NaN = unavailable.
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


def shock_value_available(value):
    """
    FAO and ASAP weighting rule:

    1 or 2 = available.
    0, blank, or NaN = excluded from weighting.

    Source collectors may preserve zero as an
    assessed observation, but the validated CERF
    formula excludes zero from the weighted score.
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


def sofi_value_available(value):
    """
    SOFI weighting rule:

    Positive values up to 100 = available.
    0, blank, or NaN = unavailable.
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
# COLUMN DETECTION
# ==================================================

def find_column(
    data,
    candidates,
    description,
):

    lookup = {
        str(column).strip().lower():
            column

        for column in data.columns
    }

    for candidate in candidates:

        match = lookup.get(
            candidate.strip().lower()
        )

        if match is not None:
            return match

    raise RuntimeError(
        f"Could not identify {description}.\n\n"
        f"Expected one of:\n"
        f"{candidates}\n\n"
        f"Available columns:\n"
        f"{list(data.columns)}"
    )


def find_optional_column(
    data,
    candidates,
):

    lookup = {
        str(column).strip().lower():
            column

        for column in data.columns
    }

    for candidate in candidates:

        match = lookup.get(
            candidate.strip().lower()
        )

        if match is not None:
            return match

    return None


# ==================================================
# LOAD CERF COUNTRY UNIVERSE
# ==================================================

def load_country_universe():

    if not mapping_file.exists():

        raise FileNotFoundError(
            "CERF country mapping not found:\n"
            f"{mapping_file}"
        )

    mapping = pd.read_csv(
        mapping_file,
        encoding="utf-8-sig",
    )

    required_columns = [
        "ISO3",
        "CERF_Country",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in mapping.columns
    ]

    if missing_columns:

        raise RuntimeError(
            "Country mapping is missing columns:\n"
            f"{missing_columns}"
        )

    countries = mapping[
        [
            "ISO3",
            "CERF_Country",
        ]
    ].copy()

    countries["ISO3"] = (
        countries["ISO3"]
        .apply(normalize_iso3)
    )

    countries = (
        countries[
            countries["ISO3"].notna()
        ]
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

    if countries.empty:

        raise RuntimeError(
            "No CERF countries were loaded "
            "from config/countries.csv."
        )

    print()
    print(
        f"CERF country universe: "
        f"{len(countries)}"
    )

    return countries


# ==================================================
# READ COLLECTOR OUTPUT
# ==================================================

def read_source(source_name):

    config = SOURCE_CONFIG[
        source_name
    ]

    file_path = (
        project_folder
        / config["file"]
    )

    if not file_path.exists():

        raise FileNotFoundError(
            f"Required {source_name.upper()} "
            f"output not found:\n"
            f"{file_path}"
        )

    print()
    print(
        f"Reading {source_name.upper()}:"
    )

    print(
        file_path
    )

    data = pd.read_csv(
        file_path,
        encoding="utf-8-sig",
        low_memory=False,
    )

    if data.empty:

        raise RuntimeError(
            f"{file_path.name} is empty."
        )

    iso3_column = find_column(
        data,
        ISO3_COLUMNS,
        f"{source_name} ISO3 column",
    )

    value_column = find_column(
        data,
        config["value_columns"],
        f"{source_name} value column",
    )

    country_column = find_optional_column(
        data,
        config["country_columns"],
    )

    standardized = pd.DataFrame(
        {
            "ISO3":
                data[
                    iso3_column
                ]
                .apply(normalize_iso3),

            f"{source_name}_raw":
                data[
                    value_column
                ],

            f"{source_name}_value":
                data[
                    value_column
                ]
                .apply(parse_numeric),

            f"{source_name}_row_present":
                True,
        }
    )

    if country_column is not None:

        standardized[
            f"{source_name}_country"
        ] = data[
            country_column
        ]

    else:

        standardized[
            f"{source_name}_country"
        ] = pd.NA

    standardized[
        f"{source_name}_file"
    ] = file_path.name

    standardized = standardized[
        standardized["ISO3"].notna()
    ].copy()

    duplicates = standardized[
        standardized.duplicated(
            subset=["ISO3"],
            keep=False,
        )
    ]

    if not duplicates.empty:

        print()
        print(
            f"Duplicate {source_name.upper()} "
            f"ISO3 records detected:"
        )

        print(
            duplicates[
                [
                    "ISO3",
                    f"{source_name}_value",
                ]
            ]
            .sort_values("ISO3")
            .to_string(index=False)
        )

    standardized = (
        standardized
        .sort_values("ISO3")
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .reset_index(drop=True)
    )

    print(
        f"Rows retained: "
        f"{len(standardized)}"
    )

    print(
        f"Value column: "
        f"{value_column}"
    )

    return standardized


# ==================================================
# MERGE SOURCES
# ==================================================

def merge_sources(
    country_universe,
    source_frames,
):

    merged = (
        country_universe.copy()
    )

    for source_name, frame in (
        source_frames.items()
    ):

        merged = merged.merge(
            frame,
            on="ISO3",
            how="left",
            validate="one_to_one",
        )

    row_present_columns = [
        column
        for column in merged.columns
        if column.endswith(
            "_row_present"
        )
    ]

    for column in row_present_columns:

        merged[column] = (
            merged[column]
            .fillna(False)
            .astype(bool)
        )

    return merged


# ==================================================
# IPC PRIORITY
# ==================================================

def select_ipc_classification(row):
    """
    Validated workbook priority:

    1. HDX IPC
    2. FEWS NET
    3. GRFC

    This is source priority, not maximum severity.
    """

    iso3 = row["ISO3"]

    hdx_ipc = row.get(
        "ipc_value"
    )

    fewsnet = row.get(
        "fewsnet_value"
    )

    grfc = row.get(
        "grfc_value"
    )

    if ipc_value_available(
        hdx_ipc
    ):

        selected_value = float(
            hdx_ipc
        )

        selected_source = (
            "HDX IPC"
        )

    elif ipc_value_available(
        fewsnet
    ):

        selected_value = float(
            fewsnet
        )

        selected_source = (
            "FEWS NET"
        )

    elif ipc_value_available(
        grfc
    ):

        selected_value = float(
            grfc
        )

        selected_source = (
            "GRFC"
        )

    else:

        selected_value = None
        selected_source = None

    override = IPC_OVERRIDES.get(
        iso3
    )

    if override is not None:

        selected_value = float(
            override["score"]
        )

        selected_source = (
            "CERF manual override"
        )

        override_reason = (
            override["reason"]
        )

    else:

        override_reason = None

    return pd.Series(
        {
            "IPC_Classification":
                selected_value,

            "IPC_Classification_Source":
                selected_source,

            "IPC_Override_Reason":
                override_reason,

            "HDX_IPC_Available":
                ipc_value_available(
                    hdx_ipc
                ),

            "FEWSNET_Available":
                ipc_value_available(
                    fewsnet
                ),

            "GRFC_Available":
                ipc_value_available(
                    grfc
                ),
        }
    )


# ==================================================
# FAO / ASAP SHOCK BLOCK
# ==================================================

def calculate_shock_block(row):
    """
    Validated FAO/ASAP block logic.

    Total base weight = 20%.

    Both positive:
        50% FAO and 50% ASAP inside the block.

    FAO only:
        FAO receives the full block.

    ASAP only:
        ASAP receives the full block.

    Zero remains visible in source evidence but is
    excluded from weighting.
    """

    fao_value = row.get(
        "fao_value"
    )

    asap_value = row.get(
        "asap_value"
    )

    fao_row_present = bool(
        row.get(
            "fao_row_present",
            False,
        )
    )

    asap_row_present = bool(
        row.get(
            "asap_row_present",
            False,
        )
    )

    fao_available = (
        fao_row_present
        and
        shock_value_available(
            fao_value
        )
    )

    asap_available = (
        asap_row_present
        and
        shock_value_available(
            asap_value
        )
    )

    if fao_available:

        fao_score_100 = (
            float(fao_value)
            * 50.0
        )

    else:

        fao_score_100 = None

    if asap_available:

        asap_score_100 = (
            float(asap_value)
            * 50.0
        )

    else:

        asap_score_100 = None

    if (
        fao_available
        and
        asap_available
    ):

        shock_score_100 = (
            fao_score_100
            * FAO_SHARE_WHEN_BOTH
            +
            asap_score_100
            * ASAP_SHARE_WHEN_BOTH
        )

        method = (
            "FAO and ASAP share shock block equally"
        )

        fao_internal_share = 0.50
        asap_internal_share = 0.50

    elif fao_available:

        shock_score_100 = (
            fao_score_100
        )

        method = (
            "FAO receives full shock-block weight"
        )

        fao_internal_share = 1.0
        asap_internal_share = 0.0

    elif asap_available:

        shock_score_100 = (
            asap_score_100
        )

        method = (
            "ASAP receives full shock-block weight"
        )

        fao_internal_share = 0.0
        asap_internal_share = 1.0

    else:

        shock_score_100 = None

        method = (
            "FAO and ASAP unavailable for weighting"
        )

        fao_internal_share = 0.0
        asap_internal_share = 0.0

    return pd.Series(
        {
            "FAO_Row_Present":
                fao_row_present,

            "ASAP_Row_Present":
                asap_row_present,

            "FAO_Available":
                fao_available,

            "ASAP_Available":
                asap_available,

            "FAO_Score_100":
                fao_score_100,

            "ASAP_Score_100":
                asap_score_100,

            "Shock_Block_Available":
                (
                    fao_available
                    or
                    asap_available
                ),

            "Shock_Block_Score_100":
                shock_score_100,

            "Shock_Block_Method":
                method,

            "FAO_Internal_Shock_Share":
                fao_internal_share,

            "ASAP_Internal_Shock_Share":
                asap_internal_share,
        }
    )


# ==================================================
# CONSOLIDATED FOOD SECURITY SCORE
# ==================================================

def calculate_consolidated_score(row):
    """
    Validated CERF Food Security calculation.

    Base weights:
        IPC classification = 60%
        FAO/ASAP block      = 20%
        SOFI                = 20%

    Unavailable blocks are excluded.
    Remaining block weights are renormalized.

    No usable evidence = score 0.
    """

    ipc_classification = row.get(
        "IPC_Classification"
    )

    shock_score = row.get(
        "Shock_Block_Score_100"
    )

    sofi_score = row.get(
        "sofi_value"
    )

    ipc_available = (
        ipc_value_available(
            ipc_classification
        )
    )

    shock_available = bool(
        row.get(
            "Shock_Block_Available",
            False,
        )
    )

    sofi_row_present = bool(
        row.get(
            "sofi_row_present",
            False,
        )
    )

    sofi_available_flag = (
        sofi_row_present
        and
        sofi_value_available(
            sofi_score
        )
    )

    if ipc_available:

        ipc_score_100 = (
            float(
                ipc_classification
            )
            * 20.0
        )

    else:

        ipc_score_100 = None

    if sofi_available_flag:

        sofi_score_100 = float(
            sofi_score
        )

    else:

        sofi_score_100 = None

    numerator = 0.0
    denominator = 0.0

    if ipc_available:

        numerator += (
            ipc_score_100
            * IPC_BASE_WEIGHT
        )

        denominator += (
            IPC_BASE_WEIGHT
        )

    if shock_available:

        numerator += (
            float(shock_score)
            * SHOCK_BASE_WEIGHT
        )

        denominator += (
            SHOCK_BASE_WEIGHT
        )

    if sofi_available_flag:

        numerator += (
            sofi_score_100
            * SOFI_BASE_WEIGHT
        )

        denominator += (
            SOFI_BASE_WEIGHT
        )

    if denominator > 0:

        consolidated_score = (
            numerator
            / denominator
        )

        effective_ipc_weight = (
            IPC_BASE_WEIGHT
            / denominator
            if ipc_available
            else 0.0
        )

        effective_shock_weight = (
            SHOCK_BASE_WEIGHT
            / denominator
            if shock_available
            else 0.0
        )

        effective_sofi_weight = (
            SOFI_BASE_WEIGHT
            / denominator
            if sofi_available_flag
            else 0.0
        )

    else:

        consolidated_score = 0.0

        effective_ipc_weight = 0.0
        effective_shock_weight = 0.0
        effective_sofi_weight = 0.0

    available_blocks = []
    missing_blocks = []

    if ipc_available:

        available_blocks.append(
            "IPC"
        )

    else:

        missing_blocks.append(
            "IPC"
        )

    if shock_available:

        available_blocks.append(
            "FAO/ASAP"
        )

    else:

        missing_blocks.append(
            "FAO/ASAP"
        )

    if sofi_available_flag:

        available_blocks.append(
            "SOFI"
        )

    else:

        missing_blocks.append(
            "SOFI"
        )

    return pd.Series(
        {
            "IPC_Block_Available":
                ipc_available,

            "SOFI_Available":
                sofi_available_flag,

            "IPC_Score_100":
                ipc_score_100,

            "SOFI_Score_100":
                sofi_score_100,

            "IPC_Base_Weight":
                (
                    IPC_BASE_WEIGHT
                    if ipc_available
                    else 0.0
                ),

            "Shock_Base_Weight":
                (
                    SHOCK_BASE_WEIGHT
                    if shock_available
                    else 0.0
                ),

            "SOFI_Base_Weight":
                (
                    SOFI_BASE_WEIGHT
                    if sofi_available_flag
                    else 0.0
                ),

            "Available_Base_Weight":
                denominator,

            "Available_Block_Count":
                len(
                    available_blocks
                ),

            "Effective_IPC_Weight":
                effective_ipc_weight,

            "Effective_Shock_Weight":
                effective_shock_weight,

            "Effective_SOFI_Weight":
                effective_sofi_weight,

            "Available_Blocks":
                ", ".join(
                    available_blocks
                ),

            "Missing_Blocks":
                ", ".join(
                    missing_blocks
                ),

            "CERF_Food_Insecurity":
                consolidated_score,
        }
    )


# ==================================================
# SOURCE RANGE VALIDATION
# ==================================================

def validate_source_ranges(data):

    range_rules = {
        "ipc_value":
            (
                0,
                5,
            ),

        "fewsnet_value":
            (
                0,
                5,
            ),

        "grfc_value":
            (
                0,
                5,
            ),

        "fao_value":
            (
                0,
                2,
            ),

        "asap_value":
            (
                0,
                2,
            ),

        "sofi_value":
            (
                0,
                100,
            ),
    }

    problems = []

    for column, limits in (
        range_rules.items()
    ):

        numeric = pd.to_numeric(
            data[column],
            errors="coerce",
        )

        invalid = data[
            numeric.notna()
            &
            ~numeric.between(
                limits[0],
                limits[1],
            )
        ]

        if not invalid.empty:

            problems.append(
                (
                    f"{column} contains "
                    f"{len(invalid)} values outside "
                    f"{limits[0]}-{limits[1]}."
                )
            )

    if problems:

        print()
        print(
            "SOURCE RANGE VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "Food Security source ranges "
            "failed validation."
        )


# ==================================================
# RESULT VALIDATION
# ==================================================

def validate_results(results):

    problems = []

    if (
        len(results)
        != EXPECTED_COUNTRY_COUNT
    ):

        problems.append(
            (
                f"Country count is {len(results)}, "
                f"expected {EXPECTED_COUNTRY_COUNT}."
            )
        )

    if results[
        "ISO3"
    ].duplicated().any():

        problems.append(
            "Duplicate ISO3 records detected."
        )

    invalid_scores = results[
        ~results[
            "CERF_Food_Insecurity"
        ].between(
            MINIMUM_SCORE,
            MAXIMUM_SCORE,
        )
    ]

    if not invalid_scores.empty:

        problems.append(
            (
                f"{len(invalid_scores)} scores "
                "fall outside 0-100."
            )
        )

    # ----------------------------------------------
    # Countries with usable evidence
    # ----------------------------------------------

    weighted_rows = results[
        results[
            "Available_Base_Weight"
        ].gt(0)
    ].copy()

    weight_total = (
        weighted_rows[
            "Effective_IPC_Weight"
        ]
        +
        weighted_rows[
            "Effective_Shock_Weight"
        ]
        +
        weighted_rows[
            "Effective_SOFI_Weight"
        ]
    )

    invalid_weights = weighted_rows[
        ~weight_total.between(
            0.999999,
            1.000001,
        )
    ]

    if not invalid_weights.empty:

        problems.append(
            (
                f"{len(invalid_weights)} weighted "
                "countries have effective weights "
                "that do not total 1."
            )
        )

    # ----------------------------------------------
    # Countries without usable evidence
    # ----------------------------------------------

    no_evidence_rows = results[
        results[
            "Available_Base_Weight"
        ].eq(0)
    ].copy()

    invalid_no_evidence = no_evidence_rows[
        ~no_evidence_rows[
            "CERF_Food_Insecurity"
        ].eq(0)
    ]

    if not invalid_no_evidence.empty:

        problems.append(
            (
                f"{len(invalid_no_evidence)} "
                "no-evidence countries did not "
                "receive a zero score."
            )
        )

    # ----------------------------------------------
    # Zero must be excluded from weighting
    # ----------------------------------------------

    asap_zero_rows = results[
        results[
            "asap_row_present"
        ]
        &
        results[
            "asap_value"
        ].eq(0)
    ]

    invalid_asap_zero = asap_zero_rows[
        asap_zero_rows[
            "ASAP_Available"
        ]
    ]

    if not invalid_asap_zero.empty:

        problems.append(
            (
                f"{len(invalid_asap_zero)} ASAP "
                "zero observations incorrectly "
                "received Food Security weight."
            )
        )

    fao_zero_rows = results[
        results[
            "fao_row_present"
        ]
        &
        results[
            "fao_value"
        ].eq(0)
    ]

    invalid_fao_zero = fao_zero_rows[
        fao_zero_rows[
            "FAO_Available"
        ]
    ]

    if not invalid_fao_zero.empty:

        problems.append(
            (
                f"{len(invalid_fao_zero)} FAO "
                "zero observations incorrectly "
                "received Food Security weight."
            )
        )

    sofi_zero_rows = results[
        results[
            "sofi_row_present"
        ]
        &
        results[
            "sofi_value"
        ].eq(0)
    ]

    invalid_sofi_zero = sofi_zero_rows[
        sofi_zero_rows[
            "SOFI_Available"
        ]
    ]

    if not invalid_sofi_zero.empty:

        problems.append(
            (
                f"{len(invalid_sofi_zero)} SOFI "
                "zero observations incorrectly "
                "received Food Security weight."
            )
        )

    if problems:

        results.to_csv(
            validation_output,
            index=False,
            encoding="utf-8-sig",
        )

        print()
        print(
            "FOOD SECURITY VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "Food Security results failed "
            "validation. The current output "
            "was not replaced."
        )

    print()
    print(
        "FOOD SECURITY VALIDATION PASSED"
    )

    print(
        f"Countries consolidated: "
        f"{len(results)}"
    )

    print(
        f"Countries with usable evidence: "
        f"{len(weighted_rows)}"
    )

    print(
        f"Countries with no usable evidence: "
        f"{len(no_evidence_rows)}"
    )


# ==================================================
# AFGHANISTAN CHECK
# ==================================================

def print_afghanistan_check(results):

    afghanistan = results[
        results[
            "ISO3"
        ].eq(
            "AFG"
        )
    ]

    if afghanistan.empty:

        print()
        print(
            "Afghanistan was not found."
        )

        return

    row = afghanistan.iloc[0]

    print()
    print(
        "AFGHANISTAN FORMULA CHECK"
    )

    print("-" * 70)

    print(
        f"HDX IPC: "
        f"{row.get('ipc_value')}"
    )

    print(
        f"FEWS NET: "
        f"{row.get('fewsnet_value')}"
    )

    print(
        f"GRFC: "
        f"{row.get('grfc_value')}"
    )

    print(
        f"Selected IPC: "
        f"{row.get('IPC_Classification')}"
    )

    print(
        f"IPC source: "
        f"{row.get('IPC_Classification_Source')}"
    )

    print(
        f"IPC score /100: "
        f"{row.get('IPC_Score_100')}"
    )

    print(
        f"FAO raw: "
        f"{row.get('fao_value')}"
    )

    print(
        f"FAO available: "
        f"{row.get('FAO_Available')}"
    )

    print(
        f"ASAP raw: "
        f"{row.get('asap_value')}"
    )

    print(
        f"ASAP available: "
        f"{row.get('ASAP_Available')}"
    )

    print(
        f"Shock block /100: "
        f"{row.get('Shock_Block_Score_100')}"
    )

    print(
        f"SOFI: "
        f"{row.get('sofi_value')}"
    )

    print(
        f"Available base weight: "
        f"{row.get('Available_Base_Weight')}"
    )

    print(
        f"Food Security score: "
        f"{row.get('CERF_Food_Insecurity')}"
    )


# ==================================================
# SAVE OUTPUTS
# ==================================================

def save_outputs(
    results,
    source_files,
):

    output_columns = [
        "ISO3",
        "CERF_Country",

        "ipc_value",
        "fewsnet_value",
        "grfc_value",

        "IPC_Classification",
        "IPC_Classification_Source",
        "IPC_Override_Reason",
        "IPC_Score_100",

        "fao_value",
        "asap_value",

        "FAO_Available",
        "ASAP_Available",

        "FAO_Score_100",
        "ASAP_Score_100",

        "Shock_Block_Available",
        "Shock_Block_Score_100",
        "Shock_Block_Method",

        "sofi_value",
        "SOFI_Available",
        "SOFI_Score_100",

        "IPC_Base_Weight",
        "Shock_Base_Weight",
        "SOFI_Base_Weight",

        "Available_Base_Weight",
        "Available_Block_Count",

        "Effective_IPC_Weight",
        "Effective_Shock_Weight",
        "Effective_SOFI_Weight",

        "Available_Blocks",
        "Missing_Blocks",

        "CERF_Food_Insecurity",
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

    missingness_columns = [
        "ISO3",
        "CERF_Country",

        "ipc_row_present",
        "fewsnet_row_present",
        "grfc_row_present",
        "fao_row_present",
        "asap_row_present",
        "sofi_row_present",

        "HDX_IPC_Available",
        "FEWSNET_Available",
        "GRFC_Available",
        "FAO_Available",
        "ASAP_Available",
        "SOFI_Available",

        "Available_Block_Count",
        "Available_Blocks",
        "Missing_Blocks",
        "Available_Base_Weight",

        "CERF_Food_Insecurity",
    ]

    missingness = results[
        missingness_columns
    ].copy()

    missingness.to_csv(
        missingness_output,
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "method":
            (
                "CERF Food Security consolidated "
                "score using IPC 60 percent, "
                "FAO/ASAP block 20 percent, and "
                "SOFI 20 percent. Missing blocks "
                "are removed and remaining weights "
                "are renormalized."
            ),

        "historical_parity":
            {
                "workbook":
                    (
                        "260810 CERF UFE 2026-I "
                        "CIRV and Funding Analysis"
                    ),

                "ipc_matches":
                    150,

                "food_security_matches":
                    150,

                "mismatches":
                    0,
            },

        "ipc_priority":
            [
                "HDX IPC",
                "FEWS NET",
                "GRFC",
            ],

        "base_weights":
            {
                "IPC":
                    IPC_BASE_WEIGHT,

                "FAO_ASAP_block":
                    SHOCK_BASE_WEIGHT,

                "SOFI":
                    SOFI_BASE_WEIGHT,
            },

        "availability_rules":
            {
                "IPC_FEWSNET_GRFC":
                    (
                        "Only positive values "
                        "from 1 to 5 receive weight."
                    ),

                "FAO_ASAP":
                    (
                        "Only positive values 1 or 2 "
                        "receive weight. Zero is "
                        "preserved as source evidence "
                        "but excluded from weighting."
                    ),

                "SOFI":
                    (
                        "Only positive values up to "
                        "100 receive weight. Zero, "
                        "blank, and missing values "
                        "are excluded."
                    ),

                "no_evidence":
                    (
                        "A country with no usable "
                        "Food Security evidence "
                        "receives a score of zero."
                    ),
            },

        "shock_block_method":
            (
                "FAO and ASAP share the 20 percent "
                "block equally when both receive "
                "weight. One source receives the "
                "full block when the other is "
                "unavailable."
            ),

        "source_files":
            source_files,

        "ipc_overrides":
            IPC_OVERRIDES,

        "countries_consolidated":
            int(
                len(results)
            ),

        "countries_with_usable_evidence":
            int(
                results[
                    "Available_Base_Weight"
                ]
                .gt(0)
                .sum()
            ),

        "countries_without_usable_evidence":
            int(
                results[
                    "Available_Base_Weight"
                ]
                .eq(0)
                .sum()
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


# ==================================================
# COMPLETE UPDATE
# ==================================================

def update_food_security():

    print(
        "Loading Food Security collector outputs..."
    )

    country_universe = (
        load_country_universe()
    )

    source_names = [
        "ipc",
        "fewsnet",
        "grfc",
        "fao",
        "asap",
        "sofi",
    ]

    source_frames = {
        source_name:
            read_source(
                source_name
            )

        for source_name in source_names
    }

    source_files = {
        source_name:
            SOURCE_CONFIG[
                source_name
            ]["file"]

        for source_name in source_names
    }

    merged = merge_sources(
        country_universe,
        source_frames,
    )

    validate_source_ranges(
        merged
    )

    # ----------------------------------------------
    # IPC selection
    # ----------------------------------------------

    ipc_selection = merged.apply(
        select_ipc_classification,
        axis=1,
    )

    merged = pd.concat(
        [
            merged,
            ipc_selection,
        ],
        axis=1,
    )

    # ----------------------------------------------
    # FAO / ASAP block
    # ----------------------------------------------

    shock_calculation = merged.apply(
        calculate_shock_block,
        axis=1,
    )

    merged = pd.concat(
        [
            merged,
            shock_calculation,
        ],
        axis=1,
    )

    # ----------------------------------------------
    # Consolidated score
    # ----------------------------------------------

    consolidated = merged.apply(
        calculate_consolidated_score,
        axis=1,
    )

    results = pd.concat(
        [
            merged,
            consolidated,
        ],
        axis=1,
    )

    results = (
        results
        .sort_values(
            "CERF_Country"
        )
        .reset_index(
            drop=True
        )
    )

    validate_results(
        results
    )

    print_afghanistan_check(
        results
    )

    save_outputs(
        results,
        source_files,
    )

    return results


# ==================================================
# MAIN
# ==================================================

if __name__ == "__main__":

    results = update_food_security()

    print()
    print("=" * 70)

    print(
        "FOOD SECURITY CONSOLIDATION COMPLETE"
    )

    print("=" * 70)

    print(
        f"Countries consolidated: "
        f"{len(results)}"
    )

    print(
        "Countries with usable evidence: "
        f"{results['Available_Base_Weight'].gt(0).sum()}"
    )

    print(
        "Countries without usable evidence: "
        f"{results['Available_Base_Weight'].eq(0).sum()}"
    )

    print()
    print(
        "Available-block distribution:"
    )

    print(
        results[
            "Available_Block_Count"
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print()
    print(
        "IPC source distribution:"
    )

    print(
        results[
            "IPC_Classification_Source"
        ]
        .fillna(
            "No IPC source"
        )
        .value_counts()
        .to_string()
    )

    print()
    print(
        "ASAP weighting check:"
    )

    asap_assessed = results[
        results[
            "asap_row_present"
        ]
    ]

    print(
        asap_assessed[
            [
                "ASAP_Available",
                "asap_value",
            ]
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print()
    print(
        "FAO weighting check:"
    )

    fao_assessed = results[
        results[
            "fao_row_present"
        ]
    ]

    print(
        fao_assessed[
            [
                "FAO_Available",
                "fao_value",
            ]
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print()
    print(
        "Sample consolidated results:"
    )

    print()

    print(
        results[
            [
                "CERF_Country",
                "ISO3",

                "IPC_Classification",
                "IPC_Classification_Source",

                "fao_value",
                "asap_value",

                "FAO_Available",
                "ASAP_Available",

                "Shock_Block_Score_100",
                "SOFI_Score_100",

                "Available_Base_Weight",
                "CERF_Food_Insecurity",
            ]
        ]
        .head(50)
        .to_string(
            index=False
        )
    )

    print()
    print(
        "Countries with manual IPC overrides:"
    )

    override_rows = results[
        results[
            "IPC_Override_Reason"
        ].notna()
    ]

    if override_rows.empty:

        print(
            "None."
        )

    else:

        print(
            override_rows[
                [
                    "CERF_Country",
                    "ISO3",
                    "IPC_Classification",
                    "IPC_Classification_Source",
                    "IPC_Override_Reason",
                    "CERF_Food_Insecurity",
                ]
            ]
            .to_string(
                index=False
            )
        )

    print()
    print(
        "Countries with no usable Food Security evidence:"
    )

    no_evidence = results[
        results[
            "Available_Base_Weight"
        ].eq(0)
    ]

    if no_evidence.empty:

        print(
            "None."
        )

    else:

        print(
            no_evidence[
                [
                    "CERF_Country",
                    "ISO3",
                    "CERF_Food_Insecurity",
                ]
            ]
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
        f"Missingness report saved to:\n"
        f"{missingness_output}"
    )

    print()
    print(
        f"Metadata saved to:\n"
        f"{metadata_output}"
    )