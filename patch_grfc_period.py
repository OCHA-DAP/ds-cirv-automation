from pathlib import Path
import ast
import re
import shutil

collector = Path("collectors/grfc.py")
app = Path("cirv_all_data_app.py")

collector_text = collector.read_text(encoding="utf-8-sig")
app_text = app.read_text(encoding="utf-8-sig")

helper_name = "_verified_grfc_analysis_period"

helper = r'''
def _verified_grfc_analysis_period(pdf_file):
    """
    Extract the report edition and report-wide annual analysis year.

    This does not infer country-specific assessment months.
    """

    with pymupdf.open(pdf_file) as document:
        opening_text = "\n".join(
            document[index].get_text("text")
            for index in range(min(20, document.page_count))
        )

    compact = re.sub(r"\s+", " ", opening_text)

    edition_match = re.search(
        r"(?:GLOBAL REPORT ON FOOD CRISES|GRFC)"
        r"\s*(?:\([^)]*\)\s*)?(20\d{2})",
        compact,
        flags=re.IGNORECASE,
    )

    if edition_match is None:
        raise RuntimeError(
            "Could not verify the GRFC edition from the PDF."
        )

    edition = int(edition_match.group(1))

    # These scoring groups are edition-specific, not dynamically
    # extracted phase-population tables.
    if edition != REPORT_YEAR:
        raise RuntimeError(
            f"PDF edition is {edition}, but this collector's "
            f"severity groups are configured for {REPORT_YEAR}. "
            "Current output was not replaced."
        )

    analysis_year = int(ANALYSIS_YEAR)

    evidence_pattern = re.compile(
        r"(?:acute food insecurity|food crises)"
        r".{0,300}?\b(?:in|during)\s+"
        + str(analysis_year)
        + r"\b",
        flags=re.IGNORECASE,
    )

    evidence_match = evidence_pattern.search(compact)

    if evidence_match is None:
        raise RuntimeError(
            f"Could not verify analysis year {analysis_year} "
            "in the PDF's introductory text. "
            "Current output was not replaced."
        )

    return {
        "report_year": edition,
        "analysis_year": analysis_year,
        "period": f"{analysis_year} — annual analysis",
        "evidence": evidence_match.group(0),
    }

'''

# Insert helper before save_outputs(), using the actual function
# definition rather than matching a large whitespace-sensitive block.
tree = ast.parse(collector_text)
save_function = next(
    (
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "save_outputs"
    ),
    None,
)

if save_function is None:
    raise RuntimeError(
        "save_outputs() was not found. No changes made."
    )

if helper_name not in collector_text:
    lines = collector_text.splitlines(keepends=True)
    insertion = sum(
        len(line)
        for line in lines[:save_function.lineno - 1]
    )
    collector_text = (
        collector_text[:insertion]
        + helper
        + "\n"
        + collector_text[insertion:]
    )

# Insert period enrichment at the beginning of save_outputs().
marker = "# GRFC_PERIOD_ENRICHMENT"

if marker not in collector_text:
    tree = ast.parse(collector_text)
    save_function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "save_outputs"
    )

    first_statement = save_function.body[0]
    lines = collector_text.splitlines(keepends=True)
    insertion = sum(
        len(line)
        for line in lines[:first_statement.lineno - 1]
    )

    enrichment = '''    # GRFC_PERIOD_ENRICHMENT
    period_info = _verified_grfc_analysis_period(pdf_file)

    results["GRFC_Time_Period"] = period_info["period"]
    results["GRFC_Report_Year"] = period_info["report_year"]
    results["GRFC_Analysis_Year"] = period_info["analysis_year"]
    results["GRFC_Period_Scope"] = "Report-wide annual analysis"
    results["GRFC_Period_Evidence"] = period_info["evidence"]
    results["GRFC_Source_File"] = pdf_file.name
    results["GRFC_Source_SHA256"] = calculate_hash(pdf_file)

'''

    collector_text = (
        collector_text[:insertion]
        + enrichment
        + collector_text[insertion:]
    )

# The working integration app already has a period assignment loop.
# Add the collector's actual new field to that loop.
old = "for col in ['GRFC_Time_Period','GRFC_Period']:"
new = (
    "for col in "
    "['GRFC_Time_Period','GRFC_Period']:"
)

if old not in app_text:
    raise RuntimeError(
        "The expected GRFC period mapping was not found in the app. "
        "No files were changed."
    )

# Mapping already recognizes GRFC_Time_Period; no replacement needed.
# Remove the old informational message once the field is populated.
# Its existing condition will automatically suppress it.

compile(collector_text, str(collector), "exec")
compile(app_text, str(app), "exec")

shutil.copy2(
    collector,
    collector.with_suffix(".py.before_period.bak"),
)

collector.write_text(collector_text, encoding="utf-8")

print("SUCCESS: verified GRFC annual period added.")
print("The app already recognizes GRFC_Time_Period.")
print("No phase scores or Food/CIRV formulas were changed.")
