from pathlib import Path
from urllib.parse import urljoin
import hashlib
import json
import re
import unicodedata

import pandas as pd
import pymupdf
import requests
from bs4 import BeautifulSoup


# ==================================================
# SETTINGS
# ==================================================

WFP_GRFC_PAGE = (
    "https://www.wfp.org/publications/"
    "global-report-food-crises-grfc"
)

REPORT_YEAR = 2026
ANALYSIS_YEAR = 2025

MINIMUM_PDF_PAGES = 50

EXPECTED_TOTAL_CONTEXTS = 47
EXPECTED_PHASE_3_COUNT = 15
EXPECTED_PHASE_4_COUNT = 26
EXPECTED_PHASE_5_COUNT = 6


# ==================================================
# AUTHORITATIVE GRFC 2026 SEVERITY GROUPS
# ==================================================
#
# GRFC 2026 reports on acute food insecurity
# during 2025.
#
# Highest-phase scoring logic for CIRV:
#
# 5 = positive Phase 5 population
# 4 = positive Phase 4 population, no Phase 5
# 3 = Crisis-or-worse but no Phase 4/5,
#     OR no IPC/CH phase disaggregation
#
# IMPORTANT:
#
# GRFC reports 32 contexts with positive Phase 4
# populations.
#
# Six of those contexts also have Phase 5.
#
# Therefore, under highest-phase scoring:
#
# 32 - 6 = 26 exclusive Phase 4 scores.
# ==================================================


# --------------------------------------------------
# PHASE 5
# --------------------------------------------------

PHASE_5_ISO3 = {
    "HTI",  # Haiti
    "MLI",  # Mali
    "PSE",  # Palestine, Gaza Strip
    "SSD",  # South Sudan
    "SDN",  # Sudan
    "YEM",  # Yemen
}


# --------------------------------------------------
# PHASE-DISAGGREGATED CONTEXTS WITHOUT PHASE 4
# --------------------------------------------------
#
# These six contexts had phase-disaggregated data
# but no positive population in Phase 4.
#
# Their highest GRFC severity for CIRV is therefore
# Phase 3.
# --------------------------------------------------

NO_PHASE_4_ISO3 = {
    "BDI",  # Burundi
    "GNB",  # Guinea-Bissau
    "LSO",  # Lesotho
    "LBR",  # Liberia
    "MDG",  # Madagascar
    "TZA",  # Tanzania
}


# --------------------------------------------------
# NO IPC/CH PHASE DISAGGREGATION
# --------------------------------------------------
#
# GRFC reports qualifying high acute food insecurity
# data for these nine contexts, but no phase
# breakdown.
#
# For CIRV they receive the equivalent high-AFI
# baseline score 3.
# --------------------------------------------------

NO_PHASE_DISAGGREGATION_ISO3 = {
    "COL",  # Colombia
    "EGY",  # Egypt, refugees
    "SLV",  # El Salvador
    "IRQ",  # Iraq, refugees
    "JOR",  # Jordan, refugees
    "LKA",  # Sri Lanka
    "SYR",  # Syrian Arab Republic
    "UKR",  # Ukraine
    "ZWE",  # Zimbabwe
}


# --------------------------------------------------
# SELECTED BUT NO QUALIFYING 2025 DATA
# --------------------------------------------------
#
# These were the 17 false inclusions found by the
# PDF country-name detector.
#
# They appear in GRFC 2026 material, maps,
# comparisons, regional text or selected-country
# coverage, but they do NOT form part of the
# 47 contexts with qualifying 2025 acute food
# insecurity estimates.
#
# Armenia is the eighteenth non-qualifying selected
# context but was already absent from our detector.
# --------------------------------------------------

NO_QUALIFYING_2025_DATA_ISO3 = {
    "AGO",  # Angola
    "DZA",  # Algeria
    "BEN",  # Benin
    "BFA",  # Burkina Faso
    "COG",  # Republic of the Congo
    "CUB",  # Cuba
    "CIV",  # Côte d'Ivoire
    "ECU",  # Ecuador
    "ERI",  # Eritrea
    "SWZ",  # Eswatini
    "ETH",  # Ethiopia
    "IRN",  # Iran
    "LBY",  # Libya
    "MDA",  # Moldova
    "PER",  # Peru
    "TGO",  # Togo
    "TUR",  # Türkiye
}


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

