from pathlib import Path
from datetime import datetime, timezone
import json
import math

import pandas as pd

# ================================================================
# CERF CIRV CONFLICT PROCESSOR
# ================================================================
# Conflict logic aligned to the attached August workbook and the
# October guidance:
#
# 1. WCI normalization
#      WCI normalized = raw WCI / applicable source maximum * 100
#
#    The applicable maximum is recalculated for the current source
#    period. It is NOT fixed permanently to the August value 6.82.
#    If the WCI collector provides ACLED_WCI_Global_Max or another
#    explicit source-maximum column, that value is preferred.
#    Otherwise, the maximum available in acled_wci_current.csv is used.
#
# 2. ACLED Trends
#      event count < 5             -> 50
#      change <= -25%              -> 0
#      -25% < change <= -10%       -> 25
#      -10% < change < 10%         -> 50
#      10% <= change < 25%         -> 75
#      change >= 25%               -> 100
#
# 3. CrisisWatch
#      net change = deteriorations - ameliorations + risk alerts
#      score = 50 + net change * (100 / 12)
#      score capped to 0-100
#
#    Resolution Opportunities are retained as evidence but are not
#    included in the attached workbook's Conflict calculation.
#
# 4. Consolidated Conflict
#      normalized WCI
#      + 0.20 * (ACLED Trends score - 50)
#      + 0.20 * (CrisisWatch score - 50)
#      capped to 0-100
# ================================================================

PROJECT = Path(__file__).resolve().parent.parent
PROCESSED = PROJECT / "data" / "processed"
PROCESSED.mkdir(parents=True, exist_ok=True)

COUNTRIES_FILE = PROJECT / "config" / "countries.csv"
WCI_FILE = PROJECT / "acled_wci_current.csv"
TRENDS_FILE = PROJECT / "acled_trends_current.csv"
CRISISWATCH_MONTHLY_FILE = PROCESSED / "crisiswatch_six_month_window.csv"

CURRENT_OUTPUT = PROJECT / "conflict_current.csv"
EVIDENCE_OUTPUT = PROCESSED / "conflict_evidence.csv"
MISSINGNESS_OUTPUT = PROCESSED / "conflict_missingness.csv"
METADATA_OUTPUT = PROCESSED / "conflict_metadata.json"

EXPECTED_COUNTRIES = 150
CRISISWATCH_MONTHS = 6
TRENDS_MIN_EVENTS = 5
TRENDS_WEIGHT = 0.20
CRISISWATCH_WEIGHT = 0.20
ROUND_DIGITS = 8


def normalize_iso3(value):
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().upper()
    return text if len(text) == 3 and text.isalpha() else None


def number(series):
    return pd.to_numeric(series, errors="coerce")


def rounded(value):
    if pd.isna(value):
        return pd.NA
    return round(float(value), ROUND_DIGITS)


def clipped(value, low=0.0, high=100.0):
    if pd.isna(value):
        return pd.NA
    return min(max(float(value), low), high)


def require_file(path, label):
    if not path.exists():
        raise FileNotFoundError(f"{label} not found:\n{path}")


def require_columns(data, columns, label):
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise RuntimeError(
            f"{label} is missing required columns: {missing}\n"
            f"Available columns: {list(data.columns)}"
        )


def load_country_universe():
    require_file(COUNTRIES_FILE, "CERF country mapping")
    data = pd.read_csv(COUNTRIES_FILE, encoding="utf-8-sig", low_memory=False)
    require_columns(data, ["ISO3", "CERF_Country"], "CERF country mapping")
    data["ISO3"] = data["ISO3"].apply(normalize_iso3)
    data = (
        data[data["ISO3"].notna()][["ISO3", "CERF_Country"]]
        .drop_duplicates("ISO3")
        .reset_index(drop=True)
    )
    if len(data) != EXPECTED_COUNTRIES:
        raise RuntimeError(
            f"Country universe contains {len(data)} countries; "
            f"expected {EXPECTED_COUNTRIES}."
        )
    return data


def detect_wci_column(data):
    candidates = [
        "ACLED_WCI_Raw",
        "ACLED_WCI",
        "WCI",
        "wci",
        "weekly_conflict_index",
        "Weekly Conflict Index",
    ]
    for column in candidates:
        if column in data.columns:
            return column
    raise RuntimeError(
        "Could not identify the raw WCI column. "
        f"Available columns: {list(data.columns)}"
    )


