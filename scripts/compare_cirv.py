from pathlib import Path

import pandas as pd

from methodology.cirv import (
    calculate_cerf_component,
    calculate_final_cirv,
)


# Find the CIRV baseline file
project_folder = Path(__file__).parent.parent
baseline_file = project_folder / "cirv_baseline.csv"

# Read the Excel baseline
df = pd.read_csv(baseline_file)

results = []

for _, row in df.iterrows():

    # Missing Early Warning values should behave like blank Excel cells
    early_warning = row["Early_Warning"]

    if pd.isna(early_warning):
        early_warning = None

    # Calculate the CERF component in Python
    python_cerf = calculate_cerf_component(
        early_warning=early_warning,
        food=row["Food"],
        conflict=row["Conflict"],
    )

    # Calculate final CIRV in Python
    python_cirv = calculate_final_cirv(
        inform_risk=row["INFORM_Risk"],
        inform_severity=row["INFORM_Severity"],
        cerf_component=python_cerf,
    )

    results.append(
        {
            "Country": row["Country"],
            "ISO3": row["ISO3"],
            "Excel_CERF": row["CERF_Component"],
            "Python_CERF": python_cerf,
            "CERF_Difference": python_cerf - row["CERF_Component"],
            "Excel_CIRV": row["Final_CIRV"],
            "Python_CIRV": python_cirv,
            "CIRV_Difference": python_cirv - row["Final_CIRV"],
        }
    )


comparison = pd.DataFrame(results)

# Calculate absolute difference for sorting
comparison["Absolute_Difference"] = (
    comparison["CIRV_Difference"].abs()
)

comparison = comparison.sort_values(
    "Absolute_Difference",
    ascending=False
)

# Save the reconciliation file
output_file = project_folder / "cirv_comparison.csv"

comparison.to_csv(
    output_file,
    index=False
)

print()
print("CIRV COMPARISON COMPLETE")
print("-" * 80)

print(f"Countries checked: {len(comparison)}")

matching = (
    comparison["Absolute_Difference"] <= 0.01
).sum()

print(f"Countries matching within 0.01: {matching}")
print(
    f"Countries with differences over 0.01: "
    f"{len(comparison) - matching}"
)

print()
print("Largest differences:")
print()

print(
    comparison[
        [
            "Country",
            "Excel_CIRV",
            "Python_CIRV",
            "CIRV_Difference",
        ]
    ]
    .head(15)
    .round(4)
    .to_string(index=False)
)

print()
print(f"Full comparison saved to:")
print(output_file)