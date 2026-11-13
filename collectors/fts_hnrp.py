from pathlib import Path
from datetime import datetime, timezone
import csv
import time

import requests


# ==================================================
# CONFIGURATION
# ==================================================

PROJECT = Path(__file__).resolve().parent.parent

OUTPUT = PROJECT / "data" / "processed"
OUTPUT.mkdir(parents=True, exist_ok=True)

YEARS = [2025, 2026]

HPC_API = "https://api.hpc.tools/v2/public/plan"
FTS_API = "https://api.hpc.tools/v1/public/fts/flow"

SESSION = requests.Session()
SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "CIRV-FTS-Collector/1.0"
})


# ==================================================
# API REQUEST
# ==================================================

def fetch_json(url, params=None):

    for attempt in range(3):

        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=90
            )

            response.raise_for_status()

            payload = response.json()

            if payload.get("status") not in ("ok", None):
                raise RuntimeError(
                    "API returned unsuccessful status."
                )

            return payload

        except (
            requests.RequestException,
            ValueError,
            RuntimeError
        ):

            if attempt == 2:
                raise

            time.sleep(2 * (attempt + 1))


# ==================================================
# DISCOVER PLANS
# ==================================================

def get_plans(year):

    payload = fetch_json(
        HPC_API,
        {"year": year}
    )

    plans = payload.get("data", [])

    if not isinstance(plans, list):
        raise RuntimeError(
            f"Unexpected plan response for {year}"
        )

    return [
        p for p in plans
        if p.get("isReleased") is True
    ]


# ==================================================
# PLAN FUNDING
# ==================================================

def get_plan_funding(year, plan_id):

    payload = fetch_json(
        FTS_API,
        {
            "year": year,
            "planId": plan_id,
            "groupby": "plan"
        }
    )

    reports = payload.get("data", {})

    report = reports.get("report3", {})

    funding = report.get("fundingTotals", {})

    amount = funding.get("total")

    if amount is None:
        return None

    return float(amount)


# ==================================================
# EXTRACT PLAN INFORMATION
# ==================================================

def extract_plan(plan, year):

    plan_id = plan.get("id")

    version = plan.get("planVersion") or {}

    name = version.get("name", "")

    categories = plan.get("categories") or []

    plan_types = [
        c.get("name")
        for c in categories
        if c.get("group") == "planType"
    ]

    locations = plan.get("locations") or []

    countries = [
        location
        for location in locations
        if location.get("adminLevel") == 0
        and location.get("iso3")
    ]

    # Avoid duplicating locations.
    countries = {
        c["iso3"]: c
        for c in countries
    }

    countries = list(countries.values())

    requirements = plan.get("revisedRequirements")

    if requirements is None:
        requirements = plan.get("origRequirements")

    return {
        "year": year,
        "plan_id": plan_id,
        "plan_name": name,
        "plan_type": "; ".join(plan_types),
        "countries": countries,
        "requirements_usd": requirements,
        "updated_at": plan.get("updatedAt")
    }


# ==================================================
# BUILD DATASET
# ==================================================

def collect():

    records = []

    retrieved_at = datetime.now(
        timezone.utc
    ).isoformat()

    for year in YEARS:

        print()
        print("=" * 60)
        print(f"COLLECTING FTS DATA: {year}")
        print("=" * 60)

        plans = get_plans(year)

        print("Released plans:", len(plans))

        for index, plan in enumerate(plans, 1):

            info = extract_plan(plan, year)

            plan_id = info["plan_id"]

            print(
                f"[{index}/{len(plans)}] "
                f"{info['plan_name'][:55]}"
            )

            try:
                funded = get_plan_funding(
                    year,
                    plan_id
                )

                funding_status = (
                    "available"
                    if funded is not None
                    else "missing"
                )

            except Exception as exc:

                print(
                    "Funding retrieval failed:",
                    type(exc).__name__
                )

                funded = None
                funding_status = "error"

            requirements = info["requirements_usd"]

            coverage = None

            if (
                requirements is not None
                and requirements > 0
                and funded is not None
            ):
                coverage = funded / requirements

            countries = info["countries"]

            # Multi-country plans remain in the
            # dataset but are not assigned in full
            # to each individual country.

            if len(countries) == 1:

                country = countries[0]["name"]
                iso3 = countries[0]["iso3"]

                allocation_status = "single_country"

            elif len(countries) > 1:

                country = "; ".join(
                    c["name"] for c in countries
                )

                iso3 = "; ".join(
                    c["iso3"] for c in countries
                )

                allocation_status = (
                    "multi_country_unallocated"
                )

            else:

                country = ""
                iso3 = ""

                allocation_status = (
                    "country_unidentified"
                )

            records.append({
                "year": year,
                "plan_id": plan_id,
                "plan_name": info["plan_name"],
                "plan_type": info["plan_type"],
                "country": country,
                "iso3": iso3,
                "requirements_usd": requirements,
                "funded_usd": funded,
                "coverage_ratio": coverage,
                "funding_status": funding_status,
                "allocation_status": allocation_status,
                "plan_updated_at": info["updated_at"],
                "retrieved_at_utc": retrieved_at
            })

    return records


# ==================================================
# EXPORT
# ==================================================

def save_csv(path, records):

    if not records:
        raise RuntimeError(
            "No FTS records collected."
        )

    fields = list(records[0].keys())

    temporary = path.with_suffix(".tmp")

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )

        writer.writeheader()
        writer.writerows(records)

    temporary.replace(path)


# ==================================================
# MAIN
# ==================================================

def main():

    records = collect()

    # Preserve all plan-level records.
    plan_file = OUTPUT / "fts_plans_2025_2026.csv"

    save_csv(plan_file, records)

    # Only single-country plans are eligible
    # for automatic country-level aggregation.
    eligible = [
        r for r in records
        if r["allocation_status"] == "single_country"
        and r["funding_status"] == "available"
        and r["requirements_usd"] is not None
        and r["requirements_usd"] > 0
    ]

    eligible_file = (
        OUTPUT / "fts_single_country_plans.csv"
    )

    if eligible:
        save_csv(eligible_file, eligible)

    excluded = [
        r for r in records
        if r not in eligible
    ]

    excluded_file = (
        OUTPUT / "fts_excluded_plans.csv"
    )

    if excluded:
        save_csv(excluded_file, excluded)

    print()
    print("=" * 60)
    print("FTS COLLECTION COMPLETE")
    print("=" * 60)

    print("Total plans:", len(records))
    print("Eligible single-country plans:", len(eligible))
    print("Plans requiring review:", len(excluded))

    print()
    print("Saved:", plan_file)
    print("Saved:", eligible_file)

    if excluded:
        print("Saved:", excluded_file)


if __name__ == "__main__":
    main()
