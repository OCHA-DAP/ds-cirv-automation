from pathlib import Path
import unicodedata

import pandas as pd
from openpyxl import load_workbook


# ==================================================
# PROJECT LOCATIONS
# ==================================================

project_folder = Path(__file__).parent.parent

input_folder = (
    project_folder
    / "input"
)

config_folder = (
    project_folder
    / "config"
)

config_folder.mkdir(
    parents=True,
    exist_ok=True,
)

output_file = (
    config_folder
    / "countries.csv"
)


# ==================================================
# FIND THE CIRV WORKBOOK
# ==================================================

excel_files = list(
    input_folder.glob("*.xlsx")
)

if not excel_files:
    raise FileNotFoundError(
        "No CIRV workbook was found "
        "inside the input folder."
    )

workbook_path = excel_files[0]

print(
    f"Reading CERF countries from: "
    f"{workbook_path.name}"
)


# ==================================================
# READ CERF CANONICAL COUNTRIES
# ==================================================

workbook = load_workbook(
    workbook_path,
    read_only=True,
    data_only=True,
)

sheet = workbook[
    "CERF UFE 2026-I All Data"
]

cerf_countries = []

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

    if not country or not iso3:
        continue

    cerf_countries.append(
        {
            "ISO3": str(iso3).strip().upper(),
            "CERF_Country": str(country).strip(),
        }
    )


canonical = pd.DataFrame(
    cerf_countries
)

canonical = (
    canonical
    .drop_duplicates(
        subset=["ISO3"],
        keep="first",
    )
    .sort_values("CERF_Country")
    .reset_index(drop=True)
)


# ==================================================
# STANDARD COUNTRY ALIASES
# ==================================================

# The CERF country name always comes from the
# master workbook.
#
# This dictionary stores alternative names that
# external data sources may use.
#
# Add new aliases here whenever future sources
# introduce another country-name variation.

aliases_by_iso3 = {

    "AFG": [
        "Afghanistan",
    ],

    "BOL": [
        "Bolivia",
        "Bolivia (Plurinational State of)",
        "Bolivia, Plurinational State of",
    ],

    "BRN": [
        "Brunei",
        "Brunei Darussalam",
    ],

    "CPV": [
        "Cabo Verde",
        "Cape Verde",
    ],

    # ------------------------------
    # Central African Republic
    # ------------------------------

    "CAF": [
        "Central African Republic",
        "Central African Rep.",
        "Central African Rep",
        "C. African Rep.",
        "CAR",
    ],

    # ------------------------------
    # Democratic Republic of Congo
    # ------------------------------

    "COD": [
        "Congo DR",
        "DR Congo",
        "DRC",
        "D.R. Congo",
        "Democratic Republic of the Congo",
        "Democratic Republic of Congo",
        "Congo, Democratic Republic of the",
        "Congo, Dem. Rep.",
        "Congo (Kinshasa)",
    ],

    # ------------------------------
    # Republic of Congo
    # ------------------------------

    "COG": [
        "Congo",
        "Republic of the Congo",
        "Congo Republic",
        "Congo, Republic of the",
        "Congo (Brazzaville)",
    ],

    # ------------------------------
    # Côte d'Ivoire
    # ------------------------------

    "CIV": [
        "Côte d'Ivoire",
        "Côte d’Ivoire",
        "Côte D'Ivoire",
        "Côte D’Ivoire",
        "Cote d'Ivoire",
        "Cote d’Ivoire",
        "Cote D'Ivoire",
        "Cote D’Ivoire",
        "Ivory Coast",
    ],

    "CZE": [
        "Czechia",
        "Czech Republic",
    ],

    # ------------------------------
    # Equatorial Guinea
    # ------------------------------

    "GNQ": [
        "Equatorial Guinea",
        "Eq. Guinea",
        "Eq Guinea",
    ],

    "SWZ": [
        "Eswatini",
        "Swaziland",
    ],

    "GMB": [
        "Gambia",
        "The Gambia",
        "Gambia, The",
    ],

    "IRN": [
        "Iran",
        "Iran (Islamic Republic of)",
        "Iran, Islamic Republic of",
    ],

    # ------------------------------
    # Lao PDR
    # ------------------------------

    "LAO": [
        "Lao PDR",
        "Laos",
        "Lao People's Democratic Republic",
        "Lao People’s Democratic Republic",
        "Lao Democratic People's Republic",
    ],

    "FSM": [
        "Micronesia",
        "Micronesia (Federated States of)",
        "Federated States of Micronesia",
        "Micronesia, Fed. Sts.",
    ],

    "MDA": [
        "Moldova",
        "Republic of Moldova",
        "Moldova, Republic of",
    ],

    "MMR": [
        "Myanmar",
        "Burma",
    ],

    # ------------------------------
    # North Korea
    # ------------------------------

    "PRK": [
        "Korea DPR",
        "North Korea",
        "DPR Korea",
        "Democratic People's Republic of Korea",
        "Democratic People’s Republic of Korea",
        "Korea, Democratic People's Republic of",
    ],

    # ------------------------------
    # South Korea
    # ------------------------------

    "KOR": [
        "Korea Republic",
        "Korea Republic of",
        "Korea Rep.",
        "South Korea",
        "Republic of Korea",
        "Korea, Republic of",
    ],

    "MKD": [
        "North Macedonia",
        "Macedonia",
        "The former Yugoslav Republic of Macedonia",
    ],

    # ------------------------------
    # Palestine / oPt
    # ------------------------------

    "PSE": [
        "oPt",
        "OPT",
        "State of Palestine",
        "Palestine",
        "Occupied Palestinian Territory",
        "occupied Palestinian territory",
        "Palestinian Territory",
        "West Bank and Gaza",
    ],

    "RUS": [
        "Russia",
        "Russian Federation",
    ],

    "STP": [
        "Sao Tome and Principe",
        "São Tomé and Príncipe",
        "São Tomé & Príncipe",
    ],

    "SYR": [
        "Syria",
        "Syrian Arab Republic",
    ],

    "TZA": [
        "Tanzania",
        "United Republic of Tanzania",
        "Tanzania, United Republic of",
    ],

    "TLS": [
        "Timor-Leste",
        "East Timor",
    ],

    "TUR": [
        "Türkiye",
        "Turkey",
        "Turkiye",
    ],

    "GBR": [
        "United Kingdom",
        "United Kingdom of Great Britain and Northern Ireland",
        "UK",
    ],

    "USA": [
        "United States",
        "United States of America",
        "USA",
        "US",
    ],

    "VEN": [
        "Venezuela",
        "Venezuela (Bolivarian Republic of)",
        "Venezuela, Bolivarian Republic of",
    ],

    "VNM": [
        "Viet Nam",
        "Vietnam",
    ],

    "YEM": [
        "Yemen",
        "Yemen, Rep.",
    ],
}


