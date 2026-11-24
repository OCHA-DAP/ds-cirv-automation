import os
from pathlib import Path

import cirv_refresh_runner as runner


def refresh_controls():
    import streamlit as st

    displayed_root = Path(runner.active_root()).resolve()

    @st.fragment(run_every="3s")
    def refresh_button():
        # Reload the whole app only when a new snapshot has been published.
        if Path(runner.active_root()).resolve() != displayed_root:
            st.rerun()

        state = runner.status()
        phase = state.get("state", "idle")
        busy = phase in {"starting", "running"}
        if st.button("Refresh data", type="primary", disabled=busy,
                     key="cirv_refresh_data"):
            outlook = os.environ.get("CIRV_REFRESH_OUTLOOK") == "1"
            ok, message = runner.start("all", outlook)
            if ok:
                st.rerun()
            else:
                st.warning(message)

        if busy:
            st.caption("Refreshing: " + str(state.get("step") or "Starting"))
        elif phase == "failed":
            step = state.get("step") or "Unknown step"
            st.error(f"Refresh failed at {step}. Showing the last published results.")
            if state.get("error"):
                st.caption(str(state["error"]))
        elif not all(
            (displayed_root / "data" / "processed" / name).is_file()
            for name in (
                "fts_funding_detailed.csv",
                "fts_country_annual.csv",
                "fts_country_combined.csv",
            )
        ):
            st.caption("Refresh data to publish the funding charts and workbook.")

    refresh_button()
    return displayed_root
