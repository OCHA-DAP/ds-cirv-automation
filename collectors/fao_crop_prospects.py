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



FAO_REPORT_SERIES_PAGE = (

    "https://www.fao.org/giews/reports/"

    "crop-prospects/en/"

)



USER_AGENT = (

    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "

    "AppleWebKit/537.36 "

    "(KHTML, like Gecko) "

    "Chrome/130.0 Safari/537.36"

)





# ==================================================

# PROJECT FILES

# ==================================================



project_folder = Path(__file__).parent.parent



raw_folder = (

    project_folder

    / "data"

    / "raw"

    / "fao_crop_prospects"

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

    / "latest_fao_report.json"

)



current_output_csv = (

    project_folder

    / "fao_crop_prospects_current.csv"

)



current_evidence_file = (

    raw_folder

    / "FAO_Crop_Prospects_current_evidence.txt"

)



validation_pdf = (

    raw_folder

    / "FAO_Crop_Prospects_July_2026.pdf"

)





# ==================================================

# NORMALIZE TEXT

# ==================================================



def normalize_text(value):

    """

    Normalize country names and category text.



    Handles:



    - accents

    - punctuation

    - apostrophe variants

    - capitalization

    - repeated spaces

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

    """

    Create a browser-like HTTP session.



    FAO Open Knowledge may reject requests that do

    not contain normal browser headers.

    """



    session = requests.Session()



    session.headers.update(

        {

            "User-Agent": USER_AGENT,

            "Accept": (

                "text/html,application/xhtml+xml,"

                "application/xml;q=0.9,"

                "application/pdf;q=0.8,*/*;q=0.7"

            ),

            "Accept-Language": "en-US,en;q=0.9",

        }

    )



    return session





# ==================================================

# FILE HASH

# ==================================================



def calculate_file_hash(file_path):



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

# DISCOVER LATEST FAO REPORT

# ==================================================



def discover_latest_report():

    """

    Visit the official FAO GIEWS series page and

    discover the newest English Crop Prospects

    report.



    The official page lists reports newest first.

    Each newer report has a stable DOI.

    """



    print(

        "Checking FAO GIEWS for the latest "

        "Crop Prospects report..."

    )



    session = create_session()



    response = session.get(

        FAO_REPORT_SERIES_PAGE,

        timeout=60,

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



        title = " ".join(

            link.get_text(

                " ",

                strip=True,

            ).split()

        )



        href = link["href"]



        title_lower = title.lower()

        href_lower = href.lower()



        if (

            "crop prospects and food situation"

            not in title_lower

        ):

            continue



        if (

            "doi.org/10.4060/"

            not in href_lower

            and

            "fao.org/documents/card/"

            not in href_lower

        ):

            continue



        full_url = urljoin(

            FAO_REPORT_SERIES_PAGE,

            href,

        )



        report_number_match = re.search(

            r"no\.?\s*(\d+)",

            title,

            flags=re.IGNORECASE,

        )



        report_number = None



        if report_number_match:



            report_number = int(

                report_number_match.group(1)

            )



        candidates.append(

            {

                "title": title,

                "report_number": report_number,

                "report_url": full_url,

                "doi_url": (

                    full_url

                    if "doi.org" in full_url.lower()

                    else None

                ),

            }

        )



    if not candidates:



        raise RuntimeError(

            "No English FAO Crop Prospects "

            "reports were discovered."

        )



    latest = candidates[0]



    latest["report_code"] = (

        latest["report_url"]

        .rstrip("/")

        .split("/")[-1]

    )



    print()

    print(

        "Latest FAO report discovered:"

    )



    print(

        latest["title"]

    )



    print(

        latest["report_url"]

    )



    return latest





# ==================================================

# READ PREVIOUS REPORT METADATA

# ==================================================



def read_previous_metadata():



    if not metadata_file.exists():



        return None



    try:



        return json.loads(

            metadata_file.read_text(

                encoding="utf-8"

            )

        )



    except Exception:



        return None





# ==================================================

# SAVE REPORT METADATA

# ==================================================



def save_metadata(

    report,

    pdf_path,

    results,

):



    metadata = {
        "report_period": report.get("report_period"),
        "publication_period_source": report.get("publication_period_source"),

        "title":

            report.get("title"),



        "report_number":

            report.get("report_number"),



        "report_url":

            report.get("report_url"),



        "doi_url":

            report.get("doi_url"),



        "report_code":

            report.get("report_code"),



        "resolved_landing_url":

            report.get(

                "resolved_landing_url"

            ),



        "pdf_url":

            report.get("pdf_url"),



        "pdf_file":

            pdf_path.name,



        "pdf_sha256":

            calculate_file_hash(

                pdf_path

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

# CHECK WHETHER REPORT IS NEW

# ==================================================



def is_new_report(report):



    previous = read_previous_metadata()



    if previous is None:



        return True



    previous_code = previous.get(

        "report_code"

    )



    current_code = report.get(

        "report_code"

    )



    return (

        previous_code

        != current_code

    )





# ==================================================

# FIND PDF LINK FROM REPORT PAGE

# ==================================================




def _http_fao_pdf(report):
    """Discover the PDF through publication links and repository bundles."""
    import re
    from urllib.parse import urljoin, urlsplit
    from bs4 import BeautifulSoup

    session = create_session()
    candidates = []
    item_ids = set()
    errors = []
    landing = report["report_url"]

    def fetch(url):
        response = session.get(
            url, timeout=(20, 90), allow_redirects=True
        )
        response.raise_for_status()
        return response

    def inspect_html(response):
        soup = BeautifulSoup(response.text, "html.parser")
        urls = []

        for tag in soup.find_all("a", href=True):
            urls.append(urljoin(response.url, tag["href"]))

        for tag in soup.find_all("meta"):
            name = (tag.get("name") or tag.get("property") or "").lower()
            if name in ("citation_pdf_url", "dc.identifier.uri"):
                if tag.get("content"):
                    urls.append(urljoin(response.url, tag["content"]))

        for url in urls:
            item_ids.update(re.findall(
                r"/items/([0-9a-fA-F-]{36})(?:/|$|\?)", url
            ))
            if (
                ".pdf" in url.lower()
                or "/bitstreams/" in url.lower()
            ):
                candidates.append(url)

        item_ids.update(re.findall(
            r"/items/([0-9a-fA-F-]{36})(?:/|$|\?)",
            response.url,
        ))

    def embedded(payload, key):
        return payload.get("_embedded", {}).get(key, [])

    def pdf_bytes(response):
        content = response.content
        if content.lstrip().startswith(b"%PDF"):
            content = content.lstrip()
            import pymupdf
            with pymupdf.open(stream=content, filetype="pdf") as doc:
                if doc.page_count < 1:
                    return None
            return content
        return None

    print("Resolving FAO PDF through publication and repository links:",
          landing, flush=True)

    response = fetch(landing)
    direct = pdf_bytes(response)
    if direct is not None:
        report["pdf_url"] = response.url
        return response.url, direct

    report["resolved_landing_url"] = response.url
    inspect_html(response)

    origin = "{0.scheme}://{0.netloc}".format(urlsplit(response.url))
    api = origin + "/server/api"

    # The publication's Full item page link supplies the UUID.
    # No report-specific UUID or PDF filename is hard-coded.
    print("Repository item IDs discovered:", len(item_ids), flush=True)

    for item_id in sorted(item_ids):
        try:
            bundles_url = (
                api + "/core/items/" + item_id + "/bundles?size=100"
            )
            bundles = embedded(fetch(bundles_url).json(), "bundles")

            for bundle in bundles:
                if str(bundle.get("name", "")).upper() != "ORIGINAL":
                    continue

                link = bundle.get("_links", {}).get("bitstreams", {})
                bitstreams_url = link.get("href")
                if not bitstreams_url:
                    bundle_id = bundle.get("uuid")
                    if not bundle_id:
                        continue
                    bitstreams_url = (
                        api + "/core/bundles/" + bundle_id + "/bitstreams"
                    )

                next_url = bitstreams_url
                visited = set()

                while next_url and next_url not in visited:
                    visited.add(next_url)
                    payload = fetch(next_url).json()

                    for bitstream in embedded(payload, "bitstreams"):
                        name = str(bitstream.get("name", "")).lower()
                        if not name.endswith(".pdf"):
                            continue

                        content_url = bitstream.get(
                            "_links", {}
                        ).get("content", {}).get("href")

                        if not content_url and bitstream.get("uuid"):
                            content_url = (
                                api + "/core/bitstreams/"
                                + bitstream["uuid"] + "/content"
                            )

                        if content_url:
                            candidates.append(content_url)

                    next_url = payload.get(
                        "_links", {}
                    ).get("next", {}).get("href")

        except Exception as exc:
            errors.append(f"Item {item_id}: {exc}")

    for url in dict.fromkeys(candidates):
        try:
            print("Trying discovered PDF:", url, flush=True)
            downloaded = fetch(url)
            content = pdf_bytes(downloaded)
            if content is not None:
                report["pdf_url"] = downloaded.url
                return downloaded.url, content
        except Exception as exc:
            errors.append(f"PDF candidate: {exc}")

    raise RuntimeError(
        "Automatic FAO download failed. "
        f"Item IDs: {len(item_ids)}; "
        f"PDF candidates: {len(set(candidates))}. "
        + " | ".join(errors[-5:])
    )


def _browser_fao_pdf(report):
    """Render the discovered publication and retrieve its linked PDF."""
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse
    import pymupdf

    def official(url):
        host = (urlparse(url).hostname or "").lower()
        return host == "fao.org" or host.endswith(".fao.org")

    def valid(content):
        if not content.lstrip().startswith(b"%PDF"):
            return False
        try:
            with pymupdf.open(
                stream=content.lstrip(), filetype="pdf"
            ) as document:
                return document.page_count > 0
        except Exception:
            return False

    candidates = []
    captured = []
    diagnostics = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        def capture(response):
            if not official(response.url):
                return
            content_type = response.headers.get(
                "content-type", ""
            ).lower()
            if "application/pdf" in content_type:
                try:
                    content = response.body()
                    if valid(content):
                        captured.append((response.url, content))
                except Exception:
                    pass

        page.on("response", capture)

        try:
            page.goto(
                report["report_url"],
                wait_until="domcontentloaded",
                timeout=120000,
            )

            # Wait for the repository's rendered download controls.
            try:
                page.get_by_text(
                    "Download PDF", exact=False
                ).first.wait_for(state="visible", timeout=45000)
            except Exception:
                pass

            print(
                "Rendered FAO publication:", page.url,
                flush=True,
            )

            links = page.locator("a[href]").evaluate_all(
                """elements => elements.map(a => ({
                    url: a.href,
                    text: (a.innerText || '').trim()
                }))"""
            )

            for link in links:
                url = link["url"]
                label = link["text"].lower()
                if official(url) and (
                    ".pdf" in url.lower()
                    or "/bitstreams/" in url.lower()
                    or "download pdf" in label
                ):
                    candidates.append(url)

            # Retrieve discovered links using the browser's session.
            for url in dict.fromkeys(candidates):
                try:
                    response = context.request.get(
                        url, timeout=120000
                    )
                    content = response.body()
                    if response.ok and valid(content):
                        report["pdf_url"] = response.url
                        return response.url, content
                except Exception as exc:
                    diagnostics.append(str(exc))

            if captured:
                url, content = captured[0]
                report["pdf_url"] = url
                return url, content

            # Some download buttons expose no href.
            button = page.get_by_text(
                "Download PDF", exact=False
            ).first

            if button.count() and button.is_visible():
                try:
                    with page.expect_download(
                        timeout=30000
                    ) as download_info:
                        button.click(timeout=15000)

                    download = download_info.value
                    downloaded_path = download.path()

                    if downloaded_path:
                        content = Path(downloaded_path).read_bytes()
                        if official(download.url) and valid(content):
                            report["pdf_url"] = download.url
                            return download.url, content

                except Exception as exc:
                    diagnostics.append(str(exc))

                # The click may have opened a PDF tab instead.
                page.wait_for_timeout(3000)

                if captured:
                    url, content = captured[0]
                    report["pdf_url"] = url
                    return url, content

                for tab in context.pages:
                    if official(tab.url) and (
                        ".pdf" in tab.url.lower()
                        or "/bitstreams/" in tab.url.lower()
                    ):
                        try:
                            response = context.request.get(
                                tab.url, timeout=120000
                            )
                            content = response.body()
                            if response.ok and valid(content):
                                report["pdf_url"] = response.url
                                return response.url, content
                        except Exception as exc:
                            diagnostics.append(str(exc))

            raise RuntimeError(
                "Browser fallback found no valid PDF. "
                f"Rendered URL: {page.url}; "
                f"discovered download links: {len(candidates)}; "
                f"page title: {page.title()}. "
                + " | ".join(diagnostics[-2:])
            )

        finally:
            browser.close()


def discover_pdf_url(report):
    try:
        return _http_fao_pdf(report)
    except Exception as http_error:
        print(
            "HTTP resolver failed; trying rendered browser:",
            http_error,
            flush=True,
        )
        return _browser_fao_pdf(report)







# ==================================================

# DOWNLOAD LATEST REPORT

# ==================================================



def download_latest_report(report):

    """

    Download the dynamically discovered report.



    If FAO blocks automated retrieval but the report

    is already stored locally, the app uses the local

    copy safely rather than deleting current data.

    """



    report_code = (

        report["report_code"]

    )



    safe_code = re.sub(

        r"[^A-Za-z0-9_-]+",

        "_",

        report_code,

    )



    output_pdf = (

        raw_folder

        / f"FAO_Crop_Prospects_{safe_code}.pdf"

    )



    # Historical compatibility:

    # use the already validated July 2026 file if

    # the current DOI corresponds to ce0480en.

    if (

        report_code.lower()

        == "ce0480en"

        and

        validation_pdf.exists()

    ):



        print()

        print(

            "Using validated July 2026 "

            "FAO report file."

        )



        return validation_pdf



    if output_pdf.exists():



        print()

        print(

            "This FAO report is already "

            "downloaded."

        )



        print(

            f"Using existing file: "

            f"{output_pdf}"

        )



        return output_pdf



    print()

    print(

        "New FAO report detected."

    )



    print(

        "Attempting automatic PDF download..."

    )



    try:



        pdf_url, pdf_content = (

            discover_pdf_url(

                report

            )

        )



    except RuntimeError as error:



        raise RuntimeError(

            f"{error}\n\n"

            "The current validated FAO values "

            "have not been changed. Download the "

            "new official FAO PDF manually into:\n"

            f"{raw_folder}\n"

            "and rerun the collector."

        ) from error



    if not pdf_content.startswith(

        b"%PDF"

    ):



        raise RuntimeError(

            "The downloaded FAO file is not "

            "a valid PDF."

        )



    output_pdf.write_bytes(

        pdf_content

    )



    print(

        "FAO PDF download successful."

    )



    print(

        f"Saved to: {output_pdf}"

    )



    return output_pdf





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

# FAO-SPECIFIC ALIASES

# ==================================================



def add_fao_aliases(mapping):



    extra_aliases = {



        "COD": [

            "Democratic Republic of Congo",

            "Democratic Republic of the Congo",

        ],



        "PSE": [

            "Palestine",

            "State of Palestine",

        ],



        "SYR": [

            "Syrian Arab Republic",

        ],



        "TZA": [

            "United Republic of Tanzania",

        ],



        "CAF": [

            "Central African Republic",

        ],



        "CIV": [

            "Côte d'Ivoire",

            "Cote d'Ivoire",

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



    extra_records = []



    for iso3, aliases in (

        extra_aliases.items()

    ):



        cerf_country = (

            canonical_lookup.get(

                iso3

            )

        )



        if cerf_country is None:



            continue



        for alias in aliases:



            extra_records.append(

                {

                    "ISO3":

                        iso3,



                    "CERF_Country":

                        cerf_country,



                    "Source_Alias":

                        alias,



                    "Normalized_Alias":

                        normalize_text(

                            alias

                        ),

                }

            )



    if extra_records:



        mapping = pd.concat(

            [

                mapping,

                pd.DataFrame(

                    extra_records

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



            "Matched_Alias":

                row["Source_Alias"],

        }



    return lookup





# ==================================================

# EXTRACT PDF PAGES

# ==================================================



def extract_pdf_pages(

    source_pdf,

):



    document = pymupdf.open(

        source_pdf

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

# EXPECTED COUNTRY COUNT

# ==================================================



def detect_expected_country_count(

    page_records,

):

    """

    Read the expected country count from the report.



    Example:

    FAO estimates that 41 countries/territories

    require external assistance for food.

    """



    combined_text = "\n".join(

        record["Text"]

        for record in page_records[:3]

    )



    patterns = [

        (

            r"FAO estimates that\s+"

            r"(\d+)\s+countries"

        ),

        (

            r"countries/territories "

            r"in need of external "

            r"assistance for food\s+"

            r"(\d+)"

        ),

    ]



    for pattern in patterns:



        match = re.search(

            pattern,

            combined_text,

            flags=re.IGNORECASE,

        )



        if match:



            return int(

                match.group(1)

            )



    return None





# ==================================================

# CATEGORY DETECTION

# ==================================================



def detect_category_from_window(

    lines,

    line_index,

):

    """

    Inspect several adjacent lines because FAO

    category headings are often broken across lines.

    """



    combined = " ".join(

        line.strip()

        for line in lines[

            line_index:

            line_index + 4

        ]

        if line.strip()

    )



    normalized = normalize_text(

        combined

    )



    if not normalized:



        return None



    if (

        "exceptional shortfall "

        "in aggregate food"

        in normalized

    ):



        return "Shortfall"



    if (

        "widespread lack of access"

        in normalized

    ):



        return "Access"



    if (

        "severe localized food insecurity"

        in normalized

    ):



        return "Localized"



    return None





# ==================================================

# IDENTIFY COUNTRY HEADING

# ==================================================



def identify_country(

    line,

    country_lookup,

):



    clean_line = str(

        line

    ).strip()



    if not clean_line:



        return None



    if len(clean_line) > 80:



        return None



    if clean_line.startswith(

        (

            "•",

            "-",

            "Source:",

            "Note:",

            "Notes:",

        )

    ):



        return None



    normalized = normalize_text(

        clean_line

    )



    return country_lookup.get(

        normalized

    )





# ==================================================

# FIND ASSISTANCE SECTION PAGES

# ==================================================



def find_assistance_page_range(

    page_records,

):

    """

    Find the real FAO assistance section dynamically.



    Parsing begins on the first page containing the

    Shortfall category and ends before the page named

    Terminology and notes.

    """



    start_page = None

    end_page = None



    for record in page_records:



        normalized = normalize_text(

            record["Text"]

        )



        if not normalized:



            continue



        if (

            start_page is None

            and

            "exceptional shortfall "

            "in aggregate food"

            in normalized

        ):



            start_page = record[

                "Page"

            ]



        if (

            start_page is not None

            and

            "terminology and notes"

            in normalized

        ):



            end_page = (

                record["Page"] - 1

            )



            break



    if start_page is None:



        raise RuntimeError(

            "Could not locate the FAO "

            "external-assistance section."

        )



    if end_page is None:



        end_page = min(

            start_page + 10,

            len(page_records),

        )



    return (

        start_page,

        end_page,

    )





# ==================================================

# PARSE FAO COUNTRIES

# ==================================================



def parse_assistance_countries(

    page_records,

    mapping,

):



    country_lookup = (

        create_country_lookup(

            mapping

        )

    )



    (

        start_page,

        end_page,

    ) = find_assistance_page_range(

        page_records

    )



    print()

    print(

        "FAO assistance section pages:"

    )



    print(

        f"{start_page} to {end_page}"

    )



    observations = []



    current_category = None



    relevant_pages = [

        record

        for record in page_records

        if (

            start_page

            <= record["Page"]

            <= end_page

        )

    ]



    for record in relevant_pages:



        page_number = record[

            "Page"

        ]



        lines = (

            record["Text"]

            .splitlines()

        )



        for line_index, raw_line in enumerate(

            lines

        ):



            line = raw_line.strip()



            if not line:



                continue



            new_category = (

                detect_category_from_window(

                    lines,

                    line_index,

                )

            )



            if new_category:



                current_category = (

                    new_category

                )



                continue



            country = identify_country(

                line,

                country_lookup,

            )



            if country is None:



                continue



            if current_category is None:



                continue



            evidence_lines = []



            for evidence_line in lines[

                line_index:

                line_index + 6

            ]:



                cleaned = (

                    evidence_line.strip()

                )



                if cleaned:



                    evidence_lines.append(

                        cleaned

                    )



            evidence = " | ".join(

                evidence_lines

            )



            observations.append(

                {

                    "ISO3":

                        country["ISO3"],



                    "CERF_Country":

                        country[

                            "CERF_Country"

                        ],



                    "FAO_Country":

                        line,



                    "FAO_Score":

                        2,



                    "FAO_Category":

                        current_category,



                    "PDF_Page":

                        page_number,



                    "Evidence":

                        evidence,



                    "Matched_Alias":

                        country[

                            "Matched_Alias"

                        ],

                }

            )



    results = pd.DataFrame(

        observations

    )



    if results.empty:



        raise RuntimeError(

            "No FAO countries were extracted."

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

            "WARNING: Duplicate FAO "

            "countries extracted:"

        )



        print(

            duplicates[

                [

                    "CERF_Country",

                    "ISO3",

                    "FAO_Category",

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

# SAVE EVIDENCE

# ==================================================



def save_evidence(

    report,

    source_pdf,

    results,

    expected_count,

    page_records,

):



    lines = [

        "FAO CROP PROSPECTS COUNTRY EXTRACTION",

        "=" * 80,

        "",

        f"Report: {report.get('title')}",

        f"Report URL: {report.get('report_url')}",

        f"Resolved page: "

        f"{report.get('resolved_landing_url')}",

        f"PDF URL: {report.get('pdf_url')}",

        f"Source PDF: {source_pdf.name}",

        (

            "SHA-256: "

            f"{calculate_file_hash(source_pdf)}"

        ),

        f"PDF pages: {len(page_records)}",

        (

            "Expected countries: "

            f"{expected_count}"

        ),

        (

            "Countries extracted: "

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

                    "FAO source name: "

                    f"{row['FAO_Country']}"

                ),

                (

                    "Category: "

                    f"{row['FAO_Category']}"

                ),

                (

                    "FAO score: "

                    f"{row['FAO_Score']}"

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



    current_evidence_file.write_text(

        "\n".join(lines),

        encoding="utf-8",

    )





# ==================================================

# VALIDATE EXTRACTION

# ==================================================



def validate_extraction(

    results,

    expected_count,

):

    """

    Block activation when the PDF layout has changed

    or the extraction result is incomplete.

    """



    problems = []



    if expected_count is None:



        problems.append(

            "Could not detect expected "

            "country count from the report."

        )



    elif len(results) != expected_count:



        problems.append(

            (

                f"Extracted {len(results)} countries "

                f"but report says {expected_count}."

            )

        )



    extracted_categories = set(

        results[

            "FAO_Category"

        ].dropna()

    )



    for required_category in [

        "Shortfall",

        "Access",

        "Localized",

    ]:



        if (

            required_category

            not in extracted_categories

        ):



            problems.append(

                (

                    "Missing category: "

                    f"{required_category}"

                )

            )



    if results["ISO3"].isna().any():



        problems.append(

            "One or more FAO countries "

            "have no ISO3 mapping."

        )



    if problems:



        print()

        print(

            "FAO EXTRACTION REQUIRES REVIEW"

        )



        for problem in problems:



            print(

                f"- {problem}"

            )



        raise RuntimeError(

            "FAO extraction did not pass "

            "validation. Existing current "

            "FAO output was not replaced."

        )





# ==================================================

# COMPLETE DYNAMIC UPDATE

# ==================================================




def _attach_fao_publication_period(report, page_records, results):
    import calendar

    months = list(calendar.month_name)[1:]
    month_pattern = (
        "|".join(months)
        + "|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
    )

    def parse_period(value):
        matches = re.findall(
            r"\b(" + month_pattern
            + r")\.?[\s,/_-]+(20\d{2})\b",
            str(value),
            flags=re.I,
        )
        periods = set()
        for month, year in matches:
            full_month = next(
                m for m in months
                if m.lower().startswith(month.lower()[:3])
            )
            periods.add(full_month + " " + year)
        return next(iter(periods)) if len(periods) == 1 else None

    period = parse_period(report.get("title", ""))
    source = "Official series-page report title"

    if not period:
        cover = page_records[0]["Text"] if page_records else ""
        period = parse_period(cover)
        source = "Downloaded report cover, page 1"

    if not period:
        raise RuntimeError(
            "Cannot identify publication month/year unambiguously "
            "from the report title or cover. "
            "Existing current CSV has not been replaced."
        )

    report["report_period"] = period
    report["publication_period_source"] = source
    results["Report_Period"] = period
    results["Report_Title"] = report.get("title")
    results["Report_URL"] = report.get("report_url")

    print(
        "FAO publication period:", period,
        "|", source, flush=True
    )



def _save_fao_cover_period(report, page_records, results):
    import calendar

    months = list(calendar.month_name)[1:]
    month_pattern = "|".join(months)
    cover = str(page_records[0]["Text"]) if page_records else ""
    cover = re.sub(r"\s+", " ", cover).strip()

    # Match the publication heading, not agricultural forecast dates.
    match = re.search(
        r"\bNo\.?\s*\d+\s*[,:\-]?\s*("
        + month_pattern
        + r")\s+(20\d{2})\b",
        cover,
        flags=re.I,
    )

    if not match:
        raise RuntimeError(
            "Publication heading 'No. <number> <month> <year>' "
            "not found. Existing CSV has not been overwritten."
        )

    month = next(
        m for m in months
        if m.lower() == match.group(1).lower()
    )
    period = month + " " + match.group(2)

    results["Report_Period"] = period
    results["Report_Title"] = report.get("title", "")
    results["Report_URL"] = report.get("report_url", "")
    report["report_period"] = period
    report["publication_period_source"] = "PDF publication heading"

    print("\nFAO PUBLICATION PERIOD:", period, flush=True)


def update_fao_crop_prospects():

    """

    Complete FAO workflow:



    1. Discover newest official report.

    2. Detect whether it is new.

    3. Retrieve the PDF.

    4. Extract country and category.

    5. Validate expected country count.

    6. Preserve page-level evidence.

    7. Replace current output only after validation.

    """



    report = discover_latest_report()



    new_report = is_new_report(

        report

    )



    if new_report:



        print()

        print(

            "FAO publication status: "

            "NEW REPORT"

        )



    else:



        print()

        print(

            "FAO publication status: "

            "already processed"

        )



    source_pdf = download_latest_report(

        report

    )



    mapping = load_country_mapping()



    mapping = add_fao_aliases(

        mapping

    )



    page_records = extract_pdf_pages(

        source_pdf

    )



    expected_count = (

        detect_expected_country_count(

            page_records

        )

    )



    results = (

        parse_assistance_countries(

            page_records,

            mapping,

        )

    )



    validate_extraction(

        results,

        expected_count,

    )



    # Only overwrite current data after validation.

    results.to_csv(

        current_output_csv,

        index=False,

        encoding="utf-8-sig",

    )



    save_evidence(

        report,

        source_pdf,

        results,

        expected_count,

        page_records,

    )



    save_metadata(

        report,

        source_pdf,

        results,

    )



    return (

        report,

        source_pdf,

        results,

        expected_count,

        new_report,

    )





# ==================================================

# RUN DIRECTLY

# ==================================================




# FAO_PUBLICATION_SAVE_WRAPPER
_fao_update_before_publication_save = update_fao_crop_prospects

def update_fao_crop_prospects():
    outcome = _fao_update_before_publication_save()
    report, source_pdf, results = outcome[:3]

    pages = extract_pdf_pages(source_pdf)
    _save_fao_cover_period(report, pages, results)

    results.to_csv(
        current_output_csv,
        index=False,
        encoding="utf-8-sig",
    )
    save_metadata(report, source_pdf, results)

    print(
        "Publication metadata saved to:",
        current_output_csv,
        flush=True,
    )
    return outcome


if __name__ == "__main__":



    (

        report,

        source_pdf,

        results,

        expected_count,

        new_report,

    ) = update_fao_crop_prospects()



    print()

    print("=" * 70)

    print(

        "FAO CROP PROSPECTS UPDATE SUCCESSFUL"

    )

    print("=" * 70)



    print(

        f"Report: "

        f"{report['title']}"

    )



    print(

        f"Report identifier: "

        f"{report['report_code']}"

    )



    print(

        f"Newly discovered: "

        f"{new_report}"

    )



    print(

        f"PDF used: "

        f"{source_pdf.name}"

    )



    print(

        f"Expected countries: "

        f"{expected_count}"

    )



    print(

        f"Countries extracted: "

        f"{len(results)}"

    )



    print()

    print(

        "Category counts:"

    )



    print(

        results[

            "FAO_Category"

        ]

        .value_counts()

        .to_string()

    )



    print()

    print(

        "Extracted FAO countries:"

    )



    print()



    print(

        results[

            [

                "CERF_Country",

                "ISO3",

                "FAO_Score",

                "FAO_Category",

                "PDF_Page",

            ]

        ]

        .to_string(index=False)

    )



    print()

    print(

        f"Current output saved to:\n"

        f"{current_output_csv}"

    )



    print()

    print(

        f"Evidence saved to:\n"

        f"{current_evidence_file}"

    )



    print()

    print(

        f"Report metadata saved to:\n"

        f"{metadata_file}"

    )