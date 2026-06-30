"""
Streamlit Cloud Entry Point for Carrier Tender Optimization Dashboard

This file serves as the main entry point for Streamlit Cloud deployment.
It imports and runs the dashboard from the same directory.

The whole run is wrapped so that ANY unhandled exception is shown in-app with its
traceback instead of Streamlit's opaque "Oh no. Error running app." page. On
Streamlit Cloud the normal traceback is hidden from viewers, which makes a crash
impossible to diagnose; surfacing it here (and logging it) means the next failure
is actionable instead of a blank wall.
"""
import logging
import traceback

import streamlit as st

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("streamlit_app")


def _run():
    # Imported inside the guard so an import-time error (e.g. a bad dependency on
    # the hosted environment) is also caught and shown, not swallowed as "Oh no".
    from dashboard import main
    main()


if __name__ == "__main__":
    try:
        _run()
    except Exception as exc:  # noqa: BLE001 - top-level safety net, must catch all
        logger.exception("Dashboard crashed")
        try:
            st.error(
                "💥 The dashboard hit an unexpected error. The details below are "
                "also in the app logs (Manage app → logs)."
            )
            st.exception(exc)
            with st.expander("Full traceback", expanded=False):
                st.code("".join(traceback.format_exc()))
        except Exception:
            # If even rendering the error fails, re-raise so it lands in the logs.
            raise
