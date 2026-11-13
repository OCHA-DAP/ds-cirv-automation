from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed"
SOURCE = OUT / "fts_plans_2025_2026.csv"

SELECTED_2025 = {
    "BGD": 1212,
    "MOZ": 1267,
    "MMR": 1275,
}

EXCLUDED = {"VNM"}


def main():
    df = pd.read_csv(SOURCE)

    for col in ["year", "plan_id", "requirements_usd", "funded_usd"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["plan_scope"] = df["allocation_status"].map({
        "single_country": "Single-country plan",
        "multi_country_unallocated": "Multi-country regional plan",
        "country_unidentified": "Global plan",
    }).fillna("Unclassified")

    reasons = []

    for _, row in df.iterrows():
        iso = str(row["iso3"])
        year = row["year"]
        plan = row["plan_id"]

        if row["plan_scope"] != "Single-country plan":
            reason = "Regional or global plan"
        elif iso in EXCLUDED:
            reason = "Country excluded from scatterplots"
        elif year == 2025 and iso in SELECTED_2025 and plan != SELECTED_2025[iso]:
            reason = "Alternative 2025 plan not selected"
        elif pd.isna(row["requirements_usd"]) or row["requirements_usd"] <= 0:
            reason = "Missing valid requirements"
        elif pd.isna(row["funded_usd"]) or row["funding_status"] != "available":
            reason = "Funding unavailable"
        else:
            reason = ""

        reasons.append(reason)

    df["exclusion_reason"] = reasons
    df["scatterplot_eligible"] = df["exclusion_reason"].eq("")

    eligible = df[df["scatterplot_eligible"]].copy()

    counts = eligible.groupby(["year", "iso3"]).size()
    ambiguous = set(counts[counts > 1].index)

    mask = eligible.apply(
        lambda r: (r["year"], r["iso3"]) in ambiguous,
        axis=1
    )

    ambiguous_indices = eligible.index[mask]

    df.loc[ambiguous_indices, "scatterplot_eligible"] = False
    df.loc[ambiguous_indices, "exclusion_reason"] = (
        "Multiple eligible plans require review"
    )

    detailed = OUT / "fts_funding_detailed.csv"
    df.to_csv(detailed, index=False, encoding="utf-8-sig")

    country = df[df["scatterplot_eligible"]].copy()

    country["coverage_ratio"] = (
        country["funded_usd"] / country["requirements_usd"]
    )

    annual = OUT / "fts_country_annual.csv"
    country.to_csv(annual, index=False, encoding="utf-8-sig")

    wide = country.pivot(
        index="iso3",
        columns="year",
        values=["requirements_usd", "funded_usd"]
    )

    wide.columns = [
        f"{field}_{int(year)}"
        for field, year in wide.columns
    ]

    wide = wide.reset_index()

    required = [
        "requirements_usd_2025",
        "requirements_usd_2026",
        "funded_usd_2025",
        "funded_usd_2026",
    ]

    for col in required:
        if col not in wide:
            wide[col] = float("nan")

    wide["eligible_2025_2026"] = wide[required].notna().all(axis=1)

    wide["requirements_combined"] = (
        wide["requirements_usd_2025"] + wide["requirements_usd_2026"]
    )

    wide["funded_combined"] = (
        wide["funded_usd_2025"]
        + wide["funded_usd_2026"]
    )

    wide["coverage_2025_2026"] = (
        wide["funded_combined"] / wide["requirements_combined"]
    )

    wide["coverage_2026_plan"] = (
        wide["funded_usd_2026"] / wide["requirements_usd_2026"]
    )


    # Load latest collected 2026 total country funding.
    total_path = OUT / "fts_total_country_2026_validation.csv"

    wide["total_funded_usd_2026"] = float("nan")

    if total_path.exists():
        totals = pd.read_csv(total_path)

        totals = totals[
            totals["report"] == "report3"
        ].copy()

        if totals["country"].duplicated().any():
            raise RuntimeError(
                "Duplicate FTS country funding records."
            )

        funding_map = totals.set_index(
            "country"
        )["total_funding_usd"]

        names_map = (
            country.drop_duplicates("iso3")
            .set_index("iso3")["country"]
        )

        wide["total_funded_usd_2026"] = (
            wide["iso3"]
            .map(names_map)
            .map(funding_map)
        )

    wide["coverage_2026_total"] = (
        wide["total_funded_usd_2026"]
        / wide["requirements_usd_2026"]
    )

    wide.loc[
        wide["requirements_usd_2026"].isna()
        | (wide["requirements_usd_2026"] <= 0),
        "coverage_2026_total"
    ] = float("nan")

    names = country.drop_duplicates("iso3").set_index("iso3")["country"]
    wide.insert(1, "country", wide["iso3"].map(names))

    wide["exclusion_reason_2025_2026"] = ""
    wide.loc[
        ~wide["eligible_2025_2026"],
        "exclusion_reason_2025_2026"
    ] = "Missing eligible plan in 2025 or 2026"

    combined = OUT / "fts_country_combined.csv"
    wide.to_csv(combined, index=False, encoding="utf-8-sig")

    print("FTS FUNDING PROCESSING COMPLETE")
    print("Detailed plan records:", len(df))
    print("Eligible annual country records:", len(country))
    print("Countries in combined dataset:", len(wide))
    print("Countries eligible for 2025+2026:", int(wide["eligible_2025_2026"].sum()))
    print("Saved:", detailed)
    print("Saved:", annual)
    print("Saved:", combined)
    print("2026 total country funding: pending separate collection")


if __name__ == "__main__":
    main()
