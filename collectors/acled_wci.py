from pathlib import Path
from urllib.parse import urljoin
import io
import json
import math
import re
import zipfile

import pandas as pd
import requests
from bs4 import BeautifulSoup

from collectors import acled_auth

acled_auth.validate_credentials()

ACLED_USERNAME = acled_auth.ACLED_USERNAME
ACLED_PASSWORD = acled_auth.ACLED_PASSWORD
create_authenticated_session = acled_auth.create_authenticated_session


# ==================================================
# SETTINGS
# ==================================================

WCI_PAGE_URL = (
    "https://acleddata.com/"
    "platform/weekly-conflict-index"
)

WCI_RESULTS_PAGE_URL = (
    "https://acleddata.com/"
    "results/weekly-conflict-index-results"
)

ACLED_LOGIN_PAGE = (
    "https://acleddata.com/user/login"
)

# CIRV methodology:
#
# Use the HIGHEST Weekly Conflict Index observation
# during the THREE MONTHS preceding the latest
# refresh date in the ACLED dataset.

WCI_LOOKBACK_MONTHS = 3

MINIMUM_EXPECTED_MAPPED_COUNTRIES = 100


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
    / "wci"
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

current_output = (
    project_folder
    / "acled_wci_current.csv"
)

evidence_output = (
    processed_folder
    / "acled_wci_evidence.csv"
)

window_output = (
    processed_folder
    / "acled_wci_three_month_window.csv"
)

unmatched_output = (
    processed_folder
    / "acled_wci_unmatched.csv"
)

metadata_output = (
    processed_folder
    / "acled_wci_metadata.json"
)


# ==================================================
# SOURCE COLUMN CANDIDATES
# ==================================================

ISO3_CANDIDATES = [
    "ISO3",
    "ISO",
    "Country ISO3",
    "Country Code",
    "Alpha-3 Code",
]

COUNTRY_CANDIDATES = [
    "Country",
    "Country Name",
    "Location",
]

WCI_SCORE_CANDIDATES = [
    "Weekly Conflict Index",
    "Weekly Conflict Index Score",
    "WCI Score",
    "WCI",
    "Conflict Index Score",
    "Conflict Index",
    "Score",
]

WCI_DATE_CANDIDATES = [
    "Week Ending",
    "Week End",
    "Reference Date",
    "Score Date",
    "WCI Date",
    "Date",
    "Week",
    "Updated",
    "Last Updated",
    "Refresh Date",
]


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


def find_column(
    data,
    candidates,
    description,
    required=True,
):

    lookup = {
        normalize_text(column):
            column
        for column in data.columns
    }

    # Exact match first.

    for candidate in candidates:

        key = normalize_text(
            candidate
        )

        if key in lookup:
            return lookup[key]

    # Controlled partial match.

    for candidate in candidates:

        key = normalize_text(
            candidate
        )

        for (
            normalized_column,
            original_column,
        ) in lookup.items():

            if (
                key
                and
                (
                    key in normalized_column
                    or
                    normalized_column in key
                )
            ):
                return original_column

    if required:

        raise RuntimeError(
            f"Could not identify {description}.\n\n"
            f"Expected one of:\n"
            f"{candidates}\n\n"
            f"Available columns:\n"
            f"{list(data.columns)}"
        )

    return None


# ==================================================
# COUNTRY MAPPING
# ==================================================

