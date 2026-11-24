from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "processed"
SOURCE = OUT / "fts_plans_current.csv"

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

    if df["year"].isna().any() or not df["year"].eq(df["year"].round()).all():
        raise RuntimeError("FTS plans contain an invalid year.")
    years = sorted(df["year"].astype(int).unique())
    if len(years) != 2 or years[1] != years[0] + 1:
        raise RuntimeError(f"Expected two consecutive FTS years, got {years}.")
    previous, current = years
    pair = f"{previous}_{current}"

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

    country = df[df["scatterplot_eligible"]].copy()

    country["coverage_ratio"] = (
        country["funded_usd"] / country["requirements_usd"]
    )

    annual = OUT / "fts_country_annual.csv"

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

    if set(country["year"].astype(int)) != set(years):
        raise RuntimeError(f"No eligible country-plan rows for one of {years}.")

    previous_req = f"requirements_usd_{previous}"
    current_req = f"requirements_usd_{current}"
    previous_funded = f"funded_usd_{previous}"
    current_funded = f"funded_usd_{current}"
    required = [previous_req, current_req, previous_funded, current_funded]
    for col in required:
        if col not in wide:
            wide[col] = float("nan")

    eligible_col = f"eligible_{pair}"
    wide[eligible_col] = wide[required].notna().all(axis=1)
    wide["requirements_combined"] = wide[previous_req] + wide[current_req]
    wide["funded_combined"] = wide[previous_funded] + wide[current_funded]
    wide[f"coverage_{pair}"] = wide["funded_combined"] / wide["requirements_combined"]
    wide[f"coverage_{current}_plan"] = wide[current_funded] / wide[current_req]

    totals = pd.read_csv(OUT / f"fts_total_country_{current}_validation.csv")
    totals = totals.loc[totals["report"].eq("report3")].copy()
    if totals.empty or not pd.to_numeric(totals["year"], errors="coerce").eq(current).all():
        raise RuntimeError(f"Missing or wrong-year country totals for {current}.")
    totals = totals.dropna(subset=["country"])
    totals["country_key"] = totals["country"].str.strip().str.casefold()
    if totals["country_key"].duplicated().any():
        raise RuntimeError("Duplicate FTS destination names; check the country totals.")
    totals["total_funding_usd"] = pd.to_numeric(totals["total_funding_usd"], errors="coerce")
    funding_map = totals.set_index("country_key")["total_funding_usd"]

    names = (country.sort_values("year", ascending=False)
             .drop_duplicates("iso3").set_index("iso3")["country"])
    wide.insert(1, "country", wide["iso3"].map(names))
    total_col = f"total_funded_usd_{current}"
    wide[total_col] = wide["country"].str.strip().str.casefold().map(funding_map)
    wide[f"coverage_{current}_total"] = wide[total_col] / wide[current_req]
    if not wide[f"coverage_{current}_total"].notna().any():
        raise RuntimeError(f"No country totals match eligible {current} plans.")

    wide[f"exclusion_reason_{pair}"] = ""
    wide.loc[~wide[eligible_col], f"exclusion_reason_{pair}"] = (
        f"Missing eligible plan in {previous} or {current}"
    )
    df.to_csv(detailed, index=False, encoding="utf-8-sig")
    country.to_csv(annual, index=False, encoding="utf-8-sig")

    combined = OUT / "fts_country_combined.csv"
    wide.to_csv(combined, index=False, encoding="utf-8-sig")

    print("FTS FUNDING PROCESSING COMPLETE")
    print("Detailed plan records:", len(df))
    print("Eligible annual country records:", len(country))
    print("Countries in combined dataset:", len(wide))
    print(f"Countries eligible for {previous}+{current}:", int(wide[eligible_col].sum()))
    print("Saved:", detailed)
    print("Saved:", annual)
    print("Saved:", combined)
    print(f"{current} country total funding matched:", int(wide[total_col].notna().sum()))


if __name__ == "__main__":
    main()
