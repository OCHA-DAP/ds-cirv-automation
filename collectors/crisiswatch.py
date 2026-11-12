from pathlib import Path
from datetime import datetime, timezone
import json
import re

import pandas as pd
import requests
from bs4 import BeautifulSoup

DATABASE_URLS = [
    "https://www.crisisgroup.org/crisiswatch/database",
    "https://crisisgroup-staging.sbx.so/crisiswatch/database",
]
LOOKBACK_MONTHS = 6
REQUEST_TIMEOUT = 120
MIN_ENTRIES_PER_MONTH = 1

PROJECT = Path(__file__).resolve().parent.parent
MAPPING_FILE = PROJECT / "config" / "countries.csv"
RAW_DIR = PROJECT / "data" / "raw" / "crisiswatch"
PROCESSED_DIR = PROJECT / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_OUTPUT = PROJECT / "crisiswatch_current.csv"
MONTHLY_OUTPUT = PROCESSED_DIR / "crisiswatch_six_month_window.csv"
EVIDENCE_OUTPUT = PROCESSED_DIR / "crisiswatch_evidence.csv"
UNMATCHED_OUTPUT = PROCESSED_DIR / "crisiswatch_unmatched.csv"
METADATA_OUTPUT = PROCESSED_DIR / "crisiswatch_metadata.json"

SITUATION_TO_ISO3 = {
    "democratic republic of congo": ["COD"],
    "democratic republic of the congo": ["COD"],
    "dr congo": ["COD"],
    "israel palestine": ["ISR", "PSE"],
    "israel and palestine": ["ISR", "PSE"],
    "israel palestinian territories": ["ISR", "PSE"],
    "palestine": ["PSE"],
    "occupied palestinian territory": ["PSE"],
    "opt": ["PSE"],
    "korean peninsula": ["PRK", "KOR"],
    "armenian azerbaijani conflict": ["ARM", "AZE"],
    "armenia azerbaijan": ["ARM", "AZE"],
    "india pakistan kashmir": ["IND", "PAK"],
    "india pakistan": ["IND", "PAK"],
    "russia ukraine": ["RUS", "UKR"],
    "ethiopia eritrea": ["ETH", "ERI"],
    "nile waters": ["EGY", "ETH", "SDN"],
    "south china sea": ["CHN", "PHL", "VNM"],
    "eastern mediterranean": ["CYP", "GRC", "TUR"],
    "venezuela guyana": ["VEN", "GUY"],
}


def normalize_text(value):
    if value is None:
        return ""
    return " ".join(
        str(value).strip().lower()
        .replace("_", " ").replace("-", " ").replace("/", " ")
        .replace("\n", " ").replace("\r", " ")
        .replace("’", "'").replace("‘", "'")
        .replace("–", " ").replace("—", " ").split()
    )


