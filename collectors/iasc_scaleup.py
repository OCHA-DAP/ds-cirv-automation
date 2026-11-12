from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin
import json
import re

import pandas as pd
import requests
from bs4 import BeautifulSoup


# ==================================================
# SETTINGS
# ==================================================

IASC_BASE_URL = "https://interagencystandingcommittee.org"
IASC_RESOURCES_URL = (
    "https://interagencystandingcommittee.org/resources"
    "?og_group_ref_target_id=All"
    "&f%5B0%5D=content_type%3Aannouncement"
)

SEARCH_PHRASES = [
    "system-wide scale-up",
    "system wide scale up",
    "scale-up activation",
    "scale up activation",
    "scale-up deactivation",
    "scale up deactivation",
]

MAX_RESOURCE_PAGES = 12
REQUEST_TIMEOUT_SECONDS = 120
EXPECTED_COUNTRIES = 150

# If a public page is temporarily ambiguous, add an audited override in:
# config/iasc_scaleup_overrides.csv
# Required columns:
# ISO3,Active,Activation_Date,End_Date,ScaleUp_Type,Source_URL,Note


# ==================================================
# PROJECT FILES
# ==================================================

PROJECT = Path(__file__).resolve().parent.parent
CONFIG = PROJECT / "config"
RAW = PROJECT / "data" / "raw" / "iasc" / "scaleup"
PROCESSED = PROJECT / "data" / "processed"

CONFIG.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)

COUNTRIES_FILE = CONFIG / "countries.csv"
OVERRIDES_FILE = CONFIG / "iasc_scaleup_overrides.csv"

CURRENT_OUTPUT = PROJECT / "iasc_scaleup_current.csv"
EVIDENCE_OUTPUT = PROCESSED / "iasc_scaleup_evidence.csv"
UNMATCHED_OUTPUT = PROCESSED / "iasc_scaleup_unmatched.csv"
METADATA_OUTPUT = PROCESSED / "iasc_scaleup_metadata.json"


# ==================================================
# COMMON HELPERS
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
        .replace("/", " ")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("â€™", "'")
        .replace("â€˜", "'")
        .replace("â€“", " ")
        .replace("â€”", " ")
        .split()
    )


def normalize_iso3(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    return text if len(text) == 3 and text.isalpha() else None


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_date(value):
    if not value:
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return pd.NaT
    return parsed.tz_convert(None).normalize()


def date_to_text(value):
    if pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def require_file(path, label):
    if not path.exists():
        raise FileNotFoundError(f"{label} not found:\n{path}")


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def request_page(session, url):
    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=True,
    )

    if not 200 <= response.status_code < 300:
        raise RuntimeError(
            f"IASC request failed: HTTP {response.status_code}\n{url}"
        )

    if not response.text or len(response.text.strip()) < 500:
        raise RuntimeError(
            "IASC returned a successful HTTP response but the page body "
            f"was unexpectedly empty or incomplete.\n"
            f"HTTP: {response.status_code}\n"
            f"URL: {response.url}"
        )

    return response


# ==================================================
# COUNTRY MAPPING
# ==================================================

def load_country_mapping():
    require_file(COUNTRIES_FILE, "CERF country mapping")
    mapping = pd.read_csv(COUNTRIES_FILE, encoding="utf-8-sig", low_memory=False)
    required = ["ISO3", "CERF_Country"]
    missing = [column for column in required if column not in mapping.columns]
    if missing:
        raise RuntimeError(f"countries.csv is missing: {missing}")

    mapping["ISO3"] = mapping["ISO3"].apply(normalize_iso3)
    mapping = mapping[mapping["ISO3"].notna()].copy()

    universe = (
        mapping[["ISO3", "CERF_Country"]]
        .drop_duplicates("ISO3")
        .reset_index(drop=True)
    )
    if len(universe) != EXPECTED_COUNTRIES:
        raise RuntimeError(
            f"Country universe contains {len(universe)} rows; expected {EXPECTED_COUNTRIES}."
        )

    aliases = universe.copy()
    aliases["Source_Alias"] = aliases["CERF_Country"]
    if "Source_Alias" in mapping.columns:
        aliases = pd.concat(
            [aliases, mapping[["ISO3", "CERF_Country", "Source_Alias"]]],
            ignore_index=True,
        )
    aliases["Normalized_Alias"] = aliases["Source_Alias"].apply(normalize_text)
    aliases = aliases[aliases["Normalized_Alias"].ne("")].drop_duplicates(
        ["ISO3", "Normalized_Alias"]
    )
    return universe, aliases


