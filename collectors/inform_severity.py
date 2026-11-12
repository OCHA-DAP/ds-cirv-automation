from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup


INFORM_SEVERITY_PAGE = (
    "https://drmkc.jrc.ec.europa.eu/"
    "inform-index/INFORM-Severity/Results-and-data"
)


def discover_latest_inform_severity():
    """
    Dynamically discover the latest INFORM Severity XLSX
    from the official INFORM Severity website.
    """

    print("Checking INFORM Severity website for latest release...")

    response = requests.get(
        INFORM_SEVERITY_PAGE,
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

        if not href.lower().endswith(".xlsx"):
            continue

        full_url = urljoin(
            INFORM_SEVERITY_PAGE,
            href
        )

        filename = Path(
            full_url.split("?")[0]
        ).name

        if "severity" not in filename.lower():
            continue

        candidates.append(
            {
                "url": full_url,
                "filename": filename,
            }
        )

    if not candidates:
        raise RuntimeError(
            "No INFORM Severity XLSX files found."
        )

    # Official page lists newest release first
    latest = candidates[0]

    print()
    print("Latest INFORM Severity release discovered:")
    print(latest["filename"])
    print(latest["url"])

    return latest


def download_inform_severity(release):
    """
    Download the latest release only if it is not
    already stored locally.
    """

    project_folder = Path(__file__).parent.parent

    raw_folder = (
        project_folder
        / "data"
        / "raw"
        / "inform_severity"
    )

    raw_folder.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        raw_folder
        / release["filename"]
    )

    if output_file.exists():

        print()
        print("This INFORM Severity release is already downloaded.")
        print(f"Using existing file: {output_file}")

        return output_file

    print()
    print("New INFORM Severity release detected.")
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


def extract_inform_severity(workbook_path):
    """
    Extract all INFORM Severity crises.

    IMPORTANT CIRV RULE:
    If a country has multiple crisis rows,
    keep ONLY the crisis with the highest
    INFORM Severity score.

    The published Severity score is 0-10.
    CIRV converts it to 0-100.
    """

    data = pd.read_excel(
        workbook_path,
        sheet_name="INFORM Severity - all crises",
        header=1,
        usecols=[0, 1, 2, 3, 5]
    )

    data.columns = [
        "Crisis",
        "Crisis_ID",
        "Country",
        "ISO3",
        "INFORM_Severity_Raw",
    ]

    # Remove empty/non-data rows
    data = data.dropna(
        subset=[
            "Country",
            "ISO3",
            "INFORM_Severity_Raw"
        ]
    )

    # Clean ISO3
    data["ISO3"] = (
        data["ISO3"]
        .astype(str)
        .str.strip()
    )

    # Keep genuine three-letter ISO3 codes only
    data = data[
        data["ISO3"].str.match(
            r"^[A-Z]{3}$"
        )
    ].copy()

    # Ensure Severity is numeric
    data["INFORM_Severity_Raw"] = pd.to_numeric(
        data["INFORM_Severity_Raw"],
        errors="coerce"
    )

    data = data.dropna(
        subset=["INFORM_Severity_Raw"]
    )

    # --------------------------------------------------
    # YOUR CIRV RULE:
    #
    # Sort highest Severity first.
    # Then keep the first row for each ISO3.
    #
    # Example:
    #
    # Bangladesh crisis 1 = 5.9
    # Bangladesh crisis 2 = 6.6
    #
    # Result:
    # Bangladesh = 6.6
    # --------------------------------------------------

    data = data.sort_values(
        [
            "ISO3",
            "INFORM_Severity_Raw"
        ],
        ascending=[
            True,
            False
        ]
    )

    highest_by_country = (
        data
        .drop_duplicates(
            subset=["ISO3"],
            keep="first"
        )
        .copy()
    )

    # Convert 0-10 to CIRV 0-100
    highest_by_country["INFORM_Severity"] = (
        highest_by_country["INFORM_Severity_Raw"]
        * 10
    )

    highest_by_country = (
        highest_by_country
        .sort_values("Country")
        .reset_index(drop=True)
    )

    return highest_by_country


def update_inform_severity():
    """
    Complete dynamic INFORM Severity update.

    1. Find newest release
    2. Download if new
    3. Read every crisis
    4. Keep maximum Severity per country
    5. Convert to CIRV 0-100 scale
    """

    release = discover_latest_inform_severity()

    workbook_path = download_inform_severity(
        release
    )

    severity_data = extract_inform_severity(
        workbook_path
    )

    return release, severity_data


if __name__ == "__main__":

    release, severity_data = update_inform_severity()

    print()
    print("=" * 70)
    print("INFORM SEVERITY UPDATE SUCCESSFUL")
    print("=" * 70)

    print(f"Release: {release['filename']}")
    print(
        f"Countries with Severity data: "
        f"{len(severity_data)}"
    )

    print()
    print(
        severity_data.head(20)
        .to_string(index=False)
    )