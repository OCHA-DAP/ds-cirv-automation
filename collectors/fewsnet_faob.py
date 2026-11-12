from datetime import date
from pathlib import Path
import calendar
import hashlib
import json
import re
import unicodedata

import pandas as pd
import pymupdf
import requests


# ==================================================
# SETTINGS
# ==================================================

FEWS_BASE_URL = (
    "https://fews.net/global/"
    "food-assistance-outlook-brief"
)

VALIDATION_YEAR = 2026
VALIDATION_MONTH = 7


# ==================================================
# PROJECT FILES
# ==================================================

project_folder = Path(__file__).parent.parent

raw_folder = (
    project_folder
    / "data"
    / "raw"
    / "fewsnet_faob"
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

metadata_file = (
    raw_folder
    / "latest_fewsnet_faob.json"
)

current_output_file = (
    project_folder
    / "fewsnet_faob_current.csv"
)

validation_output_file = (
    project_folder
    / "fewsnet_faob_july_2026.csv"
)


# ==================================================
# TEXT NORMALIZATION
# ==================================================

def normalize_text(value):
    """
    Normalize country names for matching.
    """

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
        ":",
        ";",
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
        }
    )

    return session


# ==================================================
# URL CONSTRUCTION
# ==================================================

def build_report_url(
    year,
    month,
):

    month_name = (
        calendar.month_name[month]
        .lower()
    )

    return (
        f"{FEWS_BASE_URL}/"
        f"{month_name}-{year}"
    )


# ==================================================
# CHECK WHETHER A MONTHLY REPORT EXISTS
# ==================================================

def check_report(
    year,
    month,
):

    session = create_session()

    report_url = build_report_url(
        year,
        month,
    )

    response = session.get(
        report_url,
        timeout=60,
        allow_redirects=True,
    )

    if response.status_code != 200:
        return None

    page_text = response.text.lower()

    expected_date = (
        f"{calendar.month_name[month].lower()} "
        f"{year}"
    )

    if (
        "food assistance outlook brief"
        not in page_text
    ):
        return None

    if expected_date not in page_text:
        return None

    return {
        "year":
            year,

        "month":
            month,

        "month_name":
            calendar.month_name[month],

        "title":
            (
                "Food Assistance Outlook Brief, "
                f"{calendar.month_name[month]} "
                f"{year}"
            ),

        "url":
            report_url,

        "print_url":
            f"{report_url}/print",

        "report_code":
            f"{year}-{month:02d}",
    }


# ==================================================
# DYNAMIC DISCOVERY
# ==================================================

def discover_latest_report():
    """
    Search backward from the current month until
    the latest available FEWS NET FAOB is found.
    """

    today = date.today()

    year = today.year
    month = today.month

    print(
        "Checking FEWS NET monthly "
        "FAOB publications..."
    )

    for _ in range(18):

        print(
            f"Checking "
            f"{calendar.month_name[month]} "
            f"{year}..."
        )

        report = check_report(
            year,
            month,
        )

        if report is not None:

            print()
            print(
                "Latest FEWS NET FAOB found:"
            )

            print(
                report["title"]
            )

            print(
                report["url"]
            )

            return report

        month -= 1

        if month == 0:

            month = 12
            year -= 1

    raise RuntimeError(
        "No FEWS NET FAOB found within "
        "the previous 18 months."
    )


# ==================================================
# HISTORICAL VALIDATION REPORT
# ==================================================

def get_validation_report():

    report = check_report(
        VALIDATION_YEAR,
        VALIDATION_MONTH,
    )

    if report is None:

        raise RuntimeError(
            "The July 2026 FEWS NET FAOB "
            "could not be retrieved."
        )

    return report


# ==================================================
# DOWNLOAD PDF
# ==================================================

