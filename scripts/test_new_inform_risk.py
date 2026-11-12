from pathlib import Path

import pandas as pd

from collectors.inform_risk import (
    extract_inform_risk,
)

from methodology.cirv import (
    calculate_final_cirv,
)


# --------------------------------------------------
# Locate project files
# --------------------------------------------------

project_folder = Path(__file__).parent.parent

baseline_file = (
    project_folder
    / "cirv_baseline.csv"
)

inform_file = (
    project_folder
    / "data"
    / "raw"
    / "inform_risk"
    / "INFORM_Risk_Mid_2026.xlsx"
)


# --------------------------------------------------
# Load existing CIRV baseline
# --------------------------------------------------

baseline = pd.read_csv(
    baseline_file
)


# --------------------------------------------------
# Load NEW automated INFORM Risk data
# --------------------------------------------------

new_risk = extract_inform_risk(
    inform_file
)


# Keep only what we need
new_risk = new_risk[
    [
        "ISO3",
        "INFORM_Risk"
    ]
].copy()

new_risk = new_risk.rename(
    columns={
        "INFORM_Risk": "New_INFORM_Risk"
    }
)


# --------------------------------------------------
# Join new Risk values to existing CIRV countries
# --------------------------------------------------

comparison = baseline.merge(
    new_risk,
    on="ISO3",
    how="left"
)


# --------------------------------------------------
# Calculate CIRV using the NEW Risk score
#
# Everything else stays exactly the same for now.
# --------------------------------------------------

comparison["New_CIRV"] = comparison.apply(
    lambda row: calculate_final_cirv(
        inform_risk=row["New_INFORM_Risk"],
        inform_severity=row["INFORM_Severity"],
        cerf_component=row["CERF_Component"],
    )
    if pd.notna(row["New_INFORM_Risk"])
    else None,
    axis=1
)


# --------------------------------------------------
# Calculate changes
# --------------------------------------------------

comparison["Risk_Change"] = (
    comparison["New_INFORM_Risk"]
    - comparison["INFORM_Risk"]
)

comparison["CIRV_Change"] = (
    comparison["New_CIRV"]
    - comparison["Final_CIRV"]
)


# --------------------------------------------------
# Save detailed comparison
# --------------------------------------------------

output_file = (
    project_folder
    / "inform_risk_update_comparison.csv"
)

comparison.to_csv(
    output_file,
    index=False
)


# --------------------------------------------------
# Display results
# --------------------------------------------------

matched = comparison[
    "New_INFORM_Risk"
].notna().sum()

missing = comparison[
    "New_INFORM_Risk"
].isna().sum()

changed = (
    comparison["Risk_Change"].abs() > 0.01
).sum()


print()
print("INFORM RISK UPDATE TEST COMPLETE")
print("-" * 80)

print(f"CIRV countries checked: {len(comparison)}")
print(f"Countries matched to new INFORM Risk: {matched}")
print(f"Countries without a Risk match: {missing}")
print(f"Countries with changed Risk scores: {changed}")

print()
print("Largest CIRV changes:")
print()

results = comparison[
    [
        "Country",
        "ISO3",
        "INFORM_Risk",
        "New_INFORM_Risk",
        "Final_CIRV",
        "New_CIRV",
        "CIRV_Change",
    ]
].copy()

results["Absolute_Change"] = (
    results["CIRV_Change"].abs()
)

results = results.sort_values(
    "Absolute_Change",
    ascending=False
)

print(
    results.head(20)
    .round(2)
    .to_string(index=False)
)

print()
print(f"Full comparison saved to:")
print(output_file)