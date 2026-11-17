CIRV integration replacement

FILES
- cirv_all_data_app.py: exact audited CSV/column registry, source views, workbook-colored All Data, CSV/XLSX downloads.
- publish_inform_outputs.py: publishes raw and normalized DataFrames from your existing INFORM collectors into current CSV files.

INSTALL
Stop the previous Streamlit process with Ctrl+C.
Back up cirv_all_data_app.py, then extract this ZIP into the cirv-app root.
Keep the August reference workbook in that root.

RUN
python -m pip install streamlit pandas numpy openpyxl lxml requests beautifulsoup4
python publish_inform_outputs.py
python -m processors.food_security
python -m processors.conflict
python -m processors.iasc
python -m streamlit run cirv_all_data_app.py

If no INFORM download exists locally:
python publish_inform_outputs.py --refresh
This uses your existing INFORM discovery/download functions; it does not handle ACLED credentials.

BEHAVIOR
The app reads exact audited filenames and columns, not arbitrary comparison CSVs.
The two unwanted columns are excluded from the web table/CSV and hidden in XLSX to preserve formula coordinates.
Food raw values and score come from the food processor's ipc_value, fewsnet_value, grfc_value, fao_value, asap_value, sofi_value and CERF_Food_Insecurity fields.
FAO description comes from FAO_Category.
ACLED Trends uses ACLED_Trends_Score, not ACLED_Trends_Percent.
WCI uses ACLED_WCI_Normalized, not the raw WCI.
CrisisWatch uses CrisisWatch_Score. Your processor defines it as 50 + net_change * 100/12, bounded 0-100.
INFORM uses only INFORM_Risk_Raw and INFORM_Severity_Raw and multiplies once by 10.
Countries absent from a successfully loaded Severity source get 0, as in the workbook. Missing whole sources do not become zeros.
All registered source outputs must load before complete exports are enabled.
The app does not rerun collectors or fetch remote data on page load.

EXPORT SCOPE
All original August workbook sheets, styles, conditional formatting and drawings are retained.
All Data values/cached calculations, CIRV Scores and the CIRV column in PowerBI are updated.
Current source sheets are appended for every registered loaded collector/processor dataset.
Original source tabs remain historical August reference tabs, not falsely labelled as current.
Historical funding/apportionment content and existing funding #REF errors are not repaired or refreshed.
GRFC reference period is absent from the audited collector schema. It remains blank unless GRFC_Period or GRFC_Time_Period is supplied by that collector.
This is not a byte-identical or fully refreshed funding workbook.

TEST SCOPE
Formula calculations were compared with cached August All Data values across all 150 country rows in eight calculated columns, with no numeric differences above 1e-6.
CSV schema loading was tested with the actual sample rows in the audit. The audit is not a copy of all local CSV contents, so full local runtime verification remains necessary.

SECURITY
The uploaded audit contained a plaintext password. Rotate it, remove it from code, and do not redistribute that audit. This package contains no copied credentials or authentication source code.