def determine_wci_source_max(data, raw_column):
    explicit_columns = [
        "ACLED_WCI_Global_Max",
        "ACLED_WCI_Source_Max",
        "WCI_Global_Max",
        "WCI_Source_Max",
        "Normalization_Denominator",
    ]
    for column in explicit_columns:
        if column in data.columns:
            values = number(data[column]).dropna()
            if not values.empty:
                candidate = float(values.max())
                if math.isfinite(candidate) and candidate > 0:
                    return candidate, f"explicit collector column: {column}"

    values = number(data[raw_column]).dropna()
    if values.empty:
        raise RuntimeError("ACLED WCI output contains no valid raw WCI values.")
    candidate = float(values.max())
    if not math.isfinite(candidate) or candidate <= 0:
        raise RuntimeError(f"Invalid current-period WCI maximum: {candidate}")
    return candidate, "current-period maximum available in acled_wci_current.csv"


def load_and_normalize_wci():
    require_file(WCI_FILE, "ACLED WCI collector output")
    data = pd.read_csv(WCI_FILE, encoding="utf-8-sig", low_memory=False)
    require_columns(data, ["ISO3"], "ACLED WCI output")

    raw_column = detect_wci_column(data)
    data["ISO3"] = data["ISO3"].apply(normalize_iso3)
    data["ACLED_WCI_Raw"] = number(data[raw_column])

    # Normalize the supplied source population, before CERF-country filtering.
    data = data.sort_values("ACLED_WCI_Raw", ascending=False).drop_duplicates("ISO3")
    values = data["ACLED_WCI_Raw"].dropna()
    if values.empty or not values.map(math.isfinite).all():
        raise RuntimeError("WCI raw values must be finite and nonempty.")
    source_min, source_max = float(values.min()), float(values.max())
    if source_max <= source_min:
        raise RuntimeError("WCI min-max range is zero; normalization is undefined.")
    source_description = f"Workbook min-max; supplied source minimum={source_min}; maximum={source_max}"

    data["ACLED_WCI_Normalized"] = (
        data["ACLED_WCI_Raw"].sub(source_min).div(source_max - source_min).mul(100.0).round(2)
    )
    data["ACLED_WCI_Normalization_Denominator"] = source_max
    data["ACLED_WCI_Denominator_Source"] = source_description

    optional = [
        "ACLED_WCI_Peak_Date",
        "ACLED_WCI_Refresh_Date",
        "ACLED_WCI_Window_Start",
        "ACLED_WCI_Window_End",
        "ACLED_WCI_Observations_In_Window",
    ]
    columns = [
        "ISO3",
        "ACLED_WCI_Raw",
        "ACLED_WCI_Normalized",
        "ACLED_WCI_Normalization_Denominator",
        "ACLED_WCI_Denominator_Source",
    ]
    columns.extend(column for column in optional if column in data.columns)

    result = (
        data[data["ISO3"].notna()][columns]
        .drop_duplicates("ISO3")
        .copy()
    )
    result["ACLED_WCI_Normalized"] = result[
        "ACLED_WCI_Normalized"
    ].apply(rounded)
    return result, source_max, source_description


def score_trends(event_count, percent_change):
    if pd.isna(event_count) or pd.isna(percent_change):
        return pd.NA, "Missing ACLED Trends evidence"

    events = float(event_count)
    change = float(percent_change)

    if events < TRENDS_MIN_EVENTS:
        return 50.0, "Neutral: fewer than five current-period events"
    if change <= -25.0:
        return 0.0, "Strong decrease: change <= -25%"
    if change <= -10.0:
        return 25.0, "Moderate decrease: -25% < change <= -10%"
    if change < 10.0:
        return 50.0, "Stable: -10% < change < 10%"
    if change < 25.0:
        return 75.0, "Moderate increase: 10% <= change < 25%"
    return 100.0, "Strong increase: change >= 25%"