def load_country_mapping():

    if not mapping_file.exists():

        raise FileNotFoundError(
            "CERF country mapping not found:\n"
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
        for column in required
        if column not in mapping.columns
    ]

    if missing:

        raise RuntimeError(
            "countries.csv is missing:\n"
            f"{missing}"
        )

    mapping["ISO3"] = (
        mapping["ISO3"]
        .apply(normalize_iso3)
    )

    mapping = mapping[
        mapping["ISO3"].notna()
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

    if "Source_Alias" in mapping.columns:

        aliases = mapping[
            [
                "ISO3",
                "CERF_Country",
                "Source_Alias",
            ]
        ].copy()

    else:

        aliases = universe.copy()

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
# DETECT WHETHER A TABLE LOOKS LIKE WCI DATA
# ==================================================

def table_is_wci(data):

    if data is None:
        return False

    if data.empty:
        return False

    score = find_column(
        data,
        WCI_SCORE_CANDIDATES,
        "WCI score",
        required=False,
    )

    date = find_column(
        data,
        WCI_DATE_CANDIDATES,
        "WCI date",
        required=False,
    )

    country = find_column(
        data,
        COUNTRY_CANDIDATES,
        "country",
        required=False,
    )

    iso3 = find_column(
        data,
        ISO3_CANDIDATES,
        "ISO3",
        required=False,
    )

    return (
        score is not None
        and
        date is not None
        and
        (
            country is not None
            or
            iso3 is not None
        )
    )


# ==================================================
# TRY TO READ TABULAR CONTENT
# ==================================================

def try_read_csv_bytes(content):

    encodings = [
        "utf-8-sig",
        "utf-8",
        "latin-1",
    ]

    separators = [
        ",",
        ";",
        "\t",
    ]

    for encoding in encodings:

        for separator in separators:

            try:

                data = pd.read_csv(
                    io.BytesIO(content),
                    encoding=encoding,
                    sep=separator,
                    low_memory=False,
                )

                if table_is_wci(
                    data
                ):
                    return data

            except Exception:
                pass

    return None


def try_read_excel_bytes(content):

    try:

        workbook = pd.ExcelFile(
            io.BytesIO(content)
        )

    except Exception:
        return None

    for sheet in workbook.sheet_names:

        for header_row in range(
            0,
            8,
        ):

            try:

                candidate = pd.read_excel(
                    workbook,
                    sheet_name=sheet,
                    header=header_row,
                )

            except Exception:
                continue

            if table_is_wci(
                candidate
            ):

                print(
                    f"Selected ACLED sheet: "
                    f"{sheet}"
                )

                print(
                    f"Selected Excel header row: "
                    f"{header_row}"
                )

                return candidate

    return None


def try_read_json_bytes(content):

    try:

        payload = json.loads(
            content.decode(
                "utf-8"
            )
        )

    except Exception:
        return None

    candidate_records = []

    if isinstance(
        payload,
        list,
    ):
        candidate_records.append(
            payload
        )

    elif isinstance(
        payload,
        dict,
    ):

        for key in [
            "data",
            "results",
            "records",
            "items",
            "content",
        ]:

            value = payload.get(
                key
            )

            if isinstance(
                value,
                list,
            ):
                candidate_records.append(
                    value
                )

        # Some APIs put the useful list one
        # dictionary level deeper.

        for value in payload.values():

            if isinstance(
                value,
                dict,
            ):

                for nested in (
                    value.values()
                ):

                    if isinstance(
                        nested,
                        list,
                    ):
                        candidate_records.append(
                            nested
                        )

    for records in candidate_records:

        try:

            data = pd.DataFrame(
                records
            )

        except Exception:
            continue

        if table_is_wci(
            data
        ):
            return data

    return None


def read_download_bytes(
    content,
    suggested_name="",
    content_type="",
):

    lowered = (
        suggested_name
        + " "
        + content_type
    ).lower()

    if (
        ".xlsx" in lowered
        or
        ".xls" in lowered
        or
        "spreadsheet" in lowered
        or
        "excel" in lowered
    ):

        data = try_read_excel_bytes(
            content
        )

        if data is not None:
            return data

    if (
        ".json" in lowered
        or
        "application/json"
        in lowered
    ):

        data = try_read_json_bytes(
            content
        )

        if data is not None:
            return data

    data = try_read_csv_bytes(
        content
    )

    if data is not None:
        return data

    data = try_read_json_bytes(
        content
    )

    if data is not None:
        return data

    data = try_read_excel_bytes(
        content
    )

    if data is not None:
        return data

    # ZIP fallback.

    try:

        with zipfile.ZipFile(
            io.BytesIO(content)
        ) as archive:

            for member in (
                archive.namelist()
            ):

                member_content = (
                    archive.read(
                        member
                    )
                )

                try:

                    data = read_download_bytes(
                        member_content,
                        suggested_name=member,
                    )

                    if data is not None:
                        return data

                except RuntimeError:
                    continue

    except zipfile.BadZipFile:
        pass

    raise RuntimeError(
        "Downloaded response could not be "
        "recognized as WCI tabular data."
    )


# ==================================================
# FIRST ATTEMPT:
# REQUESTS-BASED DISCOVERY
# ==================================================

def requests_discovery(
    session,
):

    pages = [
        WCI_RESULTS_PAGE_URL,
        WCI_PAGE_URL,
    ]

    candidates = []

    for page_url in pages:

        print()
        print(
            "Inspecting authenticated ACLED page:"
        )

        print(
            page_url
        )

        response = session.get(
            page_url,
            timeout=90,
            allow_redirects=True,
        )

        if response.status_code != 200:
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        # Standard links.

        for tag in soup.find_all(
            [
                "a",
                "iframe",
                "script",
            ]
        ):

            url = (
                tag.get("href")
                or
                tag.get("src")
            )

            if not url:
                continue

            url = urljoin(
                response.url,
                url,
            )

            combined = (
                normalize_text(
                    tag.get_text(
                        " ",
                        strip=True,
                    )
                )
                + " "
                + url.lower()
            )

            if any(
                phrase in combined
                for phrase in [
                    "weekly conflict",
                    "conflict index",
                    "wci",
                    "download",
                    "export",
                    ".csv",
                    ".xlsx",
                    ".json",
                ]
            ):

                candidates.append(
                    url
                )

        # data-* attributes.

        for tag in soup.find_all(
            True
        ):

            for (
                attribute,
                value,
            ) in tag.attrs.items():

                if not (
                    attribute.startswith(
                        "data-"
                    )
                ):
                    continue

                if isinstance(
                    value,
                    list,
                ):
                    value = " ".join(
                        value
                    )

                if not isinstance(
                    value,
                    str,
                ):
                    continue

                if (
                    "http" in value
                    or
                    "/download" in value
                    or
                    "/export" in value
                ):

                    candidates.append(
                        urljoin(
                            response.url,
                            value,
                        )
                    )

    candidates = list(
        dict.fromkeys(
            candidates
        )
    )

    for url in candidates:

        try:

            response = session.get(
                url,
                timeout=120,
                allow_redirects=True,
            )

            if response.status_code != 200:
                continue

            data = read_download_bytes(
                response.content,
                suggested_name=response.url,
                content_type=(
                    response.headers.get(
                        "Content-Type",
                        ""
                    )
                ),
            )

            if table_is_wci(
                data
            ):

                print()
                print(
                    "WCI data found through "
                    "requests discovery:"
                )

                print(
                    response.url
                )

                return (
                    data,
                    response.url,
                    "requests",
                )

        except Exception:
            continue

    return None


# ==================================================
# BROWSER FALLBACK:
# PLAYWRIGHT
# ==================================================

def browser_discovery():
    """
    Use a real Chromium browser so JavaScript-loaded
    ACLED resources and downloads become visible.

    The browser watches every response for tabular
    WCI data and also attempts visible download /
    export controls.
    """

    try:

        from playwright.sync_api import (
            sync_playwright,
        )

    except ImportError as exc:

        raise RuntimeError(
            "WCI requires browser-based discovery.\n\n"
            "Install Playwright with:\n\n"
            "python -m pip install playwright\n"
            "python -m playwright install chromium"
        ) from exc

    captured = {
        "data":
            None,

        "url":
            None,
    }

    candidate_responses = []

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
        )

        context = (
            browser.new_context(
                accept_downloads=True,
            )
        )

        page = context.new_page()

        # ------------------------------------------
        # Capture relevant responses.
        # ------------------------------------------

        def inspect_response(
            response,
        ):

            if (
                captured[
                    "data"
                ]
                is not None
            ):
                return

            url = (
                response.url
            )

            lowered = (
                url.lower()
            )

            content_type = (
                response.headers.get(
                    "content-type",
                    ""
                )
                .lower()
            )

            possibly_data = (
                any(
                    marker in lowered
                    for marker in [
                        "weekly",
                        "conflict",
                        "index",
                        "wci",
                        "download",
                        "export",
                        "result",
                    ]
                )
                or
                any(
                    marker in content_type
                    for marker in [
                        "json",
                        "csv",
                        "excel",
                        "spreadsheet",
                        "octet-stream",
                    ]
                )
            )

            if possibly_data:

                candidate_responses.append(
                    (
                        url,
                        content_type,
                    )
                )

                try:

                    body = (
                        response.body()
                    )

                    data = (
                        read_download_bytes(
                            body,
                            suggested_name=url,
                            content_type=(
                                content_type
                            ),
                        )
                    )

                    if table_is_wci(
                        data
                    ):

                        captured[
                            "data"
                        ] = data

                        captured[
                            "url"
                        ] = url

                except Exception:
                    pass

        page.on(
            "response",
            inspect_response,
        )

        # ------------------------------------------
        # Log in through the actual website.
        # ------------------------------------------

        print()
        print(
            "Launching browser fallback..."
        )

        print(
            "Logging into myACLED in Chromium..."
        )

        page.goto(
            ACLED_LOGIN_PAGE,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        # Username input.

        username_selectors = [
            'input[name="name"]',
            'input[name="username"]',
            'input[type="email"]',
        ]

        username_input = None

        for selector in (
            username_selectors
        ):

            locator = page.locator(
                selector
            )

            if locator.count() > 0:

                username_input = (
                    locator.first
                )

                break

        if username_input is None:

            browser.close()

            raise RuntimeError(
                "Could not locate the username "
                "field on the myACLED login page."
            )

        # Password input.

        password_input = (
            page.locator(
                'input[type="password"]'
            )
        )

        if password_input.count() == 0:

            browser.close()

            raise RuntimeError(
                "Could not locate the password "
                "field on the myACLED login page."
            )

        username_input.fill(
            ACLED_USERNAME
        )

        password_input.first.fill(
            ACLED_PASSWORD
        )

        submit_candidates = [
            'button[type="submit"]',
            'input[type="submit"]',
        ]

        submitted = False

        for selector in (
            submit_candidates
        ):

            button = page.locator(
                selector
            )

            if button.count() > 0:

                button.first.click()

                submitted = True

                break

        if not submitted:

            browser.close()

            raise RuntimeError(
                "Could not locate the myACLED "
                "login submit button."
            )

        page.wait_for_timeout(
            3000
        )

        # ------------------------------------------
        # Visit WCI results.
        # ------------------------------------------

        print(
            "Opening WCI results in browser..."
        )

        page.goto(
            WCI_RESULTS_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        # Give JavaScript/API calls time to run.

        page.wait_for_timeout(
            10000
        )

        if (
            captured[
                "data"
            ]
            is not None
        ):

            browser.close()

            print()
            print(
                "WCI data captured from browser "
                "network traffic."
            )

            return (
                captured[
                    "data"
                ],
                captured[
                    "url"
                ],
                "playwright-network",
            )

        # ------------------------------------------
        # Attempt explicit download/export controls.
        # ------------------------------------------

        clickable_patterns = [
            "Download",
            "Export",
            "CSV",
            "Excel",
            "XLSX",
            "Results",
        ]

        for pattern in (
            clickable_patterns
        ):

            locators = page.get_by_text(
                pattern,
                exact=False,
            )

            count = min(
                locators.count(),
                10,
            )

            for index in range(
                count
            ):

                locator = locators.nth(
                    index
                )

                try:

                    if not locator.is_visible():
                        continue

                except Exception:
                    continue

                try:

                    with page.expect_download(
                        timeout=10000
                    ) as download_info:

                        locator.click()

                    download = (
                        download_info.value
                    )

                    path = download.path()

                    content = (
                        Path(path)
                        .read_bytes()
                    )

                    data = (
                        read_download_bytes(
                            content,
                            suggested_name=(
                                download
                                .suggested_filename
                            ),
                        )
                    )

                    if table_is_wci(
                        data
                    ):

                        source_url = (
                            download.url
                        )

                        browser.close()

                        print()
                        print(
                            "WCI data captured from "
                            "browser download."
                        )

                        return (
                            data,
                            source_url,
                            "playwright-download",
                        )

                except Exception:

                    # Some controls launch XHR rather
                    # than an actual browser download.

                    try:

                        locator.click(
                            timeout=3000
                        )

                        page.wait_for_timeout(
                            4000
                        )

                    except Exception:
                        pass

                if (
                    captured[
                        "data"
                    ]
                    is not None
                ):

                    browser.close()

                    return (
                        captured[
                            "data"
                        ],
                        captured[
                            "url"
                        ],
                        "playwright-network",
                    )

        print()
        print(
            "Potential browser response URLs:"
        )

        for (
            url,
            content_type,
        ) in candidate_responses[-50:]:

            print(
                f"{content_type} | {url}"
            )

        browser.close()

    raise RuntimeError(
        "The browser authenticated successfully, "
        "but no response containing recognizable "
        "WCI country/date/score data was captured.\n\n"
        "The potential response URLs printed above "
        "will identify the next adjustment needed."
    )


# ==================================================
# ACQUIRE WCI DATA
# ==================================================

def acquire_wci_data():

    session = (
        create_authenticated_session()
    )

    discovered = (
        requests_discovery(
            session
        )
    )

    if discovered is not None:

        return discovered

    print()
    print(
        "No static download was exposed."
    )

    print(
        "Switching to browser-based "
        "JavaScript discovery..."
    )

    return browser_discovery()


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
        on="ISO3",
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

    alias_needed = (
        alias_needed
        .drop(
            columns=[
                "ISO3",
                "CERF_Country",
            ],
            errors="ignore",
        )
    )

    alias_needed = (
        alias_needed
        .merge(
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
# CIRV THREE-MONTH WCI RULE
# ==================================================

def calculate_current_wci(
    source,
    universe,
    aliases,
):

    print()
    print(
        "ACLED WCI columns discovered:"
    )

    for column in (
        source.columns
    ):

        print(
            f"- {column}"
        )

    score_column = find_column(
        source,
        WCI_SCORE_CANDIDATES,
        "WCI score field",
    )

    date_column = find_column(
        source,
        WCI_DATE_CANDIDATES,
        "WCI date field",
    )

    iso3_column = find_column(
        source,
        ISO3_CANDIDATES,
        "WCI ISO3 field",
        required=False,
    )

    country_column = find_column(
        source,
        COUNTRY_CANDIDATES,
        "WCI country field",
        required=(
            iso3_column is None
        ),
    )

    prepared = source.copy()

    if iso3_column:

        prepared[
            "ISO3"
        ] = prepared[
            iso3_column
        ].apply(
            normalize_iso3
        )

    else:

        prepared[
            "ISO3"
        ] = None

    if country_column:

        prepared[
            "ACLED_Country"
        ] = (
            prepared[
                country_column
            ]
            .astype(str)
            .str.strip()
        )

    else:

        prepared[
            "ACLED_Country"
        ] = pd.NA

    prepared[
        "Normalized_Country"
    ] = prepared[
        "ACLED_Country"
    ].apply(
        normalize_text
    )

    prepared[
        "ACLED_WCI_Observation"
    ] = prepared[
        score_column
    ].apply(
        parse_numeric
    )

    prepared[
        "ACLED_WCI_Date"
    ] = pd.to_datetime(
        prepared[
            date_column
        ],
        errors="coerce",
    )

    prepared = prepared[
        prepared[
            "ACLED_WCI_Observation"
        ].notna()
        &
        prepared[
            "ACLED_WCI_Date"
        ].notna()
    ].copy()

    if prepared.empty:

        raise RuntimeError(
            "No valid dated ACLED WCI "
            "observations were parsed."
        )

    if (
        prepared[
            "ACLED_WCI_Observation"
        ]
        .lt(0)
        .any()
    ):

        raise RuntimeError(
            "Negative ACLED WCI values "
            "were found."
        )

    # ----------------------------------------------
    # Refresh date
    # ----------------------------------------------

    refresh_date = (
        prepared[
            "ACLED_WCI_Date"
        ]
        .max()
    )

    # ----------------------------------------------
    # Trailing three calendar months
    # ----------------------------------------------

    window_start = (
        refresh_date
        -
        pd.DateOffset(
            months=WCI_LOOKBACK_MONTHS
        )
    )

    window = prepared[
        prepared[
            "ACLED_WCI_Date"
        ].gt(
            window_start
        )
        &
        prepared[
            "ACLED_WCI_Date"
        ].le(
            refresh_date
        )
    ].copy()

    if window.empty:

        raise RuntimeError(
            "No WCI observations fall inside "
            "the trailing three-month window."
        )

    mapped_window = map_countries(
        window,
        universe,
        aliases,
    )

    unmatched = mapped_window[
        mapped_window[
            "CERF_Country"
        ].isna()
    ].copy()

    mapped_window = (
        mapped_window[
            mapped_window[
                "CERF_Country"
            ].notna()
        ]
        .copy()
    )

    # ----------------------------------------------
    # CRITICAL CIRV RULE:
    #
    # For each country select the HIGHEST WCI score
    # observed in the three-month window.
    #
    # If the same peak occurs more than once, use
    # its most recent observation date.
    # ----------------------------------------------

    mapped_window = (
        mapped_window
        .sort_values(
            [
                "ISO3",
                "ACLED_WCI_Observation",
                "ACLED_WCI_Date",
            ],
            ascending=[
                True,
                False,
                False,
            ],
        )
    )

    current = (
        mapped_window
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .copy()
    )

    counts = (
        mapped_window
        .groupby(
            "ISO3"
        )
        .size()
        .rename(
            "ACLED_WCI_Observations_In_Window"
        )
        .reset_index()
    )

    current = current.merge(
        counts,
        on="ISO3",
        how="left",
    )

    current = current.rename(
        columns={
            "ACLED_WCI_Observation":
                "ACLED_WCI",

            "ACLED_WCI_Date":
                "ACLED_WCI_Peak_Date",
        }
    )

    current[
        "ACLED_WCI_Refresh_Date"
    ] = refresh_date

    current[
        "ACLED_WCI_Window_Start"
    ] = window_start

    current[
        "ACLED_WCI_Window_End"
    ] = refresh_date

    current = current[
        [
            "ISO3",
            "CERF_Country",
            "ACLED_Country",
            "ACLED_WCI",
            "ACLED_WCI_Peak_Date",
            "ACLED_WCI_Refresh_Date",
            "ACLED_WCI_Window_Start",
            "ACLED_WCI_Window_End",
            "ACLED_WCI_Observations_In_Window",
        ]
    ].copy()

    evidence = mapped_window[
        [
            "ISO3",
            "CERF_Country",
            "ACLED_Country",
            "ACLED_WCI_Observation",
            "ACLED_WCI_Date",
        ]
    ].copy()

    return (
        current,
        evidence,
        unmatched,
        refresh_date,
        window_start,
        score_column,
        date_column,
        iso3_column,
        country_column,
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
                "countries received WCI values."
            )
        )

    if (
        current[
            "ISO3"
        ]
        .duplicated()
        .any()
    ):

        problems.append(
            "Duplicate ISO3 records."
        )

    if (
        current[
            "ACLED_WCI"
        ]
        .isna()
        .any()
    ):

        problems.append(
            "Missing selected WCI scores."
        )

    if (
        current[
            "ACLED_WCI"
        ]
        .lt(0)
        .any()
    ):

        problems.append(
            "Negative WCI scores."
        )

    invalid_dates = current[
        (
            current[
                "ACLED_WCI_Peak_Date"
            ]
            <=
            current[
                "ACLED_WCI_Window_Start"
            ]
        )
        |
        (
            current[
                "ACLED_WCI_Peak_Date"
            ]
            >
            current[
                "ACLED_WCI_Window_End"
            ]
        )
    ]

    if not invalid_dates.empty:

        problems.append(
            (
                f"{len(invalid_dates)} peak dates "
                "fall outside the CIRV "
                "three-month window."
            )
        )

    if problems:

        print()
        print(
            "ACLED WCI VALIDATION FAILED"
        )

        for problem in problems:

            print(
                f"- {problem}"
            )

        raise RuntimeError(
            "ACLED WCI validation failed."
        )

    print()
    print(
        "ACLED WCI VALIDATION PASSED"
    )


# ==================================================
# SAVE
# ==================================================

def save_outputs(
    current,
    evidence,
    unmatched,
    source_url,
    acquisition_method,
    refresh_date,
    window_start,
    score_column,
    date_column,
    iso3_column,
    country_column,
):

    output = current.copy()

    date_fields = [
        "ACLED_WCI_Peak_Date",
        "ACLED_WCI_Refresh_Date",
        "ACLED_WCI_Window_Start",
        "ACLED_WCI_Window_End",
    ]

    for column in date_fields:

        output[column] = (
            pd.to_datetime(
                output[column],
                errors="coerce",
            )
            .dt.strftime(
                "%Y-%m-%d"
            )
        )

    evidence_copy = (
        evidence.copy()
    )

    evidence_copy[
        "ACLED_WCI_Date"
    ] = (
        pd.to_datetime(
            evidence_copy[
                "ACLED_WCI_Date"
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

    evidence_copy.to_csv(
        evidence_output,
        index=False,
        encoding="utf-8-sig",
    )

    evidence_copy.to_csv(
        window_output,
        index=False,
        encoding="utf-8-sig",
    )

    if not unmatched.empty:

        unmatched.to_csv(
            unmatched_output,
            index=False,
            encoding="utf-8-sig",
        )

    else:

        pd.DataFrame().to_csv(
            unmatched_output,
            index=False,
        )

    metadata = {
        "source":
            "ACLED Weekly Conflict Index",

        "methodology":
            (
                "Highest WCI score observed for "
                "each country during the trailing "
                "three calendar months."
            ),

        "refresh_date":
            refresh_date.strftime(
                "%Y-%m-%d"
            ),

        "window_start_exclusive":
            window_start.strftime(
                "%Y-%m-%d"
            ),

        "window_end_inclusive":
            refresh_date.strftime(
                "%Y-%m-%d"
            ),

        "lookback_months":
            WCI_LOOKBACK_MONTHS,

        "source_url":
            source_url,

        "acquisition_method":
            acquisition_method,

        "detected_columns":
            {
                "country":
                    country_column,

                "iso3":
                    iso3_column,

                "score":
                    score_column,

                "date":
                    date_column,
            },

        "mapped_countries":
            int(
                len(output)
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

    return output


# ==================================================
# COMPLETE UPDATE
# ==================================================

def update_acled_wci():

    (
        source,
        source_url,
        acquisition_method,
    ) = acquire_wci_data()

    (
        universe,
        aliases,
    ) = load_country_mapping()

    (
        current,
        evidence,
        unmatched,
        refresh_date,
        window_start,
        score_column,
        date_column,
        iso3_column,
        country_column,
    ) = calculate_current_wci(
        source,
        universe,
        aliases,
    )

    validate_results(
        current
    )

    return save_outputs(
        current,
        evidence,
        unmatched,
        source_url,
        acquisition_method,
        refresh_date,
        window_start,
        score_column,
        date_column,
        iso3_column,
        country_column,
    )


# ==================================================
# MAIN
# ==================================================

if __name__ == "__main__":

    current = (
        update_acled_wci()
    )

    print()
    print("=" * 70)

    print(
        "ACLED WCI UPDATE COMPLETE"
    )

    print("=" * 70)

    print(
        f"CERF countries mapped: "
        f"{len(current)}"
    )

    print()
    print(
        "Highest WCI score during trailing "
        "three-month window:"
    )

    print()

    print(
        current[
            [
                "CERF_Country",
                "ISO3",
                "ACLED_WCI",
                "ACLED_WCI_Peak_Date",
                "ACLED_WCI_Refresh_Date",
                "ACLED_WCI_Observations_In_Window",
            ]
        ]
        .sort_values(
            "ACLED_WCI",
            ascending=False,
        )
        .head(50)
        .to_string(
            index=False
        )
    )

    print()
    print(
        f"Current output saved to:\n"
        f"{current_output}"
    )