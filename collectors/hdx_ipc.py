import os
from datetime import date

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv


# ==================================================
# SETTINGS
# ==================================================

load_dotenv()

HDX_APP_IDENTIFIER = os.getenv(
    "HDX_APP_IDENTIFIER"
)

HDX_IPC_URL = (
    "https://hapi.humdata.org/api/v2/"
    "food-security-nutrition-poverty/"
    "food-security"
)


# ==================================================
# DOWNLOAD LIVE HDX IPC DATA
# ==================================================

def download_hdx_ipc():
    """
    Retrieve current IPC data from HDX HAPI.

    Dynamic updating:
    Every run queries HDX directly, so newly published
    IPC analyses are automatically included.

    The API date filter is used to reduce the amount
    of data downloaded.

    IMPORTANT:
    HDX can return records whose reference periods
    overlap the requested date window.

    Therefore, the strict CERF 12-month cutoff is
    applied separately in calculate_country_ipc().
    """

    if not HDX_APP_IDENTIFIER:
        raise RuntimeError(
            "HDX_APP_IDENTIFIER was not found in .env"
        )

    today = date.today()

    start_date = (
        today - relativedelta(months=12)
    )

    print("Checking HDX for latest IPC data...")
    print(f"Nominal lookback start: {start_date}")
    print(f"Lookback end:           {today}")

    all_rows = []

    limit = 10000
    offset = 0

    while True:

        params = {
            "app_identifier": HDX_APP_IDENTIFIER,

            # Current IPC periods only.
            # Projections are excluded.
            "ipc_type": "current",

            "start_date": start_date.isoformat(),
            "end_date": today.isoformat(),

            "output_format": "json",

            "limit": limit,
            "offset": offset,
        }

        response = requests.get(
            HDX_IPC_URL,
            params=params,
            timeout=120,
        )

        response.raise_for_status()

        result = response.json()

        rows = result.get(
            "data",
            []
        )

        all_rows.extend(rows)

        print(
            f"Retrieved {len(all_rows)} IPC rows..."
        )

        # HDX returns at most 10,000 records
        # in one response.
        if len(rows) < limit:
            break

        offset += limit

    return pd.DataFrame(all_rows)


# ==================================================
# CALCULATE COUNTRY IPC
# ==================================================