SPECIAL_ALIASES = {
    "drc": ["COD"],
    "dr congo": ["COD"],
    "democratic republic of congo": ["COD"],
    "democratic republic of the congo": ["COD"],
    "occupied palestinian territory": ["PSE"],
    "palestine": ["PSE"],
    "opt": ["PSE"],
    "south sudan": ["SSD"],
    "central african republic": ["CAF"],
}


def identify_countries(text, aliases):
    normalized = normalize_text(text)
    matches = {}

    # Longest aliases first to reduce accidental substring matches.
    ordered = aliases.sort_values(
        "Normalized_Alias", key=lambda s: s.str.len(), ascending=False
    )
    for _, row in ordered.iterrows():
        alias = row["Normalized_Alias"]
        if len(alias) < 4:
            continue
        if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", normalized):
            matches[row["ISO3"]] = row["CERF_Country"]

    country_lookup = aliases.drop_duplicates("ISO3").set_index("ISO3")[
        "CERF_Country"
    ].to_dict()
    for alias, iso3_values in SPECIAL_ALIASES.items():
        if re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", normalized):
            for iso3 in iso3_values:
                if iso3 in country_lookup:
                    matches[iso3] = country_lookup[iso3]

    return matches


# ==================================================
# DISCOVER RELEVANT IASC PAGES
# ==================================================

def discover_resource_links(session):
    """
    Discover IASC Scale-Up resources using a real Chromium browser.

    The IASC resources listing can return HTTP 202 to ordinary requests.
    Browser rendering gets the completed page instead.
    """

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for IASC resource discovery. "
            "Install it with: python -m pip install playwright"
        ) from exc

    links = {}

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            )
        )

        page = context.new_page()

        for page_number in range(MAX_RESOURCE_PAGES):

            separator = (
                "&"
                if "?" in IASC_RESOURCES_URL
                else "?"
            )

            url = (
                f"{IASC_RESOURCES_URL}"
                f"{separator}page={page_number}"
            )

            print(
                f"Scanning IASC resources page "
                f"{page_number + 1}..."
            )

            try:

                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=120000,
                )

                page.wait_for_timeout(
                    5000
                )

                html_text = page.content()

            except Exception as exc:

                print(
                    f"Warning: could not render "
                    f"resources page {page_number + 1}: "
                    f"{exc}"
                )

                continue

            raw_page = (
                RAW
                /
                f"iasc_resources_page_{page_number}.html"
            )

            raw_page.write_text(
                html_text,
                encoding="utf-8",
            )

            soup = BeautifulSoup(
                html_text,
                "html.parser",
            )

            found_on_page = 0

            for anchor in soup.find_all(
                "a",
                href=True,
            ):

                title = clean_text(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )

                href = urljoin(
                    page.url,
                    anchor["href"],
                )

                combined = normalize_text(
                    title
                    + " "
                    + href
                )

                if any(
                    phrase in combined
                    for phrase in SEARCH_PHRASES
                ):

                    links[href] = (
                        title
                        or
                        href
                    )

                    found_on_page += 1

            if (
                page_number > 0
                and
                found_on_page == 0
                and
                links
            ):

                break

        browser.close()

    if not links:

        raise RuntimeError(
            "No IASC Scale-Up activation/"
            "deactivation pages were discovered "
            "after browser rendering."
        )

    return [
        {
            "URL": url,
            "Title": title,
        }

        for url, title
        in links.items()
    ]

# ==================================================
# PAGE PARSING
# ==================================================

DATE_TEXT = r"(?:\d{1,2}\s+)?(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}"


def extract_published_date(soup):
    for element in soup.find_all("time"):
        candidate = element.get("datetime") or element.get_text(" ", strip=True)
        parsed = parse_date(candidate)
        if not pd.isna(parsed):
            return parsed
    text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"Published Date\s+(" + DATE_TEXT + r")", text, re.I)
    return parse_date(match.group(1)) if match else pd.NaT


