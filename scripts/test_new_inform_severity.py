from pathlib import Path

import pandas as pd

from collectors.inform_severity import (
    extract_inform_severity,
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

severity_folder = (
    project_folder
    / "data"
    / "raw"
    / "inform_severity"
)


# --------------------------------------------------
# Find the latest downloaded Severity workbook
# --------------------------------------------------

severity_files = list(
    severity_folder.glob("*.xlsx")
)

if not severity_files:
    raise FileNotFoundError(
        "No INFORM Severity workbook found."
    )

severity_file = max(
    severity_files,
    key=lambda file: file.stat().st_mtime
)

print(f"Using Severity file: {severity_file.name}")


# --------------------------------------------------
# Load existing CIRV baseline
# --------------------------------------------------

baseline = pd.read_csv(
    baseline_file
)


# --------------------------------------------------
# Extract new Severity data
#
# The collector already applies our rule:
# highest Severity crisis per ISO3 only.
# --------------------------------------------------

new_severity = extract_inform_severity(
    severity_file
)

new_severity = new_severity[
    [
        "ISO3",
        "INFORM_Severity_Raw",
        "INFORM_Severity",
        "Crisis",
    ]
].copy()

new_severity = new_severity.rename(
    columns={
        "INFORM_Severity_Raw": "New_Severity_Raw",
        "INFORM_Severity": "New_INFORM_Severity",
        "Crisis": "Selected_Crisis",
    }
)


# --------------------------------------------------
# Join to the 150 CIRV countries
# --------------------------------------------------

comparison = baseline.merge(
    new_severity,
    on="ISO3",
    how="left"
)


# --------------------------------------------------
# IMPORTANT
#
# If a country does not appear in the newest
# Severity release, treat Severity as unavailable
# for this comparison.
# --------------------------------------------------

comparison["New_CIRV"] = comparison.apply(
    lambda row: calculate_final_cirv(
        inform_risk=row["INFORM_Risk"],
        inform_severity=(
            row["New_INFORM_Severity"]
            if pd.notna(row["New_INFORM_Severity"])
            else 0
        ),
        cerf_component=row["CERF_Component"],
    ),
    axis=1
)


# --------------------------------------------------
# Compare old and new Severity
# --------------------------------------------------

comparison["Old_Severity"] = (
    comparison["INFORM_Severity"]
)

comparison["New_Severity"] = (
    comparison["New_INFORM_Severity"]
    .fillna(0)
)

comparison["Severity_Change"] = (
    comparison["New_Severity"]
    - comparison["Old_Severity"]
)

comparison["CIRV_Change"] = (
    comparison["New_CIRV"]
    - comparison["Final_CIRV"]
)


# --------------------------------------------------
# Identify important cases
# --------------------------------------------------

comparison["Gained_Severity"] = (
    (comparison["Old_Severity"] <= 0)
    & (comparison["New_Severity"] > 0)
)

comparison["Lost_Severity"] = (
    (comparison["Old_Severity"] > 0)
    & (comparison["New_Severity"] <= 0)
)

comparison["Severity_Changed"] = (
    comparison["Severity_Change"].abs() > 0.01
)


# --------------------------------------------------
# Save the full comparison
# --------------------------------------------------

output_file = (
    project_folder
    / "inform_severity_update_comparison.csv"
)

comparison.to_csv(
    output_file,
    index=False
)


# --------------------------------------------------
# Summary statistics
# --------------------------------------------------

countries_with_new_severity = (
    comparison["New_Severity"] > 0
).sum()

countries_without_new_severity = (
    comparison["New_Severity"] <= 0
).sum()

changed = (
    comparison["Severity_Changed"]
).sum()

gained = (
    comparison["Gained_Severity"]
).sum()

lost = (
    comparison["Lost_Severity"]
).sum()


print()
print("=" * 80)
print("INFORM SEVERITY UPDATE TEST COMPLETE")
print("=" * 80)

print(
    f"CIRV countries checked: "
    f"{len(comparison)}"
)

print(
    f"Countries with new Severity data: "
    f"{countries_with_new_severity}"
)

print(
    f"Countries without new Severity data: "
    f"{countries_without_new_severity}"
)

print(
    f"Countries whose Severity changed: "
    f"{changed}"
)

print(
    f"Countries that gained Severity: "
    f"{gained}"
)

print(
    f"Countries that lost Severity: "
    f"{lost}"
)


# --------------------------------------------------
# Show largest CIRV changes
# --------------------------------------------------

results = comparison[
    [
        "Country",
        "ISO3",
        "Old_Severity",
        "New_Severity",
        "Selected_Crisis",
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


print()
print("Largest CIRV changes:")
print()

print(
    results.head(25)
    .round(2)
    .to_string(index=False)
)


# --------------------------------------------------
# Show gained Severity countries
# --------------------------------------------------

print()
print("Countries that GAINED Severity:")
print()

gained_results = comparison[
    comparison["Gained_Severity"]
][
    [
        "Country",
        "ISO3",
        "Old_Severity",
        "New_Severity",
        "Selected_Crisis",
    ]
]

if gained_results.empty:
    print("None")
else:
    print(
        gained_results
        .round(2)
        .to_string(index=False)
    )


# --------------------------------------------------
# Show lost Severity countries
# --------------------------------------------------

print()
print("Countries that LOST Severity:")
print()

lost_results = comparison[
    comparison["Lost_Severity"]
][
    [
        "Country",
        "ISO3",
        "Old_Severity",
        "New_Severity",
    ]
]

if lost_results.empty:
    print("None")
else:
    print(
        lost_results
        .round(2)
        .to_string(index=False)
    )


print()
print("Full comparison saved to:")
print(output_file)