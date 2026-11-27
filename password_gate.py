"""Password prompt for the hosted CIRV app.

Uses the team's usual password for protected pages. Only the SHA-256 hash is
stored here, because this repo is public. The check runs on the server, so no
data, tables or charts are sent until the right password is entered. The
password is asked for again after a page reload.
"""
import hashlib
import hmac

import streamlit as st

PASSWORD_SHA256 = "524bf4f9f04b483effef0adac9165374f2dafdc22013b0ffa5545fdc9a8e0586"


def require_password():
    """Stop the page here unless the right password has been entered in this session."""
    if st.session_state.get("cirv_unlocked"):
        return
    password = st.text_input("Password", type="password")
    if password:
        digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if hmac.compare_digest(digest, PASSWORD_SHA256):
            st.session_state["cirv_unlocked"] = True
            st.rerun()
        st.error("Wrong password.")
    st.stop()