def load_and_score_trends():
    require_file(TRENDS_FILE, "ACLED Trends collector output")
    data = pd.read_csv(TRENDS_FILE, encoding="utf-8-sig", low_memory=False)
    require_columns(
        data,
        ["ISO3", "ACLED_Trends_Event_Count", "ACLED_Trends_Percent"],
        "ACLED Trends output",
    )

    data["ISO3"] = data["ISO3"].apply(normalize_iso3)
    data["ACLED_Trends_Event_Count"] = number(
        data["ACLED_Trends_Event_Count"]
    )
    data["ACLED_Trends_Percent"] = number(data["ACLED_Trends_Percent"])

    scores = data.apply(
        lambda row: score_trends(
            row["ACLED_Trends_Event_Count"],
            row["ACLED_Trends_Percent"],
        ),
        axis=1,
    )
    data["ACLED_Trends_Score"] = [item[0] for item in scores]
    data["ACLED_Trends_Score_Reason"] = [item[1] for item in scores]

    optional = [
        "ACLED_Trends_Absolute_Change",
        "ACLED_Trends_Period_Start",
        "ACLED_Trends_Period_End",
        "ACLED_Trends_Comparison",
        "ACLED_Trends_Comparison_Start",
        "ACLED_Trends_Comparison_End",
        "ACLED_Trends_Latest_Update",
    ]
    columns = [
        "ISO3",
        "ACLED_Trends_Event_Count",
        "ACLED_Trends_Percent",
        "ACLED_Trends_Score",
        "ACLED_Trends_Score_Reason",
    ]
    columns.extend(column for column in optional if column in data.columns)
    return (
        data[data["ISO3"].notna()][columns]
        .drop_duplicates("ISO3")
        .copy()
    )


def load_and_score_crisiswatch():
    require_file(CRISISWATCH_MONTHLY_FILE, "CrisisWatch six-month matrix")
    data = pd.read_csv(
        CRISISWATCH_MONTHLY_FILE,
        encoding="utf-8-sig",
        low_memory=False,
    )
    required = [
        "ISO3",
        "Assessment_Month",
        "CrisisWatch_Crisis_Event",
        "CrisisWatch_Deteriorated",
        "CrisisWatch_Ameliorated",
        "CrisisWatch_Unchanged",
        "CrisisWatch_Conflict_Risk_Alert",
        "CrisisWatch_Resolution_Opportunity",
    ]
    require_columns(data, required, "CrisisWatch six-month matrix")

    data["ISO3"] = data["ISO3"].apply(normalize_iso3)
    data["Assessment_Month"] = pd.to_datetime(
        data["Assessment_Month"], errors="coerce"
    )

    if data["ISO3"].isna().any() or data["Assessment_Month"].isna().any():
        raise RuntimeError("Invalid CrisisWatch ISO3 or assessment date.")
    data["Assessment_Month"] = data["Assessment_Month"].dt.to_period("M").dt.to_timestamp()
    if data.duplicated(["ISO3", "Assessment_Month"]).any():
        raise RuntimeError("Duplicate CrisisWatch country-month rows.")
    months = sorted(data["Assessment_Month"].unique())
    if len(months) != CRISISWATCH_MONTHS or list(pd.date_range(months[0], periods=CRISISWATCH_MONTHS, freq="MS")) != list(months):
        raise RuntimeError("CrisisWatch requires six consecutive source months.")
    flags = required[2:]
    for column in flags:
        data[column] = number(data[column])
        if not data[column].isin([0, 1]).all():
            raise RuntimeError(f"Invalid CrisisWatch flags in {column}.")

    month_counts = data.groupby("ISO3")["Assessment_Month"].nunique()
    invalid = month_counts[month_counts.ne(CRISISWATCH_MONTHS)]
    if not invalid.empty:
        raise RuntimeError(
            "CrisisWatch does not contain six month slots for: "
            + ", ".join(invalid.index.astype(str))
        )

    summary = data.groupby("ISO3", as_index=False).agg(
        CrisisWatch_Crisis_Event_Months=("CrisisWatch_Crisis_Event", "sum"),
        CrisisWatch_Deterioration_Months=("CrisisWatch_Deteriorated", "sum"),
        CrisisWatch_Amelioration_Months=("CrisisWatch_Ameliorated", "sum"),
        CrisisWatch_Unchanged_Months=("CrisisWatch_Unchanged", "sum"),
        CrisisWatch_Risk_Alert_Months=(
            "CrisisWatch_Conflict_Risk_Alert", "sum"
        ),
        CrisisWatch_Resolution_Opportunity_Months=(
            "CrisisWatch_Resolution_Opportunity", "sum"
        ),
    )

    summary["CrisisWatch_Net_Change"] = (
        summary["CrisisWatch_Deterioration_Months"]
        - summary["CrisisWatch_Amelioration_Months"]
        + summary["CrisisWatch_Risk_Alert_Months"]
    )

    # Workbook GS = (deteriorations - improvements + risk alerts) / 12 * 100.
    summary["CrisisWatch_Score"] = (
        summary["CrisisWatch_Net_Change"].mul(100.0 / 12.0)
    )
    summary["CrisisWatch_Score"] = summary[
        "CrisisWatch_Score"
    ].apply(rounded)
    summary["CrisisWatch_Score_Step"] = rounded(100.0 / 12.0)
    return summary