raw_folder = (
    project_folder
    / "data"
    / "raw"
    / "grfc"
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

pdf_output = (
    raw_folder
    / "GRFC_2026_full.pdf"
)

text_output = (
    raw_folder
    / "GRFC_2026_full_text.txt"
)

current_output = (
    project_folder
    / "grfc_current.csv"
)

evidence_output = (
    raw_folder
    / "GRFC_2026_extraction_evidence.txt"
)

metadata_output = (
    raw_folder
    / "latest_grfc_report.json"
)

diagnostic_output = (
    raw_folder
    / "GRFC_2026_diagnostics.csv"
)


# ==================================================
# TEXT NORMALIZATION
# ==================================================

def normalize_text(value):

    if pd.isna(value):
        return None

    text = str(value).strip()

    text = (
        text
        .replace("’", "'")
        .replace("‘", "'")
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
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
        ":",
        ";",
        "|",
        "[",
        "]",
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

            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/pdf;q=0.9,*/*;q=0.8"
            ),

            "Accept-Language":
                "en-US,en;q=0.9",
        }
    )

    return session


# ==================================================
# FILE UTILITIES
# ==================================================

def calculate_hash(file_path):

    sha256 = hashlib.sha256()

    with open(
        file_path,
        "rb",
    ) as source_file:

        for block in iter(
            lambda: source_file.read(65536),
            b"",
        ):

            sha256.update(block)

    return sha256.hexdigest()


def validate_pdf(file_path):

    try:

        document = pymupdf.open(
            file_path
        )

        page_count = (
            document.page_count
        )

        if page_count <= 0:

            document.close()

            return 0

        first_page = (
            document.load_page(0)
        )

        first_page.get_text(
            "text"
        )

        document.close()

        return page_count

    except Exception:

        return 0


# ==================================================
# DISCOVER FULL GRFC 2026
# ==================================================

def discover_latest_grfc():

    print(
        "Checking official WFP GRFC page..."
    )

    session = create_session()

    response = session.get(
        WFP_GRFC_PAGE,
        timeout=60,
        allow_redirects=True,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    candidates = []

    for link in soup.find_all(
        "a",
        href=True,
    ):

        text = " ".join(
            link.get_text(
                " ",
                strip=True,
            ).split()
        )

        url = urljoin(
            WFP_GRFC_PAGE,
            link["href"],
        )

        parent = link.parent

        if parent is not None:

            context = " ".join(
                parent.get_text(
                    " ",
                    strip=True,
                ).split()
            )

        else:

            context = text

        url_lower = (
            url.lower()
        )

        text_lower = (
            text.lower()
        )

        context_lower = (
            context.lower()
        )

        score = 0

        if (
            "docs.wfp.org"
            in url_lower
        ):

            score += 100

        if (
            "/download"
            in url_lower
        ):

            score += 60

        if (
            "2026"
            in context_lower
        ):

            score += 150

        if (
            text_lower
            == "english"
        ):

            score += 50

        if (
            "mid-year"
            in context_lower
            or
            "mid year"
            in context_lower
        ):

            score -= 100

        if (
            "in brief"
            in context_lower
        ):

            score -= 100

        older_year = re.search(
            r"\b(201[7-9]|202[0-5])\b",
            context_lower,
        )

        if older_year:

            score -= 100

        if score <= 0:
            continue

        candidates.append(
            {
                "text":
                    text,

                "url":
                    url,

                "score":
                    score,
            }
        )

    if not candidates:

        raise RuntimeError(
            "No full GRFC download candidates "
            "were discovered."
        )

    candidates = sorted(
        candidates,
        key=lambda item:
            item["score"],
        reverse=True,
    )

    report = {
        "year":
            REPORT_YEAR,

        "analysis_year":
            ANALYSIS_YEAR,

        "title":
            "Global Report on Food Crises 2026",

        "report_code":
            "GRFC-2026",

        "publication_page":
            WFP_GRFC_PAGE,

        "candidates":
            candidates,
    }

    print()
    print(
        "Latest full GRFC discovered:"
    )

    print(
        report["title"]
    )

    print(
        candidates[0]["url"]
    )

    return report


# ==================================================
# DOWNLOAD REPORT
# ==================================================

def download_report(report):

    existing_pages = 0

    if pdf_output.exists():

        existing_pages = validate_pdf(
            pdf_output
        )

    if (
        existing_pages
        >= MINIMUM_PDF_PAGES
    ):

        print()
        print(
            "Using existing validated GRFC PDF."
        )

        print(
            f"Pages: {existing_pages}"
        )

        return (
            pdf_output,
            existing_pages,
            None,
        )

    session = create_session()

    for candidate in report[
        "candidates"
    ]:

        print()
        print(
            "Trying GRFC download:"
        )

        print(
            candidate["url"]
        )

        try:

            response = session.get(
                candidate["url"],
                timeout=240,
                allow_redirects=True,
                headers={
                    "Referer":
                        report[
                            "publication_page"
                        ],
                },
            )

        except requests.RequestException:

            continue

        if response.status_code != 200:
            continue

        temporary_file = (
            raw_folder
            / "_GRFC_candidate.tmp"
        )

        temporary_file.write_bytes(
            response.content
        )

        page_count = validate_pdf(
            temporary_file
        )

        if page_count == 0:

            pdf_start = (
                response.content.find(
                    b"%PDF"
                )
            )

            if pdf_start >= 0:

                temporary_file.write_bytes(
                    response.content[
                        pdf_start:
                    ]
                )

                page_count = validate_pdf(
                    temporary_file
                )

        if (
            page_count
            < MINIMUM_PDF_PAGES
        ):

            temporary_file.unlink(
                missing_ok=True
            )

            continue

        temporary_file.replace(
            pdf_output
        )

        print()
        print(
            "Full GRFC PDF downloaded."
        )

        print(
            f"Pages: {page_count}"
        )

        return (
            pdf_output,
            page_count,
            response.url,
        )

    raise RuntimeError(
        "The GRFC 2026 report was discovered, "
        "but its full PDF could not be downloaded."
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

    mapping["Normalized_Alias"] = (
        mapping[
            "Source_Alias"
        ]
        .apply(normalize_text)
    )

    return mapping[
        [
            "ISO3",
            "CERF_Country",
            "Source_Alias",
            "Normalized_Alias",
        ]
    ].drop_duplicates(
        subset=[
            "ISO3",
            "Normalized_Alias",
        ]
    )


# ==================================================
# ADD GRFC COUNTRY ALIASES
# ==================================================

def add_grfc_aliases(mapping):

    aliases = {

        "COD": [
            "Democratic Republic of the Congo",
            "Democratic Republic of Congo",
        ],

        "PSE": [
            "Palestine",
            "Palestine Gaza Strip",
            "Gaza Strip",
        ],

        "SYR": [
            "Syrian Arab Republic",
        ],

        "TZA": [
            "United Republic of Tanzania",
            "Tanzania",
        ],

        "PRK": [
            "Democratic People's Republic of Korea",
        ],

        "MDA": [
            "Republic of Moldova",
        ],

        "LKA": [
            "Sri Lanka",
        ],

        "CIV": [
            "Côte d'Ivoire",
            "Cote d'Ivoire",
        ],

        "CAF": [
            "Central African Republic",
        ],

        "TLS": [
            "Timor-Leste",
            "Timor Leste",
        ],
    }

    canonical_lookup = (
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

    additions = []

    for iso3, source_names in aliases.items():

        cerf_country = (
            canonical_lookup.get(
                iso3
            )
        )

        if cerf_country is None:
            continue

        for source_name in source_names:

            additions.append(
                {
                    "ISO3":
                        iso3,

                    "CERF_Country":
                        cerf_country,

                    "Source_Alias":
                        source_name,

                    "Normalized_Alias":
                        normalize_text(
                            source_name
                        ),
                }
            )

    if additions:

        mapping = pd.concat(
            [
                mapping,
                pd.DataFrame(
                    additions
                ),
            ],
            ignore_index=True,
        )

    return mapping.drop_duplicates(
        subset=[
            "ISO3",
            "Normalized_Alias",
        ] ,
        keep="first",
    )


# ==================================================
# EXTRACT PDF PAGES
# ================================================

def extract_pdf_pages(pdf_file):

    document = pymupdf.open(
        pdf_file
    )

    pages = []

    for page_index in range(
        document.page_count
    ):

        page = document.load_page(
            page_index
        )

        pages.append(
            {
                "Page":
                    page_index + 1,

                "Text":
                    page.get_text(
                        "text"
                    ),
            }
        )

    document.close()

    return pages


# ==================================================
# SAVE FULL TEXT
# ==================================================

def save_full_text(
    report,
    pdf_file,
    pages,
    resolved_url,
):

    lines = [
        "GLOBAL REPORT ON FOOD CRISES 2026",
        "=" * 80,
        "",
        (
            f"Report: "
            f"{report['title']}"
        ),
        (
            f"Publication page: "
            f"{report['publication_page']}"
        ),
        (
            f"Resolved PDF URL: "
            f"{resolved_url}"
        ),
        (
            f"PDF: "
            f"{pdf_file.name}"
        ),
        (
            f"SHA256: "
            f"{calculate_hash(pdf_file)}"
        ),
        (
            f"Pages: "
            f"{len(pages)}"
        ),
        "",
    ]

    for page in pages:

        lines.extend(
            [
                "=" * 80,

                (
                    f"PDF PAGE "
                    f"{page['Page']}"
                ),

                "=" * 80,
                "",
                page["Text"],
                "",
            ]
        )

    text_output.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


# ==================================================
# DETECT COUNTRY CONTEXTS
# ==================================================

def detect_grfc_contexts(
    pages,
    mapping,
):

    alias_lookup = {}

    for _, row in mapping.iterrows():

        alias_lookup[
            row["Normalized_Alias"]
        ] = {
            "ISO3":
                row["ISO3"],

            "CERF_Country":
                row["CERF_Country"],

            "Source_Alias":
                row["Source_Alias"],
        }

    observations = []

    candidate_pages = [
        page
        for page in pages
        if (
            5
            <= page["Page"]
            <= 45
        )
    ]

    for page in candidate_pages:

        lines = [
            line.strip()
            for line in page[
                "Text"
            ].splitlines()
            if line.strip()
        ]

        for start_index in range(
            len(lines)
        ):

            for line_count in range(
                5,
                0,
                -1,
            ):

                end_index = (
                    start_index
                    + line_count
                )

                if (
                    end_index
                    > len(lines)
                ):

                    continue

                combined = " ".join(
                    lines[
                        start_index:
                        end_index
                    ]
                )

                if (
                    len(combined)
                    > 100
                ):

                    continue

                country = (
                    alias_lookup.get(
                        normalize_text(
                            combined
                        )
                    )
                )

                if country is None:
                    continue

                observations.append(
                    {
                        "ISO3":
                            country[
                                "ISO3"
                            ],

                        "CERF_Country":
                            country[
                                "CERF_Country"
                            ],

                        "GRFC_Country":
                            combined,

                        "First_PDF_Page":
                            page["Page"],
                    }
                )

    contexts = pd.DataFrame(
        observations
    )

    if contexts.empty:

        raise RuntimeError(
            "No GRFC country contexts "
            "were detected."
        )

    contexts = (
        contexts
        .sort_values(
            [
                "ISO3",
                "First_PDF_Page",
            ]
        )
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .reset_index(
            drop=True
        )
    )

    return contexts


# ==================================================
# REMOVE NON-QUALIFYING 2025 CONTEXTS
# ==================================================

def remove_non_qualifying_contexts(
    contexts,
):

    removed = contexts[
        contexts[
            "ISO3"
        ].isin(
            NO_QUALIFYING_2025_DATA_ISO3
        )
    ].copy()

    contexts = contexts[
        ~contexts[
            "ISO3"
        ].isin(
            NO_QUALIFYING_2025_DATA_ISO3
        )
    ].copy()

    if not removed.empty:

        print()
        print(
            "Excluded contexts without "
            "qualifying 2025 GRFC data:"
        )

        print(
            removed[
                [
                    "CERF_Country",
                    "ISO3",
                ]
            ]
            .sort_values(
                "CERF_Country"
            )
            .to_string(
                index=False
            )
        )

    return (
        contexts.reset_index(
            drop=True
        ),
        removed,
    )


# ==================================================
# ENSURE AUTHORITATIVE CONTEXTS
# ==================================================

def ensure_authoritative_contexts(
    contexts,
    mapping,
):

    required_iso3 = (
        PHASE_5_ISO3
        | NO_PHASE_4_ISO3
        | NO_PHASE_DISAGGREGATION_ISO3
    )

    current_iso3 = set(
        contexts[
            "ISO3"
        ]
    )

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

    additions = []

    for iso3 in sorted(
        required_iso3
        - current_iso3
    ):

        country = canonical.get(
            iso3
        )

        if country is None:
            continue

        additions.append(
            {
                "ISO3":
                    iso3,

                "CERF_Country":
                    country,

                "GRFC_Country":
                    country,

                "First_PDF_Page":
                    pd.NA,
            }
        )

    if additions:

        contexts = pd.concat(
            [
                contexts,
                pd.DataFrame(
                    additions
                ),
            ],
            ignore_index=True,
        )

    return (
        contexts
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


# ==================================================
# SCORE CONTEXT
# ==================================================

def assign_grfc_score(row):

    iso3 = row[
        "ISO3"
    ]

    # ----------------------------------------------
    # PHASE 5
    # ----------------------------------------------

    if iso3 in PHASE_5_ISO3:

        return pd.Series(
            {
                "GRFC_Phase":
                    5,

                "GRFC_Category":
                    "Catastrophe",

                "Scoring_Method":
                    (
                        "GRFC 2026 authoritative "
                        "positive Phase 5 context"
                    ),

                "Evidence":
                    (
                        "GRFC 2026 reports a "
                        "positive population in "
                        "Catastrophe, IPC/CH "
                        "Phase 5, during 2025."
                    ),
            }
        )

    # ----------------------------------------------
    # PHASE 3:
    # DISAGGREGATED, BUT NO PHASE 4
    # ----------------------------------------------

    if iso3 in NO_PHASE_4_ISO3:

        return pd.Series(
            {
                "GRFC_Phase":
                    3,

                "GRFC_Category":
                    "Crisis",

                "Scoring_Method":
                    (
                        "Phase-disaggregated "
                        "GRFC context with no "
                        "positive Phase 4 population"
                    ),

                "Evidence":
                    (
                        "GRFC 2026 identifies this "
                        "as a phase-disaggregated "
                        "2025 context without a "
                        "positive Phase 4 population."
                    ),
            }
        )

    # ----------------------------------------------
    # PHASE 3:
    # NO PHASE DISAGGREGATION
    # ----------------------------------------------

    if (
        iso3
        in
        NO_PHASE_DISAGGREGATION_ISO3
    ):

        return pd.Series(
            {
                "GRFC_Phase":
                    3,

                "GRFC_Category":
                    (
                        "Crisis or worse "
                        "equivalent"
                    ),

                "Scoring_Method":
                    (
                        "GRFC high acute food "
                        "insecurity data without "
                        "IPC/CH phase disaggregation"
                    ),

                "Evidence":
                    (
                        "GRFC 2026 reports qualifying "
                        "2025 high acute food "
                        "insecurity data for this "
                        "context without an IPC/CH "
                        "phase breakdown."
                    ),
            }
        )

    # ----------------------------------------------
    # REMAINING QUALIFYING CONTEXTS
    #
    # There are 26 after:
    #
    # 47 total
    # - 6 Phase 5
    # - 6 no Phase 4
    # - 9 no phase disaggregation
    # = 26
    #
    # These contexts all had a positive Phase 4
    # population but no positive Phase 5 population.
    # ----------------------------------------------

    return pd.Series(
        {
            "GRFC_Phase":
                4,

            "GRFC_Category":
                "Emergency",

            "Scoring_Method":
                (
                    "GRFC 2026 positive "
                    "Phase 4 context"
                ),

            "Evidence":
                (
                    "GRFC 2026 reports a positive "
                    "population in Emergency, "
                    "IPC/CH Phase 4, during 2025."
                ),
        }
    )


# ==================================================
# VALIDATE RESULTS
# ==================================================

def validate_results(results):

    problems = []

    phase_counts = (
        results[
            "GRFC_Phase"
        ]
        .value_counts()
        .to_dict()
    )

    phase_3_count = int(
        phase_counts.get(
            3,
            0,
        )
    )

    phase_4_count = int(
        phase_counts.get(
            4,
            0,
        )
    )

    phase_5_count = int(
        phase_counts.get(
            5,
            0,
        )
    )

    actual_phase_5 = set(
        results.loc[
            results[
                "GRFC_Phase"
            ].eq(5),
            "ISO3",
        ]
    )

    if (
        len(results)
        != EXPECTED_TOTAL_CONTEXTS
    ):

        problems.append(
            (
                f"Total context count is "
                f"{len(results)}, expected "
                f"{EXPECTED_TOTAL_CONTEXTS}."
            )
        )

    if (
        phase_3_count
        != EXPECTED_PHASE_3_COUNT
    ):

        problems.append(
            (
                f"Exclusive Phase 3 count is "
                f"{phase_3_count}, expected "
                f"{EXPECTED_PHASE_3_COUNT}."
            )
        )

    if (
        phase_4_count
        != EXPECTED_PHASE_4_COUNT
    ):

        problems.append(
            (
                f"Exclusive Phase 4 count is "
                f"{phase_4_count}, expected "
                f"{EXPECTED_PHASE_4_COUNT}."
            )
        )

    if (
        phase_5_count
        != EXPECTED_PHASE_5_COUNT
    ):

        problems.append(
            (
                f"Exclusive Phase 5 count is "
                f"{phase_5_count}, expected "
                f"{EXPECTED_PHASE_5_COUNT}."
            )
        )

    if (
        actual_phase_5
        != PHASE_5_ISO3
    ):

        missing = (
            PHASE_5_ISO3
            - actual_phase_5
        )

        unexpected = (
            actual_phase_5
            - PHASE_5_ISO3
        )

        problems.append(
            (
                "Phase 5 ISO3 mismatch. "
                f"Missing: {sorted(missing)}; "
                f"Unexpected: "
                f"{sorted(unexpected)}."
            )
        )

    if not results[
        "GRFC_Phase"
    ].isin(
        [
            3,
            4,
            5,
        ]
    ).all():

        problems.append(
            "A GRFC score falls outside 3, 4, 5."
        )

    if problems:

        results.to_csv(
            diagnostic_output,
            index=False,
            encoding="utf-8-sig",
        )

        print()
        print(
            "GRFC VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "GRFC results failed validation. "
            "The current output was not replaced."
        )

    print()
    print(
        "GRFC VALIDATION PASSED"
    )

    print(
        f"Total contexts: "
        f"{len(results)}"
    )

    print(
        f"Phase 3: "
        f"{phase_3_count}"
    )

    print(
        f"Phase 4: "
        f"{phase_4_count}"
    )

    print(
        f"Phase 5: "
        f"{phase_5_count}"
    )


# ==================================================
# SAVE OUTPUTS
# ==================================================


def _verified_grfc_analysis_period(pdf_file):
    """
    Extract the report edition and report-wide annual analysis year.

    This does not infer country-specific assessment months.
    """

    with pymupdf.open(pdf_file) as document:
        opening_text = "\n".join(
            document[index].get_text("text")
            for index in range(min(20, document.page_count))
        )

    compact = re.sub(r"\s+", " ", opening_text)

    edition_match = re.search(
        r"(?:GLOBAL REPORT ON FOOD CRISES|GRFC)"
        r"\s*(?:\([^)]*\)\s*)?(20\d{2})",
        compact,
        flags=re.IGNORECASE,
    )

    if edition_match is None:
        raise RuntimeError(
            "Could not verify the GRFC edition from the PDF."
        )

    edition = int(edition_match.group(1))

    # These scoring groups are edition-specific, not dynamically
    # extracted phase-population tables.
    if edition != REPORT_YEAR:
        raise RuntimeError(
            f"PDF edition is {edition}, but this collector's "
            f"severity groups are configured for {REPORT_YEAR}. "
            "Current output was not replaced."
        )

    analysis_year = int(ANALYSIS_YEAR)

    evidence_pattern = re.compile(
        r"(?:acute food insecurity|food crises)"
        r".{0,300}?\b(?:in|during)\s+"
        + str(analysis_year)
        + r"\b",
        flags=re.IGNORECASE,
    )

    evidence_match = evidence_pattern.search(compact)

    if evidence_match is None:
        raise RuntimeError(
            f"Could not verify analysis year {analysis_year} "
            "in the PDF's introductory text. "
            "Current output was not replaced."
        )

    return {
        "report_year": edition,
        "analysis_year": analysis_year,
        "period": f"{analysis_year} — annual analysis",
        "evidence": evidence_match.group(0),
    }


def save_outputs(
    report,
    pdf_file,
    results,
    resolved_pdf_url,
    removed_contexts,
):

    # GRFC_PERIOD_ENRICHMENT
    period_info = _verified_grfc_analysis_period(pdf_file)

    results["GRFC_Time_Period"] = period_info["period"]
    results["GRFC_Report_Year"] = period_info["report_year"]
    results["GRFC_Analysis_Year"] = period_info["analysis_year"]
    results["GRFC_Period_Scope"] = "Report-wide annual analysis"
    results["GRFC_Period_Evidence"] = period_info["evidence"]
    results["GRFC_Source_File"] = pdf_file.name
    results["GRFC_Source_SHA256"] = calculate_hash(pdf_file)

    results.to_csv(
        current_output,
        index=False,
        encoding="utf-8-sig",
    )

    evidence_lines = [
        "GRFC 2026 COUNTRY SEVERITY EXTRACTION",
        "=" * 80,
        "",
        f"Report: {report['title']}",
        (
            f"Analysis year: "
            f"{report['analysis_year']}"
        ),
        (
            f"Publication page: "
            f"{report['publication_page']}"
        ),
        (
            f"Resolved PDF URL: "
            f"{resolved_pdf_url}"
        ),
        (
            f"PDF: "
            f"{pdf_file.name}"
        ),
        (
            f"SHA256: "
            f"{calculate_hash(pdf_file)}"
        ),
        (
            f"Qualifying contexts scored: "
            f"{len(results)}"
        ),
        (
            f"Non-qualifying detected "
            f"contexts removed: "
            f"{len(removed_contexts)}"
        ),
        "",
        "Highest-phase distribution:",
        (
            "Phase 3 = 15"
        ),
        (
            "Phase 4 = 26"
        ),
        (
            "Phase 5 = 6"
        ),
        (
            "Total = 47"
        ),
        "",
    ]

    for _, row in results.iterrows():

        evidence_lines.extend(
            [
                "-" * 80,

                (
                    f"{row['CERF_Country']} "
                    f"({row['ISO3']})"
                ),

                (
                    f"Phase: "
                    f"{row['GRFC_Phase']}"
                ),

                (
                    f"Category: "
                    f"{row['GRFC_Category']}"
                ),

                (
                    f"Method: "
                    f"{row['Scoring_Method']}"
                ),

                (
                    f"First PDF page: "
                    f"{row['First_PDF_Page']}"
                ),

                (
                    f"Evidence: "
                    f"{row['Evidence']}"
                ),

                "",
            ]
        )

    evidence_output.write_text(
        "\n".join(
            evidence_lines
        ),
        encoding="utf-8",
    )

    phase_counts = (
        results[
            "GRFC_Phase"
        ]
        .value_counts()
        .sort_index()
        .to_dict()
    )

    metadata = {
        "title":
            report["title"],

        "report_code":
            report["report_code"],

        "publication_year":
            report["year"],

        "analysis_year":
            report["analysis_year"],

        "publication_page":
            report["publication_page"],

        "resolved_pdf_url":
            resolved_pdf_url,

        "pdf_file":
            pdf_file.name,

        "pdf_sha256":
            calculate_hash(
                pdf_file
            ),

        "contexts_scored":
            int(
                len(results)
            ),

        "phase_counts":
            {
                str(key):
                    int(value)

                for key, value in (
                    phase_counts.items()
                )
            },

        "phase_5_iso3":
            sorted(
                PHASE_5_ISO3
            ),

        "no_phase_4_iso3":
            sorted(
                NO_PHASE_4_ISO3
            ),

        "no_phase_disaggregation_iso3":
            sorted(
                NO_PHASE_DISAGGREGATION_ISO3
            ),

        "non_qualifying_2025_iso3":
            sorted(
                NO_QUALIFYING_2025_DATA_ISO3
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

def update_grfc():

    report = (
        discover_latest_grfc()
    )

    (
        pdf_file,
        page_count,
        resolved_pdf_url,
    ) = download_report(
        report
    )

    print()
    print(
        "Extracting GRFC 2026 report..."
    )

    pages = extract_pdf_pages(
        pdf_file
    )

    save_full_text(
        report,
        pdf_file,
        pages,
        resolved_pdf_url,
    )

    mapping = load_country_mapping()

    mapping = add_grfc_aliases(
        mapping
    )

    detected_contexts = (
        detect_grfc_contexts(
            pages,
            mapping,
        )
    )

    print()
    print(
        f"Raw CERF-mapped contexts "
        f"detected: "
        f"{len(detected_contexts)}"
    )

    (
        contexts,
        removed_contexts,
    ) = remove_non_qualifying_contexts(
        detected_contexts
    )

    contexts = (
        ensure_authoritative_contexts(
            contexts,
            mapping,
        )
    )

    print()
    print(
        f"Qualifying GRFC contexts "
        f"after filtering: "
        f"{len(contexts)}"
    )

    scoring = contexts.apply(
        assign_grfc_score,
        axis=1,
    )

    results = pd.concat(
        [
            contexts,
            scoring,
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

    save_outputs(
        report,
        pdf_file,
        results,
        resolved_pdf_url,
        removed_contexts,
    )

    return (
        report,
        pdf_file,
        results,
        removed_contexts,
    )


# ==================================================
# RUN
# ==================================================

if __name__ == "__main__":

    (
        report,
        pdf_file,
        results,
        removed_contexts,
    ) = update_grfc()

    print()
    print("=" * 70)

    print(
        "GRFC 2026 EXTRACTION COMPLETE"
    )

    print("=" * 70)

    print(
        f"Report: "
        f"{report['title']}"
    )

    print(
        f"Contexts scored: "
        f"{len(results)}"
    )

    print()
    print(
        "Phase counts:"
    )

    print(
        results[
            "GRFC_Phase"
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )

    print()
    print(
        "Phase 5 contexts:"
    )

    print(
        results.loc[
            results[
                "GRFC_Phase"
            ].eq(5),
            [
                "CERF_Country",
                "ISO3",
            ],
        ]
        .to_string(
            index=False
        )
    )

    print()
    print(
        "Phase 3 contexts:"
    )

    print(
        results.loc[
            results[
                "GRFC_Phase"
            ].eq(3),
            [
                "CERF_Country",
                "ISO3",
                "Scoring_Method",
            ],
        ]
        .to_string(
            index=False
        )
    )

    print()
    print(
        "All extracted contexts:"
    )

    print()

    print(
        results[
            [
                "CERF_Country",
                "ISO3",
                "GRFC_Phase",
                "GRFC_Category",
                "First_PDF_Page",
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
        f"Metadata saved to:\n"
        f"{metadata_output}"
    )