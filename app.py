from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="CERF CIRV",
    layout="wide"
)

st.title("CERF Index for Risk and Vulnerability")
st.caption("CIRV application under construction")

# Find the baseline file
project_folder = Path(__file__).parent
baseline_file = project_folder / "cirv_baseline.csv"

# Read CIRV data
df = pd.read_csv(baseline_file)

# Round numbers for display
display_df = df.copy()

numeric_columns = [
    "INFORM_Risk",
    "INFORM_Severity",
    "Early_Warning",
    "Food",
    "Conflict",
    "CERF_Component",
    "Final_CIRV",
]

display_df[numeric_columns] = display_df[numeric_columns].round(2)

# Summary
st.success(f"CIRV baseline loaded successfully: {len(df)} countries")

# Country search
search = st.text_input(
    "Search for a country"
)

if search:
    display_df = display_df[
        display_df["Country"]
        .str.contains(search, case=False, na=False)
    ]

# Main table
st.subheader("Current CIRV Scores")

st.dataframe(
    display_df[
        [
            "Country",
            "ISO3",
            "INFORM_Risk",
            "INFORM_Severity",
            "Early_Warning",
            "Food",
            "Conflict",
            "CERF_Component",
            "Final_CIRV",
        ]
    ],
    use_container_width=True,
    hide_index=True,
)

st.info(
    "These scores currently come from the existing Excel workbook. "
    "The next development step is to reproduce the calculations directly in Python."
)