def calculate_conflict(row):
    wci = row["ACLED_WCI_Normalized"]
    trends = row["ACLED_Trends_Score"]
    crisiswatch = row["CrisisWatch_Score"]

    if pd.isna(wci):
        return pd.Series({
            "ACLED_Trends_Modifier": pd.NA,
            "CrisisWatch_Modifier": pd.NA,
            "Combined_Conflict_Modifier": pd.NA,
            "CERF_Conflict_Consolidated_Unclipped": pd.NA,
            "CERF_Conflict_Consolidated": pd.NA,
            "Conflict_Calculation_Status": "Missing normalized WCI base",
        })

    trends_effective = 50.0 if pd.isna(trends) else float(trends)
    crisiswatch_effective = 50.0 if pd.isna(crisiswatch) else float(crisiswatch)

    trends_modifier = TRENDS_WEIGHT * (trends_effective - 50.0)
    crisiswatch_modifier = CRISISWATCH_WEIGHT * (crisiswatch_effective - 50.0)
    combined = trends_modifier + crisiswatch_modifier
    raw_consolidated = float(wci) + combined
    consolidated = clipped(raw_consolidated)

    missing = []
    if pd.isna(trends):
        missing.append("ACLED Trends")
    if pd.isna(crisiswatch):
        missing.append("CrisisWatch")
    status = (
        "Complete conflict evidence"
        if not missing
        else "Missing modifier treated as neutral: " + ", ".join(missing)
    )

    return pd.Series({
        "ACLED_Trends_Modifier": rounded(trends_modifier),
        "CrisisWatch_Modifier": rounded(crisiswatch_modifier),
        "Combined_Conflict_Modifier": rounded(combined),
        "CERF_Conflict_Consolidated_Unclipped": rounded(raw_consolidated),
        "CERF_Conflict_Consolidated": rounded(consolidated),
        "Conflict_Calculation_Status": status,
    })


def validate_output(output):
    problems = []
    if len(output) != EXPECTED_COUNTRIES:
        problems.append(
            f"Output contains {len(output)} countries; expected {EXPECTED_COUNTRIES}."
        )
    if output["ISO3"].duplicated().any():
        problems.append("Duplicate ISO3 records.")

    for column in [
        "ACLED_WCI_Normalized",
        "ACLED_Trends_Score",
        "CrisisWatch_Score",
        "CERF_Conflict_Consolidated",
    ]:
        values = number(output[column]).dropna()
        if not values.between(0.0, 100.0).all():
            problems.append(f"{column} contains values outside 0-100.")

    valid_trends = set(number(output["ACLED_Trends_Score"]).dropna().unique())
    if not valid_trends.issubset({0.0, 25.0, 50.0, 75.0, 100.0}):
        problems.append("Unexpected ACLED Trends score.")

    scored = output[output["CERF_Conflict_Consolidated"].notna()].copy()
    expected = (
        scored["ACLED_WCI_Normalized"]
        + 0.20 * (scored["ACLED_Trends_Score"].fillna(50.0) - 50.0)
        + 0.20 * (scored["CrisisWatch_Score"].fillna(50.0) - 50.0)
    ).clip(0.0, 100.0)
    differences = (
        expected - scored["CERF_Conflict_Consolidated"]
    ).abs()
    if (differences > 1e-6).any():
        problems.append("Consolidated formula failed reconciliation.")

    if problems:
        print("\nCONFLICT VALIDATION FAILED")
        for problem in problems:
            print(f"- {problem}")
        raise RuntimeError("Conflict validation failed.")

    print("\nCONFLICT VALIDATION PASSED")