def extract_first_date(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            parsed = parse_date(match.group(1))
            if not pd.isna(parsed):
                return parsed
    return pd.NaT


def infer_dates(title, text, published_date):
    full = clean_text(title + " " + text)

    activation = extract_first_date(full, [
        r"(?:activated|activation (?:takes effect|effective)|with effect from|effective from|effective)\s+(?:on\s+)?(" + DATE_TEXT + r")",
        r"(?:on)\s+(" + DATE_TEXT + r")[^.]*(?:activated|activation)",
    ])
    if pd.isna(activation) and "activat" in normalize_text(full):
        activation = published_date

    deactivation = extract_first_date(full, [
        r"(?:deactivated|deactivation (?:takes effect|effective)|deactivate(?:d)? (?:on|from)|ended on|expired on)\s+(" + DATE_TEXT + r")",
        r"(?:until|through)\s+(" + DATE_TEXT + r")",
    ])

    explicit_end = extract_first_date(full, [
        r"(?:extended until|extension until|remain(?:s)? in effect until|active until|in place until)\s+(" + DATE_TEXT + r")",
        r"(?:for the period ending|end date)\s+(" + DATE_TEXT + r")",
    ])

    duration_months = None

    # IASC announcements may express the duration either numerically
    # ("3 months") or in words ("three months").
    number_words = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
    }

    duration_match = re.search(
        r"(?:initial\s+period|period)\s+of\s+"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
        r"\s+months?",
        full,
        flags=re.I,
    )

    if duration_match:

        duration_value = (
            duration_match
            .group(1)
            .lower()
        )

        if duration_value.isdigit():
            duration_months = int(
                duration_value
            )
        else:
            duration_months = number_words.get(
                duration_value
            )

    end_date = explicit_end

    if (
        pd.isna(end_date)
        and
        not pd.isna(deactivation)
    ):
        end_date = deactivation

    if (
        pd.isna(end_date)
        and
        not pd.isna(activation)
        and
        duration_months is not None
    ):
        end_date = (
            activation
            + pd.DateOffset(
                months=duration_months
            )
        )

    return activation, deactivation, end_date, duration_months


def classify_action(title, text):
    """
    Classify the formal action.

    The resource title is authoritative. This prevents related links,
    navigation, and historical Scale-Up material elsewhere on the page
    from changing an Activation into a Deactivation.
    """

    normalized_title = normalize_text(title)

    if (
        "deactivation" in normalized_title
        or
        "deactivated" in normalized_title
    ):
        return "Deactivation"

    if (
        "extension" in normalized_title
        or
        "extended" in normalized_title
    ):
        return "Extension"

    if (
        "activation" in normalized_title
        or
        "activated" in normalized_title
    ):
        return "Activation"

    normalized_text = normalize_text(text)

    if "deactivated" in normalized_text:
        return "Deactivation"

    if "extended until" in normalized_text:
        return "Extension"

    if "has activated" in normalized_text:
        return "Activation"

    return "Scale-Up Update"


def classify_type(text):
    normalized = normalize_text(text)
    if "infectious disease" in normalized or "ebola" in normalized:
        return "Control of Infectious Disease Events"
    if "sudden onset" in normalized:
        return "Sudden-Onset Emergency"
    return "Humanitarian System-Wide Scale-Up"