def calculate_country_ipc(data):
    """
    Apply the CERF IPC methodology.

    Rules:

    1. Current-period IPC only.
    2. Strict previous 12-month lookback.
    3. Exclude projections.
    4. Keep IPC phases 1-5 only.
    5. Population in the phase must be > 0.
    6. Take the highest eligible IPC phase
       recorded for each country.

    Returns one IPC value per ISO3 country.
    """

    if data.empty:
        raise RuntimeError(
            "HDX returned no IPC data."
        )

    working = data.copy()


    # ==================================================
    # DATE RULE
    # ==================================================

    today = pd.Timestamp(
        date.today()
    )

    lookback_start = (
        today - pd.DateOffset(months=12)
    )


    # Read HDX reference dates.

    working["Reference_Start"] = pd.to_datetime(
        working["reference_period_start"],
        errors="coerce",
    ).dt.tz_localize(None)

    working["Reference_End"] = pd.to_datetime(
        working["reference_period_end"],
        errors="coerce",
    ).dt.tz_localize(None)


    # --------------------------------------------------
    # STRICT NOMINAL 12-MONTH LOOKBACK
    #
    # An analysis must BEGIN within the preceding
    # 12 months.
    #
    # This prevents an older record from being included
    # simply because its reference period overlaps the
    # beginning of our 12-month window.
    # --------------------------------------------------

    working = working[
        (
            working["Reference_Start"]
            >= lookback_start
        )
        &
        (
            working["Reference_Start"]
            <= today
        )
    ].copy()


    # ==================================================
    # CURRENT PERIOD ONLY
    # ==================================================

    # The API query already requests current periods,
    # but enforce it again locally as a safeguard.

    working = working[
        working["ipc_type"]
        .astype(str)
        .str.lower()
        .eq("current")
    ].copy()


    # ==================================================
    # IPC PHASE
    # ==================================================

    working["IPC_Phase"] = pd.to_numeric(
        working["ipc_phase"],
        errors="coerce",
    )


    # Keep only genuine IPC phases 1-5.
    #
    # This excludes aggregate categories such as:
    #
    # all
    # 3+

    working = working[
        working["IPC_Phase"].isin(
            [1, 2, 3, 4, 5]
        )
    ].copy()


    # ==================================================
    # POPULATION RULE
    # ==================================================

    working["Population"] = pd.to_numeric(
        working["population_in_phase"],
        errors="coerce",
    )


    # A phase counts only if at least one person
    # is recorded in that phase.

    working = working[
        working["Population"] > 0
    ].copy()


    # ==================================================
    # COUNTRY CODE
    # ==================================================

    working["ISO3"] = (
        working["location_code"]
        .astype(str)
        .str.upper()
        .str.strip()
    )


    working = working[
        working["ISO3"].str.match(
            r"^[A-Z]{3}$"
        )
    ].copy()


    # ==================================================
    # HIGHEST IPC PHASE PER COUNTRY
    # ==================================================

    # Sort so that the highest phase is first.
    #
    # If several records contain the same highest
    # phase, retain the most recently starting
    # reference period.

    working = working.sort_values(
        [
            "ISO3",
            "IPC_Phase",
            "Reference_Start",
            "Reference_End",
            "Population",
        ],
        ascending=[
            True,
            False,
            False,
            False,
            False,
        ],
    )


    # Keep ONE evidence row per country.

    country_ipc = (
        working
        .drop_duplicates(
            subset=["ISO3"],
            keep="first",
        )
        .copy()
    )


    # ==================================================
    # OUTPUT
    # ==================================================

    country_ipc = country_ipc[
        [
            "ISO3",
            "location_name",
            "IPC_Phase",
            "Population",
            "Reference_Start",
            "Reference_End",
            "resource_hdx_id",
        ]
    ]


    country_ipc = country_ipc.rename(
        columns={
            "location_name": "Country",
            "IPC_Phase": "HDX_IPC",
            "resource_hdx_id": "HDX_Resource_ID",
        }
    )


    country_ipc = (
        country_ipc
        .sort_values("Country")
        .reset_index(drop=True)
    )


    return country_ipc


# ==================================================
# COMPLETE HDX IPC UPDATE
# ==================================================

def update_hdx_ipc():
    """
    Complete dynamic HDX IPC workflow.

    1. Query live HDX HAPI.
    2. Retrieve current-period IPC data.
    3. Apply strict rolling 12-month cutoff.
    4. Remove projections/aggregate phases.
    5. Require population > 0.
    6. Select highest eligible IPC phase
       for each country.
    """

    raw_data = download_hdx_ipc()

    country_ipc = calculate_country_ipc(
        raw_data
    )

    return raw_data, country_ipc


# ==================================================
# RUN COLLECTOR DIRECTLY
# ==================================================

if __name__ == "__main__":

    raw_data, country_ipc = update_hdx_ipc()

    print()
    print("=" * 70)
    print("HDX IPC UPDATE SUCCESSFUL")
    print("=" * 70)

    print(
        f"Raw API records retrieved: "
        f"{len(raw_data)}"
    )

    print(
        f"Countries with eligible IPC data: "
        f"{len(country_ipc)}"
    )

    print()

    # Make dates easier to read in the terminal.
    display = country_ipc.copy()

    display["Reference_Start"] = (
        display["Reference_Start"]
        .dt.strftime("%Y-%m-%d")
    )

    display["Reference_End"] = (
        display["Reference_End"]
        .dt.strftime("%Y-%m-%d")
    )

    print(
        display[
            [
                "Country",
                "ISO3",
                "HDX_IPC",
                "Population",
                "Reference_Start",
                "Reference_End",
            ]
        ]
        .to_string(index=False)
    )