def save_outputs(output, source_max, source_description):
    output.to_csv(CURRENT_OUTPUT, index=False, encoding="utf-8-sig")
    output.to_csv(EVIDENCE_OUTPUT, index=False, encoding="utf-8-sig")

    missingness = output[["ISO3", "CERF_Country"]].copy()
    missingness["WCI_Available"] = output["ACLED_WCI_Normalized"].notna()
    missingness["ACLED_Trends_Available"] = output[
        "ACLED_Trends_Score"
    ].notna()
    missingness["CrisisWatch_Available"] = output[
        "CrisisWatch_Score"
    ].notna()
    missingness["Conflict_Available"] = output[
        "CERF_Conflict_Consolidated"
    ].notna()
    missingness["Conflict_Calculation_Status"] = output[
        "Conflict_Calculation_Status"
    ]
    missingness.to_csv(MISSINGNESS_OUTPUT, index=False, encoding="utf-8-sig")

    metadata = {
        "processor": "CERF CIRV Conflict",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wci_source_max": source_max,
        "wci_source_max_description": source_description,
        "methodology": {
            "wci": (
                "raw WCI divided by the applicable current-period source maximum "
                "and multiplied by 100"
            ),
            "trends": (
                "event count under 5 is neutral 50; otherwise fixed "
                "0/25/50/75/100 percentage-change bands"
            ),
            "crisiswatch": (
                "(deteriorations - ameliorations + risk alerts) * 100/12, "
                "capped to 0..100"
            ),
            "consolidated": (
                "normalized WCI + .20*(Trends-50) + .20*(CrisisWatch-50), "
                "capped to 0..100"
            ),
        },
        "countries": int(len(output)),
        "countries_with_conflict": int(
            output["CERF_Conflict_Consolidated"].notna().sum()
        ),
    }
    METADATA_OUTPUT.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def process_conflict():
    print("Loading CERF country universe...")
    universe = load_country_universe()

    print("Loading and normalizing ACLED WCI...")
    wci, source_max, source_description = load_and_normalize_wci()
    print(f"WCI normalization denominator: {source_max:.8f}")
    print(f"WCI denominator source: {source_description}")

    print("Loading and normalizing ACLED Trends...")
    trends = load_and_score_trends()

    print("Loading and scoring CrisisWatch...")
    crisiswatch = load_and_score_crisiswatch()

    output = (
        universe.merge(wci, on="ISO3", how="left")
        .merge(trends, on="ISO3", how="left")
        .merge(crisiswatch, on="ISO3", how="left")
    )

    calculations = output.apply(calculate_conflict, axis=1)
    output = pd.concat([output, calculations], axis=1)
    validate_output(output)
    save_outputs(output, source_max, source_description)
    return output


if __name__ == "__main__":
    conflict = process_conflict()

    print("\n" + "=" * 70)
    print("CERF CONFLICT PROCESSING COMPLETE")
    print("=" * 70)
    print(f"Countries consolidated: {len(conflict)}")
    print(f"Countries with WCI: {conflict['ACLED_WCI_Normalized'].notna().sum()}")
    print(f"Countries with Trends: {conflict['ACLED_Trends_Score'].notna().sum()}")
    print(f"Countries with CrisisWatch: {conflict['CrisisWatch_Score'].notna().sum()}")
    print(
        "Countries with Conflict score: "
        f"{conflict['CERF_Conflict_Consolidated'].notna().sum()}"
    )

    print("\nHighest current Conflict scores:\n")
    columns = [
        "CERF_Country",
        "ISO3",
        "ACLED_WCI_Raw",
        "ACLED_WCI_Normalized",
        "ACLED_Trends_Event_Count",
        "ACLED_Trends_Percent",
        "ACLED_Trends_Score",
        "CrisisWatch_Deterioration_Months",
        "CrisisWatch_Amelioration_Months",
        "CrisisWatch_Risk_Alert_Months",
        "CrisisWatch_Resolution_Opportunity_Months",
        "CrisisWatch_Net_Change",
        "CrisisWatch_Score",
        "ACLED_Trends_Modifier",
        "CrisisWatch_Modifier",
        "Combined_Conflict_Modifier",
        "CERF_Conflict_Consolidated",
    ]
    print(
        conflict[columns]
        .sort_values("CERF_Conflict_Consolidated", ascending=False)
        .head(50)
        .to_string(index=False)
    )

    print(f"\nCurrent output:\n{CURRENT_OUTPUT}")
    print(f"\nEvidence:\n{EVIDENCE_OUTPUT}")
    print(f"\nMissingness report:\n{MISSINGNESS_OUTPUT}")
    print(f"\nMetadata:\n{METADATA_OUTPUT}")