def parse_resource_page(session, item, aliases):
    """
    Render an individual IASC Scale-Up resource with Chromium.

    Ordinary requests to the IASC site can return a JavaScript-disabled
    shell, so individual evidence pages must be browser rendered too.
    """

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for IASC resource rendering."
        ) from exc

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            )
        )

        page = context.new_page()

        page.goto(
            item["URL"],
            wait_until="domcontentloaded",
            timeout=120000,
        )

        # The IASC site can redirect/re-render after DOMContentLoaded.
        # Wait for the page to settle before reading the final DOM.
        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=30000,
            )
        except Exception:
            pass

        page.wait_for_timeout(
            5000
        )

        # page.content() can fail if the IASC page begins one last
        # navigation. Retry several times before failing.
        html_text = None

        for attempt in range(5):
            try:
                page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=30000,
                )

                page.wait_for_timeout(
                    1500
                )

                html_text = page.content()

                if (
                    html_text
                    and
                    len(html_text) > 1000
                ):
                    break

            except Exception:
                page.wait_for_timeout(
                    2000
                )

        if not html_text:
            raise RuntimeError(
                "Browser rendered the IASC resource but "
                "could not capture the final settled HTML."
            )

        final_url = page.url

        browser.close()

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    # Remove page furniture, but preserve the article content.
    for tag in soup(
        [
            "script",
            "style",
            "svg",
            "nav",
            "footer",
        ]
    ):
        tag.decompose()

    title_element = soup.find("h1")

    if title_element is not None:

        page_title = clean_text(
            title_element.get_text(
                " ",
                strip=True,
            )
        )

    else:

        page_title = clean_text(
            item["Title"]
        )

    # If an H1 still contains the site's JS fallback text,
    # use the title discovered from the resource listing.
    if (
        not page_title
        or
        "javascript is disabled"
        in normalize_text(page_title)
    ):

        page_title = clean_text(
            item["Title"]
        )

    body_text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    published_date = extract_published_date(
        soup
    )

    action = classify_action(
        page_title,
        body_text,
    )

    scaleup_type = classify_type(
        page_title
        + " "
        + body_text
    )

    (
        activation,
        deactivation,
        end_date,
        duration_months,
    ) = infer_dates(
        page_title,
        body_text,
        published_date,
    )

    normalized_title = normalize_text(
        page_title
    )

    is_master_status_page = (
        "iasc humanitarian system wide scale up activations and deactivations"
        in normalized_title
    )

    if is_master_status_page:

        # This is a historical/status index containing multiple
        # activations and deactivations. Do not classify the entire
        # page as a single country event.
        countries = {}

    elif (
        "drc ebola"
        in normalized_title
        or
        (
            "control of infectious disease events"
            in normalized_title
            and
            "drc"
            in normalized_title
        )
    ):

        country_lookup = (
            aliases
            .drop_duplicates("ISO3")
            .set_index("ISO3")[
                "CERF_Country"
            ]
            .to_dict()
        )

        countries = {}

        if "COD" in country_lookup:
            countries["COD"] = country_lookup["COD"]

    else:

        countries = identify_countries(
            page_title
            + " "
            + body_text,
            aliases,
        )

    # Explicit fallback for the IASC terminology used
    # in formal activation announcements.
    normalized_evidence = normalize_text(
        page_title
        + " "
        + body_text
        + " "
        + final_url
    )

    universe_lookup = (
        aliases
        .drop_duplicates("ISO3")
        .set_index("ISO3")[
            "CERF_Country"
        ]
        .to_dict()
    )

    if (
        not is_master_status_page
        and
        (
            "drc"
            in normalized_evidence
            or
            "democratic republic of congo"
            in normalized_evidence
            or
            "democratic republic of the congo"
            in normalized_evidence
        )
        and
        "COD"
        in universe_lookup
    ):

        countries["COD"] = (
            universe_lookup["COD"]
        )

    raw_name = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        page_title,
    ).strip("_")[:80]

    raw_path = (
        RAW
        /
        f"{raw_name or 'iasc_scaleup'}.html"
    )

    raw_path.write_text(
        html_text,
        encoding="utf-8",
    )

    records = []

    for iso3, country in (
        countries.items()
    ):

        records.append(
            {
                "ISO3":
                    iso3,

                "CERF_Country":
                    country,

                "IASC_ScaleUp_Action":
                    action,

                "IASC_ScaleUp_Type":
                    scaleup_type,

                "IASC_ScaleUp_Activation_Date":
                    activation,

                "IASC_ScaleUp_Deactivation_Date":
                    deactivation,

                "IASC_ScaleUp_End_Date":
                    end_date,

                "IASC_ScaleUp_Initial_Duration_Months":
                    duration_months,

                "IASC_ScaleUp_Source_Title":
                    page_title,

                "IASC_ScaleUp_Source_URL":
                    final_url,

                "IASC_ScaleUp_Published_Date":
                    published_date,

                "IASC_ScaleUp_Evidence_Text":
                    body_text[:3000],

                "IASC_ScaleUp_Detection":
                    "Browser-rendered public IASC resource page",
            }
        )

    unmatched = None

    if not records:

        unmatched = {
            "Source_Title":
                page_title,

            "Source_URL":
                final_url,

            "Published_Date":
                published_date,

            "Action":
                action,

            "Reason":
                (
                    "Resource rendered successfully, "
                    "but no CERF country could be "
                    "identified."
                ),
        }

    return (
        records,
        unmatched,
    )

# ==================================================
# OVERRIDES
# ==================================================

def ensure_override_template():
    if OVERRIDES_FILE.exists():
        return
    pd.DataFrame(columns=[
        "ISO3",
        "Active",
        "Activation_Date",
        "End_Date",
        "ScaleUp_Type",
        "Source_URL",
        "Note",
    ]).to_csv(OVERRIDES_FILE, index=False, encoding="utf-8-sig")