def download_report(
    report,
):
    """
    Download a FEWS NET FAOB from its /print URL.

    The /print endpoint returns an actual PDF.
    """

    output_file = (
        raw_folder
        / (
            "FEWSNET_FAOB_"
            f"{report['year']}_"
            f"{report['month']:02d}.pdf"
        )
    )

    if output_file.exists():

        print()
        print(
            "This FEWS NET report is already "
            "downloaded."
        )

        print(
            f"Using existing file: "
            f"{output_file}"
        )

        return output_file

    session = create_session()

    print()
    print(
        f"Downloading: "
        f"{report['title']}"
    )

    response = session.get(
        report["print_url"],
        timeout=120,
        allow_redirects=True,
    )

    response.raise_for_status()

    content_type = (
        response.headers
        .get(
            "Content-Type",
            "",
        )
        .lower()
    )

    if not (
        "pdf" in content_type
        or
        response.content.startswith(
            b"%PDF"
        )
    ):

        raise RuntimeError(
            "FEWS NET /print did not "
            "return a valid PDF."
        )

    output_file.write_bytes(
        response.content
    )

    print(
        "PDF download successful."
    )

    print(
        f"Saved to: "
        f"{output_file}"
    )

    return output_file


# ==================================================
# FILE HASH
# ==================================================

def calculate_hash(
    file_path,
):

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


# ==================================================
# LOAD CERF COUNTRY MAPPING
# ==================================================

def load_country_mapping():

    if not mapping_file.exists():

        raise FileNotFoundError(
            "CERF country mapping not found.\n"
            f"Expected location:\n"
            f"{mapping_file}"
        )

    mapping = pd.read_csv(
        mapping_file
    )

    mapping["Normalized_Alias"] = (
        mapping["Source_Alias"]
        .apply(normalize_text)
    )

    return (
        mapping[
            [
                "ISO3",
                "CERF_Country",
                "Source_Alias",
                "Normalized_Alias",
            ]
        ]
        .drop_duplicates(
            subset=[
                "ISO3",
                "Normalized_Alias",
            ]
        )
    )


# ==================================================
# FEWS NET-SPECIFIC COUNTRY ALIASES
# ==================================================

