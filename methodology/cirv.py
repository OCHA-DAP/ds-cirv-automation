def calculate_cerf_component(
    early_warning,
    food,
    conflict
):
    """
    Calculate the CERF Multi-Indicator Component.

    Weights:
    Early Warning = 5/33
    Food = 13/33
    Conflict = 15/33
    """

    # Excel effectively has blanks here for countries
    # without an Early Warning score.
    if early_warning is None:
        early_warning = 0

    if food is None:
        food = 0

    if conflict is None:
        conflict = 0

    return (
        early_warning * (5 / 33)
        + food * (13 / 33)
        + conflict * (15 / 33)
    )


def calculate_cirv_without_severity(
    inform_risk,
    cerf_component
):
    """
    CIRV when INFORM Severity is not available.
    """

    return (
        inform_risk * 0.5
        + cerf_component * 0.5
    )


def calculate_cirv_with_severity(
    inform_risk,
    inform_severity,
    cerf_component
):
    """
    CIRV when INFORM Severity is available.
    """

    return (
        inform_risk
        + inform_severity
        + cerf_component
    ) / 3


def calculate_final_cirv(
    inform_risk,
    inform_severity,
    cerf_component
):
    """
    Reproduce the current workbook's adjusted CIRV rule.

    Current workbook:
    If INFORM Severity > 0:
        use CIRV with Severity

    Otherwise:
        use CIRV without Severity
    """

    if (
        inform_severity is not None
        and inform_severity > 0
    ):
        return calculate_cirv_with_severity(
            inform_risk,
            inform_severity,
            cerf_component
        )

    return calculate_cirv_without_severity(
        inform_risk,
        cerf_component
    )