def load_overrides():
    """
    Dynamically read CURRENT active Scale-Ups from the authoritative
    IASC Humanitarian System-Wide Scale-Up Activations and
    Deactivations page.

    The page's 'Currently Active Scale-Ups' section is authoritative.
    Parsing stops when the 'Deactivated/Expired Scale-Ups' heading
    is reached.

    The function retains the existing override interface so the rest
    of the collector does not need to change.
    """

    master_url = (
        "https://interagencystandingcommittee.org/"
        "iasc-humanitarian-system-wide-scale-"
        "activations-and-deactivations"
    )

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required for live IASC status retrieval."
        ) from exc

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=True,
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            )
        )

        page = context.new_page()

        page.goto(
            master_url,
            wait_until="domcontentloaded",
            timeout=120000,
        )

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=30000,
            )
        except Exception:
            pass

        page.wait_for_timeout(5000)

        html_text = None

        for attempt in range(5):

            try:

                html_text = page.content()

                if html_text and len(html_text) > 1000:
                    break

            except Exception:

                page.wait_for_timeout(2000)

        final_url = page.url

        browser.close()

    if not html_text:

        raise RuntimeError(
            "Could not capture the authoritative IASC "
            "Activations and Deactivations page."
        )

    raw_path = (
        RAW
        /
        "iasc_authoritative_scaleup_status.html"
    )

    raw_path.write_text(
        html_text,
        encoding="utf-8",
    )

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    universe, aliases = load_country_mapping()

    country_lookup = (
        universe
        .set_index("ISO3")[
            "CERF_Country"
        ]
        .to_dict()
    )

    #
    # Find the formal "Currently Active Scale-Ups" heading.
    #
    active_heading = None

    for heading in soup.find_all(
        [
            "h1",
            "h2",
            "h3",
        ]
    ):

        heading_text = normalize_text(
            heading.get_text(
                " ",
                strip=True,
            )
        )

        if (
            "currently active scale ups"
            in heading_text
        ):

            active_heading = heading
            break

    if active_heading is None:

        raise RuntimeError(
            "The authoritative IASC page was retrieved, "
            "but the 'Currently Active Scale-Ups' section "
            "could not be found. Refusing to infer that "
            "there are zero active Scale-Ups."
        )

    active_records = {}

    current = active_heading.find_next_sibling()

    while current is not None:

        #
        # Stop as soon as the deactivated/expired section begins.
        #
        if current.name in {
            "h1",
            "h2",
        }:

            section_name = normalize_text(
                current.get_text(
                    " ",
                    strip=True,
                )
            )

            if (
                "deactivated"
                in section_name
                or
                "expired"
                in section_name
                or
                "former"
                in section_name
            ):
                break

        #
        # Each active response is represented by an H3 followed
        # by its descriptive list/text.
        #
        if current.name == "h3":

            source_name = clean_text(
                current.get_text(
                    " ",
                    strip=True,
                )
            )

            detail_parts = []

            sibling = current.find_next_sibling()

            while sibling is not None:

                if sibling.name in {
                    "h1",
                    "h2",
                    "h3",
                }:
                    break

                detail_text = clean_text(
                    sibling.get_text(
                        " ",
                        strip=True,
                    )
                )

                if detail_text:
                    detail_parts.append(
                        detail_text
                    )

                sibling = sibling.find_next_sibling()

            detail = clean_text(
                " ".join(
                    detail_parts
                )
            )

            evidence_text = clean_text(
                source_name
                + " "
                + detail
            )

            normalized_name = normalize_text(
                source_name
            )

            #
            # Resolve DRC before generic alias matching.
            #
            # "Democratic Republic of the Congo" contains the word
            # "Congo", which would otherwise incorrectly match both:
            #
            #   COD = Democratic Republic of the Congo
            #   COG = Republic of the Congo
            #
            # If the formal IASC heading identifies DRC, map exclusively
            # to COD.
            #
            if (
                "democratic republic of the congo"
                in normalized_name
                or
                "democratic republic of congo"
                in normalized_name
                or
                normalized_name.startswith("drc ")
                or
                normalized_name.startswith("drc (")
            ):

                countries = {}

                if "COD" in country_lookup:
                    countries["COD"] = country_lookup["COD"]

            else:

                countries = identify_countries(
                    source_name,
                    aliases,
                )

            if not countries:

                raise RuntimeError(
                    "An active IASC Scale-Up entry could "
                    "not be mapped to a CERF country:\n"
                    f"{source_name}"
                )

            #
            # Activation date.
            #
            activation_date = pd.NaT

            activation_patterns = [
                r"activated\s+(?:from|on)\s+"
                r"(\d{1,2}\s+"
                r"(?:January|February|March|April|May|June|"
                r"July|August|September|October|November|December)"
                r"(?:\s+20\d{2})?)",

                r"activation\s+(?:from|on)\s+"
                r"(\d{1,2}\s+"
                r"(?:January|February|March|April|May|June|"
                r"July|August|September|October|November|December)"
                r"(?:\s+20\d{2})?)",
            ]

            for pattern in activation_patterns:

                match = re.search(
                    pattern,
                    detail,
                    flags=re.IGNORECASE,
                )

                if match:

                    date_text = match.group(1)

                    #
                    # The current page has "activated from 9 June"
                    # while its publication date supplies 2026.
                    #
                    if not re.search(
                        r"20\d{2}",
                        date_text,
                    ):

                        page_date_element = soup.find(
                            "time"
                        )

                        page_date = pd.NaT

                        if page_date_element is not None:

                            page_date = parse_date(
                                page_date_element.get(
                                    "datetime"
                                )
                                or
                                page_date_element.get_text(
                                    " ",
                                    strip=True,
                                )
                            )

                        if not pd.isna(
                            page_date
                        ):

                            date_text = (
                                date_text
                                + " "
                                + str(
                                    page_date.year
                                )
                            )

                    activation_date = parse_date(
                        date_text
                    )

                    break

            #
            # Extension/current end date.
            #
            end_date = pd.NaT

            end_patterns = [
                r"extended\s+until\s+"
                r"(\d{1,2}\s+"
                r"(?:January|February|March|April|May|June|"
                r"July|August|September|October|November|December)"
                r"\s+20\d{2})",

                r"active\s+until\s+"
                r"(\d{1,2}\s+"
                r"(?:January|February|March|April|May|June|"
                r"July|August|September|October|November|December)"
                r"\s+20\d{2})",
            ]

            for pattern in end_patterns:

                match = re.search(
                    pattern,
                    detail,
                    flags=re.IGNORECASE,
                )

                if match:

                    end_date = parse_date(
                        match.group(1)
                    )

                    break

            scaleup_type = classify_type(
                evidence_text
            )

            for iso3, country in countries.items():

                active_records[
                    iso3
                ] = {
                    "ISO3":
                        iso3,

                    "Active":
                        True,

                    "Activation_Date":
                        activation_date,

                    "End_Date":
                        end_date,

                    "ScaleUp_Type":
                        scaleup_type,

                    "Source_URL":
                        final_url,

                    "Note":
                        (
                            "Dynamically parsed from the "
                            "'Currently Active Scale-Ups' "
                            "section of the authoritative "
                            "IASC status page. Source entry: "
                            + evidence_text
                        ),
                }

        current = current.find_next_sibling()

    if not active_records:

        raise RuntimeError(
            "The authoritative IASC page contains a "
            "'Currently Active Scale-Ups' section, but "
            "no active country records were parsed. "
            "Refusing to return a false zero."
        )

    result = pd.DataFrame(
        active_records.values()
    )

    result["ISO3"] = result[
        "ISO3"
    ].apply(
        normalize_iso3
    )

    result["Active"] = True

    result[
        "Activation_Date"
    ] = pd.to_datetime(
        result[
            "Activation_Date"
        ],
        errors="coerce",
    )

    result[
        "End_Date"
    ] = pd.to_datetime(
        result[
            "End_Date"
        ],
        errors="coerce",
    )

    print()
    print(
        "Authoritative IASC active Scale-Ups:"
    )

    print(
        result[
            [
                "ISO3",
                "Activation_Date",
                "End_Date",
                "ScaleUp_Type",
            ]
        ].to_string(
            index=False
        )
    )

    return result