# ==================================================
# NORMALIZE COUNTRY NAMES
# ==================================================

def normalize_country_name(value):
    """
    Normalize country names for matching.

    Handles:

    - capitalization
    - accents
    - apostrophe variants
    - punctuation
    - repeated spaces

    Example:

    Côte D’Ivoire

    becomes:

    cote d ivoire
    """

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

    # Remove accents.
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

    text = " ".join(
        text.split()
    )

    return text


# ==================================================
# BUILD MAPPING TABLE
# ==================================================

mapping_records = []

for _, row in canonical.iterrows():

    iso3 = row["ISO3"]

    cerf_country = row[
        "CERF_Country"
    ]

    source_aliases = set()

    # CERF's own country name is always
    # automatically recognized.
    source_aliases.add(
        cerf_country
    )

    # Add known external-source aliases.
    for alias in aliases_by_iso3.get(
        iso3,
        [],
    ):

        source_aliases.add(alias)

    for alias in sorted(
        source_aliases
    ):

        mapping_records.append(
            {
                "ISO3": iso3,
                "CERF_Country": cerf_country,
                "Source_Alias": alias,
                "Normalized_Alias":
                    normalize_country_name(
                        alias
                    ),
            }
        )


mapping = pd.DataFrame(
    mapping_records
)


# ==================================================
# QUALITY CHECK 1
#
# One ISO3 must correspond to only one
# CERF canonical country.
# ==================================================

duplicate_iso3_names = (
    canonical
    .groupby(
        "ISO3"
    )["CERF_Country"]
    .nunique()
)


duplicate_iso3_names = (
    duplicate_iso3_names[
        duplicate_iso3_names > 1
    ]
)


if not duplicate_iso3_names.empty:

    raise RuntimeError(
        "Some ISO3 codes map to more than "
        "one CERF country."
    )


# ==================================================
# QUALITY CHECK 2
#
# A normalized alias should not point to
# multiple ISO3 codes.
# ==================================================

ambiguous_aliases = (
    mapping
    .groupby(
        "Normalized_Alias"
    )["ISO3"]
    .nunique()
)


ambiguous_aliases = (
    ambiguous_aliases[
        ambiguous_aliases > 1
    ]
)


if not ambiguous_aliases.empty:

    print()
    print(
        "WARNING: Ambiguous aliases found:"
    )

    print(
        ambiguous_aliases.to_string()
    )


# ==================================================
# REMOVE DUPLICATE ALIASES
# ==================================================

mapping = (
    mapping
    .drop_duplicates(
        subset=[
            "ISO3",
            "Normalized_Alias",
        ]
    )
    .sort_values(
        [
            "CERF_Country",
            "Source_Alias",
        ]
    )
    .reset_index(
        drop=True
    )
)


# ==================================================
# SAVE COUNTRY MAPPING
# ==================================================

mapping.to_csv(
    output_file,
    index=False,
    encoding="utf-8-sig",
)


# ==================================================
# SUMMARY
# ==================================================

print()
print("=" * 70)
print("CERF COUNTRY MAPPING CREATED")
print("=" * 70)

print(
    f"CERF canonical countries: "
    f"{len(canonical)}"
)

print(
    f"Country aliases stored: "
    f"{len(mapping)}"
)

print(
    f"Saved to: "
    f"{output_file}"
)


# ==================================================
# DISPLAY IMPORTANT EXAMPLES
# ==================================================

print()
print("Example mappings:")
print()


example_iso3 = [
    "CAF",
    "COD",
    "COG",
    "CIV",
    "GNQ",
    "LAO",
    "PRK",
    "KOR",
    "PSE",
]


examples = mapping[
    mapping["ISO3"].isin(
        example_iso3
    )
]


print(
    examples.to_string(
        index=False
    )
)