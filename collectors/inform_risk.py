from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


INFORM_RISK_PAGE = (
    "https://drmkc.jrc.ec.europa.eu/"
    "inform-index/INFORM-Risk/Results-and-data"
)


def discover_latest_inform_risk():
    """
    Visit the official INFORM Risk results page
    and discover the newest INFORM Risk XLSX.

    This avoids hard-coding a specific yearly file URL.
    """

    print("Checking INFORM Risk website for latest release...")

    response = requests.get(
        INFORM_RISK_PAGE,
        timeout=60
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    candidates = []

    for link in soup.find_all("a", href=True):

        href = link["href"]

        # Only consider Excel files
        if not href.lower().endswith(".xlsx"):
            continue

        full_url = urljoin(
            INFORM_RISK_PAGE,
            href
        )

        filename = Path(
            full_url.split("?")[0]
        ).name

        filename_lower = filename.lower()

        # We want INFORM Risk releases,
        # but NOT INFORM Trend files.
        if "inform" not in filename_lower:
            continue

        if "risk" not in filename_lower:
            continue

        if "trend" in filename_lower:
            continue

        candidates.append(
            {
                "url": full_url,
                "filename": filename,
            }
        )

    if not candidates:
        raise RuntimeError(
            "No INFORM Risk XLSX files were found "
            "on the official results page."
        )

    # The official page lists the newest Risk release first.
    latest = candidates[0]

    print("Latest INFORM Risk release discovered:")
    print(latest["filename"])
    print(latest["url"])

    return latest


def download_inform_risk(release):
    """
    Download the dynamically discovered INFORM Risk file.
    """

    project_folder = Path(__file__).parent.parent

    raw_folder = (
        project_folder
        / "data"
        / "raw"
        / "inform_risk"
    )

    raw_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        raw_folder
        / release["filename"]
    )

    # If this exact release has already been downloaded,
    # do not download it again.
    if output_file.exists():
        print()
        print("This INFORM Risk release is already downloaded.")
        print(f"Using existing file: {output_file}")

        return output_file

    print()
    print("New INFORM Risk release detected.")
    print("Downloading...")

    response = requests.get(
        release["url"],
        timeout=120
    )

    response.raise_for_status()

    output_file.write_bytes(
        response.content
    )

    print("Download successful.")
    print(f"Saved to: {output_file}")

    return output_file


def find_risk_sheet(workbook_path):
    """
    Find the country-level INFORM Risk worksheet dynamically.

    This avoids assuming the worksheet will always be named
    'INFORM Risk 2026 (a-z)'.
    """

    excel_file = pd.ExcelFile(
        workbook_path
    )

    for sheet_name in excel_file.sheet_names:

        if (
            "INFORM Risk" in sheet_name
            and "(a-z)" in sheet_name
        ):
            return sheet_name

    raise RuntimeError(
        "Could not find the country-level "
        "INFORM Risk worksheet."
    )


def extract_inform_risk(workbook_path):
    """
    Extract Country, ISO3 and INFORM Risk.

    INFORM Risk is published on a 0-10 scale.
    CIRV converts it to 0-100.
    """

    sheet_name = find_risk_sheet(
        workbook_path
    )

    print()
    print(f"Reading worksheet: {sheet_name}")

    data = pd.read_excel(
        workbook_path,
        sheet_name=sheet_name,
        header=1,
        usecols=[0, 1, 2]
    )

    data.columns = [
        "Country",
        "ISO3",
        "INFORM_Risk_Raw"
    ]

    data = data.dropna(
        subset=[
            "Country",
            "ISO3",
            "INFORM_Risk_Raw"
        ]
    )

    data["ISO3"] = (
        data["ISO3"]
        .astype(str)
        .str.strip()
    )

    # Keep genuine three-letter ISO3 codes.
    # This also removes the "(a-z)" units row.
    data = data[
        data["ISO3"].str.match(
            r"^[A-Z]{3}$"
        )
    ].copy()

    data["INFORM_Risk_Raw"] = pd.to_numeric(
        data["INFORM_Risk_Raw"],
        errors="coerce"
    )

    data = data.dropna(
        subset=["INFORM_Risk_Raw"]
    )

    # CIRV conversion: 0-10 -> 0-100
    data["INFORM_Risk"] = (
        data["INFORM_Risk_Raw"] * 10
    )

    data = data.sort_values(
        "Country"
    ).reset_index(drop=True)

    return data


def update_inform_risk():
    """
    Complete INFORM Risk update process.

    1. Discover latest release
    2. Download only if needed
    3. Extract country scores
    """

    release = discover_latest_inform_risk()

    workbook_path = download_inform_risk(
        release
    )

    risk_data = extract_inform_risk(
        workbook_path
    )

    return release, risk_data


if __name__ == "__main__":

    release, risk_data = update_inform_risk()

    print()
    print("=" * 70)
    print("INFORM RISK UPDATE SUCCESSFUL")
    print("=" * 70)

    print(f"Release: {release['filename']}")
    print(f"Countries extracted: {len(risk_data)}")

    print()
    print(
        risk_data.head(10)
        .to_string(index=False)
    )