# ==================================================
# RESOLVE CURRENT STATUS
# ==================================================

def resolve_country_status(country_events, as_of_date):
    if country_events.empty:
        return {
            "IASC_ScaleUp_Active": False,
            "IASC_ScaleUp_Score": pd.NA,
            "IASC_ScaleUp_Status": "No active public Scale-Up identified",
        }

    events = country_events.copy()
    events["Sort_Date"] = events["IASC_ScaleUp_Published_Date"].fillna(
        events["IASC_ScaleUp_Activation_Date"]
    )
    events = events.sort_values("Sort_Date")

    latest = events.iloc[-1]
    action = latest["IASC_ScaleUp_Action"]
    activation = latest["IASC_ScaleUp_Activation_Date"]
    deactivation = latest["IASC_ScaleUp_Deactivation_Date"]
    end_date = latest["IASC_ScaleUp_End_Date"]

    active = action != "Deactivation"
    if not pd.isna(activation) and activation > as_of_date:
        active = False
    if not pd.isna(deactivation) and deactivation <= as_of_date:
        active = False
    if not pd.isna(end_date) and end_date < as_of_date:
        active = False

    status = "Active System-Wide Scale-Up" if active else "Inactive or expired Scale-Up"
    return {
        "IASC_ScaleUp_Active": bool(active),
        "IASC_ScaleUp_Score": 100.0 if active else pd.NA,
        "IASC_ScaleUp_Status": status,
        "IASC_ScaleUp_Action": action,
        "IASC_ScaleUp_Type": latest["IASC_ScaleUp_Type"],
        "IASC_ScaleUp_Activation_Date": activation,
        "IASC_ScaleUp_Deactivation_Date": deactivation,
        "IASC_ScaleUp_End_Date": end_date,
        "IASC_ScaleUp_Source_Title": latest["IASC_ScaleUp_Source_Title"],
        "IASC_ScaleUp_Source_URL": latest["IASC_ScaleUp_Source_URL"],
        "IASC_ScaleUp_Published_Date": latest["IASC_ScaleUp_Published_Date"],
        "IASC_ScaleUp_Detection": latest["IASC_ScaleUp_Detection"],
    }


