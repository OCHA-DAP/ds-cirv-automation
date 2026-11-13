from pathlib import Path
from datetime import datetime, timezone
import json
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

URL = "https://api.hpc.tools/v1/public/fts/flow"

def main():
    response = requests.get(
        URL,
        params={
            "year": 2026,
            "groupby": "location"
        },
        timeout=90
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("status") != "ok":
        raise RuntimeError("FTS returned an unsuccessful status.")

    reports = payload["data"]
    records = []

    retrieved = datetime.now(timezone.utc).isoformat()

    for report_name in ["report2", "report3"]:
        funding = reports[report_name]["fundingTotals"]

        for group in funding.get("objects", []):
            if group.get("direction") != "destination":
                continue

            for item in group.get("objectsBreakdown", []):
                location_id = item.get("id")

                if location_id is None:
                    continue

                records.append({
                    "year": 2026,
                    "report": report_name,
                    "location_id": str(location_id),
                    "country": item.get("name"),
                    "total_funding_usd": item.get("totalFunding"),
                    "single_funding_usd": item.get("singleFunding"),
                    "overlap_funding_usd": item.get("overlapFunding"),
                    "shared_funding_usd": item.get("sharedFunding"),
                    "retrieved_at_utc": retrieved
                })

    df = pd.DataFrame(records)

    if df.empty:
        raise RuntimeError("No country funding records returned.")

    output = OUT / "fts_total_country_2026_validation.csv"

    df.to_csv(
        output,
        index=False,
        encoding="utf-8-sig"
    )

    print()
    print("=" * 60)
    print("FTS TOTAL COUNTRY FUNDING COLLECTED")
    print("=" * 60)

    print("Records:", len(df))

    for report in ["report2", "report3"]:
        subset = df[df["report"] == report]
        print(report, "locations:", len(subset))

    print()
    print("EXAMPLE COUNTRY TOTALS")

    examples = [
        "Sudan",
        "Somalia",
        "Afghanistan",
        "Yemen",
        "Ukraine"
    ]

    selected = df[df["country"].isin(examples)]

    print(
        selected[
            ["country", "report", "total_funding_usd"]
        ].sort_values(["country", "report"]).to_string(index=False)
    )

    print()
    print("Saved:", output)
    print()
    print("Validation dataset only. Existing CIRV outputs unchanged.")


if __name__ == "__main__":
    main()