def add_fewsnet_aliases(mapping):

    aliases = {
        "COD": [
            "Democratic Republic of the Congo",
            "Democratic Republic of Congo",
        ],

        "CAF": [
            "Central African Republic",
        ],

        "CIV": [
            "Côte d'Ivoire",
            "Cote d'Ivoire",
        ],

        "PSE": [
            "Palestine",
            "State of Palestine",
        ],

        "SYR": [
            "Syria",
            "Syrian Arab Republic",
        ],

        "TZA": [
            "Tanzania",
            "United Republic of Tanzania",
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

    new_records = []

    for iso3, source_aliases in aliases.items():

        cerf_country = (
            canonical_lookup.get(
                iso3
            )
        )

        if cerf_country is None:
            continue

        for alias in source_aliases:

            new_records.append(
                {
                    "ISO3":
                        iso3,

                    "CERF_Country":
                        cerf_country,

                    "Source_Alias":
                        alias,

                    "Normalized_Alias":
                        normalize_text(alias),
                }
            )

    if new_records:

        mapping = pd.concat(
            [
                mapping,
                pd.DataFrame(
                    new_records
                ),
            ],
            ignore_index=True,
        )

    return mapping.drop_duplicates(
        subset=[
            "ISO3",
            "Normalized_Alias",
        ],
        keep="first",
    )


# ==================================================
# COUNTRY LOOKUP
# ==================================================

def create_country_lookup(mapping):

    lookup = {}

    for _, row in mapping.iterrows():

        lookup[
            row["Normalized_Alias"]
        ] = {
            "ISO3":
                row["ISO3"],

            "CERF_Country":
                row["CERF_Country"],

            "Source_Alias":
                row["Source_Alias"],
        }

    return lookup


# ==================================================
# EXTRACT PDF PAGES
# ==================================================

def extract_pdf_pages(
    pdf_file,
):

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
# FIND COUNTRY HEADING
# ==================================================

def find_country_at_line(
    lines,
    line_index,
    country_lookup,
):
    """
    Country names can span multiple PDF lines.

    Examples:

    Democratic
    Republic of
    the Congo

    Central
    African
    Republic

    Search the current line plus up to three
    following lines and prefer the longest match.
    """

    max_lines = 4

    for line_count in range(
        max_lines,
        0,
        -1,
    ):

        end_index = (
            line_index + line_count
        )

        if end_index > len(lines):
            continue

        parts = [
            lines[index].strip()
            for index in range(
                line_index,
                end_index,
            )
            if lines[index].strip()
        ]

        if not parts:
            continue

        combined = " ".join(
            parts
        )

        if len(combined) > 80:
            continue

        normalized = normalize_text(
            combined
        )

        country = country_lookup.get(
            normalized
        )

        if country is not None:

            return {
                "country":
                    country,

                "source_name":
                    combined,

                "lines_used":
                    line_count,
            }

    return None


# ==================================================
# EXTRACT IPC PHASE
# ==================================================

def extract_ipc_phase(
    text,
):
    """
    Extract the most likely area-level IPC phase.

    Examples:

    Crisis (IPC Phase 3)
        -> 3

    Crisis! (IPC Phase 3!)
        -> 3

    Emergency (IPC Phase 4) & risk of Famine
        -> 4

    The phrase "risk of Famine" does not change
    the score to 5 because it is an alternative
    scenario rather than the most likely outcome.
    """

    matches = re.findall(
        (
            r"IPC\s+Phase\s*"
            r"([1-5])"
            r"!?"
        ),
        text,
        flags=re.IGNORECASE,
    )

    if not matches:
        return None

    return int(
        matches[0]
    )


# ==================================================
# PARSE COUNTRY RECORDS
# ==================================================

def parse_country_records(
    pages,
    mapping,
):
    """
    Parse the country-level rows from the FEWS NET
    table on PDF pages 3 to 5.

    The first IPC classification following a country
    heading is treated as that country's highest
    projected area-level IPC classification.
    """

    lookup = create_country_lookup(
        mapping
    )

    observations = []

    # In the July 2026 report the country table is
    # located on PDF pages 3 to 5.
    candidate_pages = [
        page
        for page in pages
        if 3 <= page["Page"] <= 5
    ]

    for page in candidate_pages:

        page_number = page[
            "Page"
        ]

        raw_lines = (
            page["Text"]
            .splitlines()
        )

        lines = [
            line.strip()
            for line in raw_lines
        ]

        line_index = 0

        while line_index < len(lines):

            match = find_country_at_line(
                lines,
                line_index,
                lookup,
            )

            if match is None:

                line_index += 1
                continue

            country = match[
                "country"
            ]

            source_name = match[
                "source_name"
            ]

            lines_used = match[
                "lines_used"
            ]

            search_start = (
                line_index + lines_used
            )

            next_country_index = None

            search_index = search_start

            # Find where the next country starts.
            while search_index < len(lines):

                next_match = find_country_at_line(
                    lines,
                    search_index,
                    lookup,
                )

                if next_match is not None:

                    next_country_index = (
                        search_index
                    )

                    break

                search_index += 1

            if next_country_index is None:

                next_country_index = (
                    min(
                        search_start + 45,
                        len(lines),
                    )
                )

            block_lines = lines[
                search_start:
                next_country_index
            ]

            block_text = "\n".join(
                block_lines
            )

            ipc_phase = extract_ipc_phase(
                block_text
            )

            if ipc_phase is not None:

                classification_match = re.search(
                    (
                        r"([A-Za-z]+!?)\s*"
                        r"\(IPC\s+Phase\s*"
                        r"([1-5])!?\)"
                    ),
                    block_text,
                    flags=re.IGNORECASE,
                )

                classification = None

                if classification_match:

                    classification = (
                        classification_match
                        .group(1)
                        .replace(
                            "!",
                            "",
                        )
                        .title()
                    )

                evidence_lines = [
                    line
                    for line in block_lines[:18]
                    if line
                ]

                observations.append(
                    {
                        "ISO3":
                            country["ISO3"],

                        "CERF_Country":
                            country[
                                "CERF_Country"
                            ],

                        "FEWSNET_Country":
                            source_name,

                        "FEWSNET_IPC":
                            ipc_phase,

                        "FEWSNET_Classification":
                            classification,

                        "PDF_Page":
                            page_number,

                        "Evidence":
                            " | ".join(
                                evidence_lines
                            ),
                    }
                )

            line_index = max(
                next_country_index,
                line_index + 1,
            )

    results = pd.DataFrame(
        observations
    )

    if results.empty:

        raise RuntimeError(
            "No FEWS NET country IPC values "
            "were extracted."
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
            "WARNING: Duplicate FEWS NET "
            "countries were extracted:"
        )

        print(
            duplicates[
                [
                    "CERF_Country",
                    "ISO3",
                    "FEWSNET_IPC",
                    "PDF_Page",
                ]
            ]
            .to_string(index=False)
        )

    results = (
        results
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

    return results


# ==================================================
# SAVE EXTRACTION EVIDENCE
# ==================================================

def save_evidence(
    report,
    pdf_file,
    results,
):

    output_file = (
        raw_folder
        / (
            "FEWSNET_FAOB_"
            f"{report['year']}_"
            f"{report['month']:02d}"
            "_extraction_evidence.txt"
        )
    )

    lines = [
        "FEWS NET FAOB COUNTRY EXTRACTION",
        "=" * 80,
        "",
        f"Report: {report['title']}",
        f"URL: {report['url']}",
        f"PDF: {pdf_file.name}",
        (
            f"SHA256: "
            f"{calculate_hash(pdf_file)}"
        ),
        (
            f"Countries extracted: "
            f"{len(results)}"
        ),
        "",
    ]

    for _, row in results.iterrows():

        lines.extend(
            [
                "-" * 80,

                (
                    f"{row['CERF_Country']} "
                    f"({row['ISO3']})"
                ),

                (
                    "FEWS NET source name: "
                    f"{row['FEWSNET_Country']}"
                ),

                (
                    "Highest projected IPC: "
                    f"{row['FEWSNET_IPC']}"
                ),

                (
                    "Classification: "
                    f"{row['FEWSNET_Classification']}"
                ),

                (
                    "PDF page: "
                    f"{row['PDF_Page']}"
                ),

                (
                    "Evidence: "
                    f"{row['Evidence']}"
                ),

                "",
            ]
        )

    output_file.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return output_file


# ==================================================
# SAVE METADATA
# ==================================================

def save_metadata(
    report,
    pdf_file,
    results,
):

    metadata = {
        "title":
            report["title"],

        "report_code":
            report["report_code"],

        "url":
            report["url"],

        "print_url":
            report["print_url"],

        "pdf_file":
            pdf_file.name,

        "pdf_sha256":
            calculate_hash(
                pdf_file
            ),

        "countries_extracted":
            int(len(results)),
    }

    metadata_file.write_text(
        json.dumps(
            metadata,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ==================================================
# PROCESS ONE REPORT
# ==================================================

def process_report(
    report,
    output_file,
):
    """
    Download, parse, validate, and save one
    FEWS NET FAOB.
    """

    pdf_file = download_report(
        report
    )

    pages = extract_pdf_pages(
        pdf_file
    )

    mapping = load_country_mapping()

    mapping = add_fewsnet_aliases(
        mapping
    )

    results = parse_country_records(
        pages,
        mapping,
    )

    if results[
        "FEWSNET_IPC"
    ].isna().any():

        raise RuntimeError(
            "One or more FEWS NET countries "
            "have no IPC classification."
        )

    if not results[
        "FEWSNET_IPC"
    ].between(
        1,
        5,
    ).all():

        raise RuntimeError(
            "FEWS NET returned an IPC value "
            "outside the range 1 to 5."
        )

    results.to_csv(
        output_file,
        index=False,
        encoding="utf-8-sig",
    )

    evidence_file = save_evidence(
        report,
        pdf_file,
        results,
    )

    return (
        pdf_file,
        results,
        evidence_file,
    )


# ==================================================
# HISTORICAL JULY 2026 EXTRACTION
# ==================================================

def extract_july_2026_fewsnet():

    report = get_validation_report()

    (
        pdf_file,
        results,
        evidence_file,
    ) = process_report(
        report,
        validation_output_file,
    )

    return (
        report,
        pdf_file,
        results,
        evidence_file,
    )


# ==================================================
# DYNAMIC LIVE UPDATE
# ==================================================

def update_fewsnet_faob():
    """
    Complete dynamic FEWS NET workflow.

    1. Discover latest monthly FAOB.
    2. Download its PDF.
    3. Extract countries and highest IPC phase.
    4. Map to CERF canonical countries.
    5. Validate values.
    6. Save current output and evidence.
    """

    report = discover_latest_report()

    (
        pdf_file,
        results,
        evidence_file,
    ) = process_report(
        report,
        current_output_file,
    )

    save_metadata(
        report,
        pdf_file,
        results,
    )

    return (
        report,
        pdf_file,
        results,
        evidence_file,
    )


# ==================================================
# RUN DIRECTLY
# ==================================================


# DYNAMIC_FAOB_PERIOD_WRAPPER
_faob_original_update = update_fewsnet_faob

def update_fewsnet_faob():
    report, pdf_file, results, evidence_file = (
        _faob_original_update()
    )

    period = f"{report['month_name']} {report['year']}"

    results["Report_Period"] = period
    results["Report_Title"] = report["title"]
    results["Report_URL"] = report["url"]

    results.to_csv(
        current_output_file,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        "\nFEWS NET FAOB REPORT PERIOD:",
        period,
        flush=True,
    )

    return report, pdf_file, results, evidence_file

if __name__ == "__main__":

    # First extract the historical July report.
    (
        july_report,
        july_pdf,
        july_results,
        july_evidence,
    ) = extract_july_2026_fewsnet()

    print()
    print("=" * 70)
    print(
        "FEWS NET JULY 2026 EXTRACTION COMPLETE"
    )
    print("=" * 70)

    print(
        f"Countries extracted: "
        f"{len(july_results)}"
    )

    print()
    print(
        july_results[
            [
                "CERF_Country",
                "ISO3",
                "FEWSNET_IPC",
                "FEWSNET_Classification",
                "PDF_Page",
            ]
        ]
        .to_string(index=False)
    )

    print()
    print(
        f"Historical output saved to:\n"
        f"{validation_output_file}"
    )

    print()
    print(
        f"Historical evidence saved to:\n"
        f"{july_evidence}"
    )

    # Then process the newest publication.
    print()
    print(
        "Processing latest FEWS NET FAOB..."
    )

    (
        latest_report,
        latest_pdf,
        latest_results,
        latest_evidence,
    ) = update_fewsnet_faob()

    print()
    print("=" * 70)
    print(
        "FEWS NET DYNAMIC UPDATE COMPLETE"
    )
    print("=" * 70)

    print(
        f"Latest report: "
        f"{latest_report['title']}"
    )

    print(
        f"Countries extracted: "
        f"{len(latest_results)}"
    )

    print()
    print(
        latest_results[
            [
                "CERF_Country",
                "ISO3",
                "FEWSNET_IPC",
                "FEWSNET_Classification",
                "PDF_Page",
            ]
        ]
        .to_string(index=False)
    )

    print()
    print(
        f"Current output saved to:\n"
        f"{current_output_file}"
    )

    print()
    print(
        f"Current evidence saved to:\n"
        f"{latest_evidence}"
    )

    print()
    print(
        f"Metadata saved to:\n"
        f"{metadata_file}"
    )