def apply_overrides(current, overrides):
    if overrides.empty:
        return current

    current = current.copy()
    for _, override in overrides.iterrows():
        mask = current["ISO3"].eq(override["ISO3"])
        if not mask.any():
            continue
        active = bool(override["Active"])
        current.loc[mask, "IASC_ScaleUp_Active"] = active
        current.loc[mask, "IASC_ScaleUp_Score"] = 100.0 if active else pd.NA
        current.loc[mask, "IASC_ScaleUp_Status"] = (
            "Active System-Wide Scale-Up (manual audited override)"
            if active else "Inactive Scale-Up (manual audited override)"
        )
        current.loc[mask, "IASC_ScaleUp_Activation_Date"] = override["Activation_Date"]
        current.loc[mask, "IASC_ScaleUp_End_Date"] = override["End_Date"]
        current.loc[mask, "IASC_ScaleUp_Type"] = override.get("ScaleUp_Type")
        current.loc[mask, "IASC_ScaleUp_Source_URL"] = override.get("Source_URL")
        current.loc[mask, "IASC_ScaleUp_Detection"] = "Manual audited override"
        current.loc[mask, "IASC_ScaleUp_Override_Note"] = override.get("Note")
    return current


# ==================================================
# VALIDATION AND SAVE
# ==================================================

def validate(current):
    problems = []
    if len(current) != EXPECTED_COUNTRIES:
        problems.append(f"Output has {len(current)} countries; expected {EXPECTED_COUNTRIES}.")
    if current["ISO3"].duplicated().any():
        problems.append("Duplicate ISO3 rows detected.")
    active_scores = current.loc[current["IASC_ScaleUp_Active"], "IASC_ScaleUp_Score"]
    if not active_scores.eq(100.0).all():
        problems.append("Every active Scale-Up must have score 100.")
    inactive_scores = current.loc[~current["IASC_ScaleUp_Active"], "IASC_ScaleUp_Score"]
    if inactive_scores.notna().any():
        problems.append("Inactive countries must have a blank override score, not zero.")
    if problems:
        print("\nIASC SCALE-UP VALIDATION FAILED")
        for problem in problems:
            print(f"- {problem}")
        raise RuntimeError("IASC Scale-Up validation failed.")
    print("\nIASC SCALE-UP VALIDATION PASSED")