def normalize_iso3(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    return text if len(text) == 3 and text.isalpha() else None


def clean_name(value):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    text = re.sub(r"^[•·▪■►▶\-–—]+\s*", "", text)
    text = re.sub(r"\s*[:;,.]+$", "", text)
    return text if text and len(text) <= 120 else None


def month_start(value):
    ts = pd.Timestamp(value)
    return pd.Timestamp(year=ts.year, month=ts.month, day=1)


def month_label(value):
    return pd.Timestamp(value).strftime("%B %Y")


def previous_months(latest_month, count):
    end = pd.Timestamp(latest_month).to_period("M")
    return [(end - offset).to_timestamp() for offset in range(count - 1, -1, -1)]


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def find_working_database(session):
    errors = []
    for url in DATABASE_URLS:
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if response.status_code != 200:
                errors.append(f"{url}: HTTP {response.status_code}")
                continue
            low = response.text.lower()
            markers = ["from_month", "from_year", "to_month", "to_year", "crisis_state"]
            if all(marker in low for marker in markers):
                return response.url, response.text
            errors.append(f"{url}: database form not found")
        except requests.RequestException as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("No usable CrisisWatch database found.\n\n" + "\n".join(errors))


def load_country_mapping():
    if not MAPPING_FILE.exists():
        raise FileNotFoundError(f"Country mapping not found:\n{MAPPING_FILE}")
    mapping = pd.read_csv(MAPPING_FILE, encoding="utf-8-sig", low_memory=False)
    for column in ["ISO3", "CERF_Country"]:
        if column not in mapping.columns:
            raise RuntimeError(f"countries.csv is missing required column: {column}")
    mapping["ISO3"] = mapping["ISO3"].apply(normalize_iso3)
    mapping = mapping[mapping["ISO3"].notna()].copy()
    universe = mapping[["ISO3", "CERF_Country"]].drop_duplicates("ISO3").reset_index(drop=True)
    aliases = universe.copy()
    aliases["Source_Alias"] = aliases["CERF_Country"]
    if "Source_Alias" in mapping.columns:
        aliases = pd.concat(
            [aliases, mapping[["ISO3", "CERF_Country", "Source_Alias"]].copy()],
            ignore_index=True,
        )
    aliases["Normalized_Alias"] = aliases["Source_Alias"].apply(normalize_text)
    aliases = aliases[aliases["Normalized_Alias"].ne("")].drop_duplicates(
        ["ISO3", "Normalized_Alias"]
    )
    return universe, aliases


def extract_latest_month(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    months = []
    for element in soup.select(".cw-database h1 time, .c-crisiswatch-entry time"):
        parsed = pd.to_datetime(
            element.get("datetime") or element.get_text(" ", strip=True),
            errors="coerce",
        )
        if not pd.isna(parsed):
            months.append(month_start(parsed))
    if not months:
        raise RuntimeError("Could not identify the latest CrisisWatch month.")
    completed = month_start(datetime.now(timezone.utc).replace(tzinfo=None))
    months = [m for m in months if m < completed]
    if not months:
        raise RuntimeError("No completed CrisisWatch assessment month found.")
    return max(months)


def request_month(session, database_url, month):
    params = {
        "created": "custom",
        "from_month": str(month.month),
        "from_year": str(month.year),
        "to_month": str(month.month),
        "to_year": str(month.year),
    }
    print(f"Requesting {month_label(month)}...")
    response = session.get(
        database_url,
        params=params,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=True,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Monthly request failed for {month_label(month)}: HTTP {response.status_code}\n{response.url}"
        )
    raw_path = RAW_DIR / f"crisiswatch_{month.strftime('%Y_%m')}.html"
    raw_path.write_text(response.text, encoding="utf-8")
    return response.url, response.text


def extract_main_state(entry):
    heading = entry.find(["h2", "h3", "h4"])
    if heading is None:
        raise RuntimeError("CrisisWatch heading missing; refusing to infer Unchanged.")
    use = heading.find("use")
    href = ""
    if use is not None:
        href = use.get("xlink:href") or use.get("href") or ""
    low = href.lower()
    if "deteriorated" in low:
        return "Deteriorated", href
    if "improved" in low:
        return "Ameliorated", href
    if "unchanged" in low:
        return "Unchanged", href
    html = str(heading).lower()
    if "#deteriorated" in html or "state-deteriorated" in html:
        return "Deteriorated", "heading-html"
    if "#improved" in html or "state-improved" in html:
        return "Ameliorated", "heading-html"
    if "unchanged" in html:
        return "Unchanged", "heading-html"
    raise RuntimeError("Unrecognized CrisisWatch state; refusing to infer Unchanged.")


def extract_formal_outlook_flags(entry, requested_month):
    """Read only explicit structured CrisisWatch labels for the requested month."""
    risk_alert = 0
    resolution = 0
    target = month_label(requested_month).lower()

    # The database places formal states in timeline-like state entries.
    for state_entry in entry.select(".o-state-entry"):
        text = " ".join(state_entry.get_text(" ", strip=True).split())
        title = state_entry.get("title") or ""
        combined = f"{title} {text}".strip()
        low = combined.lower()
        parsed = pd.to_datetime(title or text, errors="coerce")
        same_month = False
        if not pd.isna(parsed):
            same_month = month_start(parsed) == requested_month
        elif target in low:
            same_month = True
        if not same_month:
            continue
        if "conflict risk alert" in low or "risk alert" in low:
            risk_alert = 1
        if "resolution opportunity" in low:
            resolution = 1

    # Some formal labels are rendered outside .o-state-entry but still inside
    # the entry. Match only a date immediately adjacent to the formal label.
    entry_text = " ".join(entry.get_text(" ", strip=True).split())
    escaped_month = re.escape(month_label(requested_month))
    if re.search(
        rf"{escaped_month}\s+Conflict Risk Alert|Conflict Risk Alert\s+{escaped_month}",
        entry_text,
        flags=re.IGNORECASE,
    ):
        risk_alert = 1
    if re.search(
        rf"{escaped_month}\s+Resolution Opportunity|Resolution Opportunity\s+{escaped_month}",
        entry_text,
        flags=re.IGNORECASE,
    ):
        resolution = 1

    return risk_alert, resolution


def extract_month_entries(html_text, source_url, requested_month):
    soup = BeautifulSoup(html_text, "html.parser")
    displayed = []
    for element in soup.select(".cw-database h1 time"):
        parsed = pd.to_datetime(
            element.get("datetime") or element.get_text(" ", strip=True),
            errors="coerce",
        )
        if not pd.isna(parsed):
            displayed.append(month_start(parsed))
    if displayed and max(displayed) != requested_month:
        raise RuntimeError(
            f"Wrong month returned. Requested {month_label(requested_month)}, "
            f"received {month_label(max(displayed))}."
        )

    entries = soup.select("div.c-crisiswatch-entry")
    if len(entries) < MIN_ENTRIES_PER_MONTH:
        raise RuntimeError(
            f"Only {len(entries)} CrisisWatch entries found for {month_label(requested_month)}."
        )

    records = []
    for entry in entries:
        heading = entry.find(["h2", "h3", "h4"])
        heading_name = clean_name(heading.get_text(" ", strip=True)) if heading else None
        source_name = heading_name or clean_name(entry.get("data-entry-country"))
        if not source_name:
            continue
        state, state_evidence = extract_main_state(entry)
        risk_alert, resolution = extract_formal_outlook_flags(entry, requested_month)
        paragraphs = entry.find_all("p")
        narrative = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
        narrative = re.sub(r"\s+", " ", narrative).strip()
        records.append({
            "Assessment_Month": requested_month,
            "Source_Name": source_name,
            "CrisisWatch_Crisis_Event": 1,
            "CrisisWatch_State": state,
            "CrisisWatch_Deteriorated": int(state == "Deteriorated"),
            "CrisisWatch_Ameliorated": int(state == "Ameliorated"),
            "CrisisWatch_Unchanged": int(state == "Unchanged"),
            "CrisisWatch_Conflict_Risk_Alert": risk_alert,
            "CrisisWatch_Resolution_Opportunity": resolution,
            "State_Evidence": state_evidence,
            "Narrative": narrative,
            "Source_URL": source_url,
        })

    data = pd.DataFrame(records)
    if data.empty:
        raise RuntimeError(f"No valid entries parsed for {month_label(requested_month)}.")
    return data.drop_duplicates(["Assessment_Month", "Source_Name"]).reset_index(drop=True)


def map_entries(evidence, universe, aliases):
    alias_lookup = {}
    for _, row in aliases.iterrows():
        alias_lookup.setdefault(row["Normalized_Alias"], []).append({
            "ISO3": row["ISO3"],
            "CERF_Country": row["CERF_Country"],
        })
    universe_lookup = universe.set_index("ISO3")["CERF_Country"].to_dict()
    mapped_records = []
    unmatched_records = []

    for _, row in evidence.iterrows():
        normalized_name = normalize_text(row["Source_Name"])
        matches = list(alias_lookup.get(normalized_name, []))
        for iso3 in SITUATION_TO_ISO3.get(normalized_name, []):
            country = universe_lookup.get(iso3)
            if country:
                matches.append({"ISO3": iso3, "CERF_Country": country})
        unique = {match["ISO3"]: match for match in matches}
        if not unique:
            record = row.to_dict()
            record["Normalized_Source_Name"] = normalized_name
            unmatched_records.append(record)
            continue
        for match in unique.values():
            record = row.to_dict()
            record.update(match)
            mapped_records.append(record)

    if not mapped_records:
        raise RuntimeError("No CrisisWatch entries mapped to the country universe.")
    return pd.DataFrame(mapped_records), pd.DataFrame(unmatched_records)


def build_country_matrix(mapped, universe, months):
    rows = []
    for _, country in universe.iterrows():
        for month in months:
            subset = mapped[
                mapped["ISO3"].eq(country["ISO3"])
                & mapped["Assessment_Month"].eq(month)
            ]
            if subset.empty:
                values = {
                    "CrisisWatch_Crisis_Event": 0,
                    "CrisisWatch_Deteriorated": 0,
                    "CrisisWatch_Ameliorated": 0,
                    "CrisisWatch_Unchanged": 0,
                    "CrisisWatch_Conflict_Risk_Alert": 0,
                    "CrisisWatch_Resolution_Opportunity": 0,
                    "CrisisWatch_States": "",
                    "CrisisWatch_Source_Names": "",
                }
            else:
                values = {
                    "CrisisWatch_Crisis_Event": 1,
                    "CrisisWatch_Deteriorated": int(subset["CrisisWatch_Deteriorated"].max()),
                    "CrisisWatch_Ameliorated": int(subset["CrisisWatch_Ameliorated"].max()),
                    "CrisisWatch_Unchanged": int(subset["CrisisWatch_Unchanged"].max()),
                    "CrisisWatch_Conflict_Risk_Alert": int(subset["CrisisWatch_Conflict_Risk_Alert"].max()),
                    "CrisisWatch_Resolution_Opportunity": int(subset["CrisisWatch_Resolution_Opportunity"].max()),
                    "CrisisWatch_States": ", ".join(sorted(set(subset["CrisisWatch_State"].dropna()))),
                    "CrisisWatch_Source_Names": ", ".join(sorted(set(subset["Source_Name"].dropna()))),
                }
            rows.append({
                "ISO3": country["ISO3"],
                "CERF_Country": country["CERF_Country"],
                "Assessment_Month": month,
                **values,
            })

    monthly = pd.DataFrame(rows)
    summary = monthly.groupby(["ISO3", "CERF_Country"], as_index=False).agg(
        CrisisWatch_Months_In_Window=("Assessment_Month", "nunique"),
        CrisisWatch_Crisis_Event_Months=("CrisisWatch_Crisis_Event", "sum"),
        CrisisWatch_Deterioration_Months=("CrisisWatch_Deteriorated", "sum"),
        CrisisWatch_Amelioration_Months=("CrisisWatch_Ameliorated", "sum"),
        CrisisWatch_Unchanged_Months=("CrisisWatch_Unchanged", "sum"),
        CrisisWatch_Risk_Alert_Months=("CrisisWatch_Conflict_Risk_Alert", "sum"),
        CrisisWatch_Resolution_Opportunity_Months=("CrisisWatch_Resolution_Opportunity", "sum"),
    )
    summary["CrisisWatch_Directional_Balance"] = (
        summary["CrisisWatch_Deterioration_Months"]
        - summary["CrisisWatch_Amelioration_Months"]
    )
    summary["CrisisWatch_Outlook_Balance"] = (
        summary["CrisisWatch_Risk_Alert_Months"]
        - summary["CrisisWatch_Resolution_Opportunity_Months"]
    )
    summary["CrisisWatch_Window_Start"] = min(months)
    summary["CrisisWatch_Window_End"] = max(months)
    return summary, monthly


def validate(current, monthly, raw_evidence, months):
    problems = []
    if current["ISO3"].duplicated().any():
        problems.append("Duplicate ISO3 records.")
    if current["CrisisWatch_Months_In_Window"].ne(LOOKBACK_MONTHS).any():
        problems.append("Not every country has six monthly slots.")
    if raw_evidence["Assessment_Month"].nunique() != LOOKBACK_MONTHS:
        problems.append("Fewer than six actual source months were retrieved.")
    for month in months:
        if raw_evidence[raw_evidence["Assessment_Month"].eq(month)].empty:
            problems.append(f"No source records for {month_label(month)}.")
    for column in [
        "CrisisWatch_Crisis_Event",
        "CrisisWatch_Deteriorated",
        "CrisisWatch_Ameliorated",
        "CrisisWatch_Unchanged",
        "CrisisWatch_Conflict_Risk_Alert",
        "CrisisWatch_Resolution_Opportunity",
    ]:
        if not monthly[column].isin([0, 1]).all():
            problems.append(f"Invalid flags in {column}.")
    if problems:
        print("\nCRISISWATCH VALIDATION FAILED")
        for problem in problems:
            print(f"- {problem}")
        raise RuntimeError("CrisisWatch validation failed.")
    print("\nCRISISWATCH VALIDATION PASSED")
    print(f"Countries in output: {len(current)}")
    print(f"Actual source months retrieved: {raw_evidence['Assessment_Month'].nunique()}")


def save_outputs(current, monthly, evidence, unmatched, database_url, months):
    current_save = current.copy()
    monthly_save = monthly.copy()
    evidence_save = evidence.copy()
    unmatched_save = unmatched.copy()

    for column in ["CrisisWatch_Window_Start", "CrisisWatch_Window_End"]:
        current_save[column] = pd.to_datetime(current_save[column]).dt.strftime("%Y-%m")
    monthly_save["Assessment_Month"] = pd.to_datetime(monthly_save["Assessment_Month"]).dt.strftime("%Y-%m")
    if not evidence_save.empty:
        evidence_save["Assessment_Month"] = pd.to_datetime(evidence_save["Assessment_Month"]).dt.strftime("%Y-%m")
    if not unmatched_save.empty and "Assessment_Month" in unmatched_save.columns:
        unmatched_save["Assessment_Month"] = pd.to_datetime(unmatched_save["Assessment_Month"]).dt.strftime("%Y-%m")

    current_save.to_csv(CURRENT_OUTPUT, index=False, encoding="utf-8-sig")
    monthly_save.to_csv(MONTHLY_OUTPUT, index=False, encoding="utf-8-sig")
    evidence_save.to_csv(EVIDENCE_OUTPUT, index=False, encoding="utf-8-sig")
    unmatched_save.to_csv(UNMATCHED_OUTPUT, index=False, encoding="utf-8-sig")

    metadata = {
        "source": "International Crisis Group CrisisWatch",
        "database_url": database_url,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "lookback_months": LOOKBACK_MONTHS,
        "selected_months": [month.strftime("%Y-%m") for month in months],
        "method": (
            "Six separate monthly database requests. Main monthly state is read from the entry heading. "
            "Formal Conflict Risk Alert and Resolution Opportunity labels are parsed only when explicitly "
            "associated with the requested month inside the structured CrisisWatch entry."
        ),
        "mapped_evidence_records": int(len(evidence_save)),
        "unmatched_evidence_records": int(len(unmatched_save)),
        "scoring": "No CERF score is calculated in this collector.",
    }
    METADATA_OUTPUT.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")


def update_crisiswatch():
    print("Loading CrisisWatch...")
    session = create_session()
    database_url, database_html = find_working_database(session)
    print(f"Database:\n{database_url}")
    latest_month = extract_latest_month(database_html)
    months = previous_months(latest_month, LOOKBACK_MONTHS)
    print("\nSelected CrisisWatch months:")
    for month in months:
        print(f"- {month_label(month)}")

    extracted = []
    for month in months:
        source_url, html = request_month(session, database_url, month)
        month_data = extract_month_entries(html, source_url, month)
        alerts = int(month_data["CrisisWatch_Conflict_Risk_Alert"].sum())
        opportunities = int(month_data["CrisisWatch_Resolution_Opportunity"].sum())
        print(
            f"Entries parsed: {len(month_data)} | risk alerts: {alerts} | "
            f"resolution opportunities: {opportunities}"
        )
        extracted.append(month_data)

    raw_evidence = pd.concat(extracted, ignore_index=True)
    universe, aliases = load_country_mapping()
    mapped, unmatched = map_entries(raw_evidence, universe, aliases)
    current, monthly = build_country_matrix(mapped, universe, months)
    validate(current, monthly, raw_evidence, months)
    save_outputs(current, monthly, mapped, unmatched, database_url, months)
    return current, mapped, unmatched


if __name__ == "__main__":
    current, evidence, unmatched = update_crisiswatch()
    print("\n" + "=" * 70)
    print("CRISISWATCH UPDATE COMPLETE")
    print("=" * 70)
    print(f"Countries in output: {len(current)}")
    print(f"Mapped evidence records: {len(evidence)}")
    print(f"Unmatched evidence records: {len(unmatched)}")
    print("\nCountries with CrisisWatch entries or outlook signals:\n")
    signalled = current[
        current["CrisisWatch_Crisis_Event_Months"].gt(0)
        | current["CrisisWatch_Risk_Alert_Months"].gt(0)
        | current["CrisisWatch_Resolution_Opportunity_Months"].gt(0)
    ]
    columns = [
        "CERF_Country",
        "ISO3",
        "CrisisWatch_Crisis_Event_Months",
        "CrisisWatch_Deterioration_Months",
        "CrisisWatch_Amelioration_Months",
        "CrisisWatch_Unchanged_Months",
        "CrisisWatch_Risk_Alert_Months",
        "CrisisWatch_Resolution_Opportunity_Months",
        "CrisisWatch_Directional_Balance",
        "CrisisWatch_Outlook_Balance",
    ]
    print(signalled[columns].sort_values(
        ["CrisisWatch_Risk_Alert_Months", "CrisisWatch_Deterioration_Months", "CERF_Country"],
        ascending=[False, False, True],
    ).to_string(index=False))
    print(f"\nCurrent output:\n{CURRENT_OUTPUT}")
    print(f"\nSix-month matrix:\n{MONTHLY_OUTPUT}")
    print(f"\nEvidence:\n{EVIDENCE_OUTPUT}")
    print(f"\nUnmatched entries:\n{UNMATCHED_OUTPUT}")