def save_outputs(current, evidence, unmatched, as_of_date, resource_count):
    date_columns = [
        "IASC_ScaleUp_Activation_Date",
        "IASC_ScaleUp_Deactivation_Date",
        "IASC_ScaleUp_End_Date",
        "IASC_ScaleUp_Published_Date",
    ]
    current_save = current.copy()
    evidence_save = evidence.copy()
    unmatched_save = unmatched.copy()

    for frame in [current_save, evidence_save]:
        for column in date_columns:
            if column in frame.columns:
                frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.strftime(
                    "%Y-%m-%d"
                )

    if "Published_Date" in unmatched_save.columns:
        unmatched_save["Published_Date"] = pd.to_datetime(
            unmatched_save["Published_Date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")

    current_save.to_csv(CURRENT_OUTPUT, index=False, encoding="utf-8-sig")
    evidence_save.to_csv(EVIDENCE_OUTPUT, index=False, encoding="utf-8-sig")
    unmatched_save.to_csv(UNMATCHED_OUTPUT, index=False, encoding="utf-8-sig")

    metadata = {
        "source": "IASC public website",
        "source_listing": IASC_RESOURCES_URL,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "status_as_of": as_of_date.strftime("%Y-%m-%d"),
        "resources_discovered": int(resource_count),
        "evidence_records": int(len(evidence_save)),
        "active_scaleups": int(current_save["IASC_ScaleUp_Active"].sum()),
        "method": (
            "Discover public IASC Scale-Up activation, extension and deactivation resources; "
            "resolve status by country as of the run date; assign 100 only to active Scale-Ups."
        ),
        "scoring": (
            "Active IASC System-Wide Scale-Up = 100 override. Countries without an active "
            "Scale-Up remain blank, not zero."
        ),
        "override_file": str(OVERRIDES_FILE),
    }
    METADATA_OUTPUT.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ==================================================
# COMPLETE UPDATE
# ==================================================

def update_iasc_scaleup():
    print("Loading IASC System-Wide Scale-Up status...")
    as_of_date = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()

    universe, aliases = load_country_mapping()
    session = create_session()
    resources = discover_resource_links(session)
    print(f"Relevant public IASC resources discovered: {len(resources)}")

    records = []
    unmatched_records = []
    for item in resources:
        try:
            parsed, unmatched = parse_resource_page(session, item, aliases)
            records.extend(parsed)
            if unmatched:
                unmatched_records.append(unmatched)
        except Exception as exc:
            unmatched_records.append({
                "Source_Title": item["Title"],
                "Source_URL": item["URL"],
                "Reason": f"Page parsing failed: {exc}",
            })

    evidence_columns = [
        "ISO3", "CERF_Country", "IASC_ScaleUp_Action", "IASC_ScaleUp_Type",
        "IASC_ScaleUp_Activation_Date", "IASC_ScaleUp_Deactivation_Date",
        "IASC_ScaleUp_End_Date", "IASC_ScaleUp_Initial_Duration_Months",
        "IASC_ScaleUp_Source_Title", "IASC_ScaleUp_Source_URL",
        "IASC_ScaleUp_Published_Date", "IASC_ScaleUp_Evidence_Text",
        "IASC_ScaleUp_Detection",
    ]
    evidence = pd.DataFrame(records, columns=evidence_columns)
    unmatched = pd.DataFrame(unmatched_records)

    output_rows = []
    for _, country in universe.iterrows():
        country_events = evidence[evidence["ISO3"].eq(country["ISO3"])]
        status = resolve_country_status(country_events, as_of_date)
        output_rows.append({
            "ISO3": country["ISO3"],
            "CERF_Country": country["CERF_Country"],
            **status,
        })

    current = pd.DataFrame(output_rows)
    if "IASC_ScaleUp_Override_Note" not in current.columns:
        current["IASC_ScaleUp_Override_Note"] = None

    current = apply_overrides(current, load_overrides())
    current["IASC_ScaleUp_As_Of_Date"] = as_of_date

    validate(current)
    save_outputs(current, evidence, unmatched, as_of_date, len(resources))
    return current, evidence, unmatched


if __name__ == "__main__":
    current, evidence, unmatched = update_iasc_scaleup()

    print("\n" + "=" * 70)
    print("IASC SCALE-UP UPDATE COMPLETE")
    print("=" * 70)
    print(f"Countries in output: {len(current)}")
    print(f"Evidence records: {len(evidence)}")
    print(f"Unmatched/ambiguous resources: {len(unmatched)}")
    print(f"Active Scale-Ups: {int(current['IASC_ScaleUp_Active'].sum())}")

    active = current[current["IASC_ScaleUp_Active"]].copy()
    print("\nActive IASC System-Wide Scale-Ups:\n")
    if active.empty:
        print("None identified from public resources as of this run.")
    else:
        columns = [
            "CERF_Country", "ISO3", "IASC_ScaleUp_Score",
            "IASC_ScaleUp_Activation_Date", "IASC_ScaleUp_End_Date",
            "IASC_ScaleUp_Type", "IASC_ScaleUp_Source_Title",
        ]
        print(active[columns].to_string(index=False))

    print(f"\nCurrent output:\n{CURRENT_OUTPUT}")
    print(f"\nEvidence:\n{EVIDENCE_OUTPUT}")
    print(f"\nUnmatched resources:\n{UNMATCHED_OUTPUT}")
    print(f"\nMetadata:\n{METADATA_OUTPUT}")






