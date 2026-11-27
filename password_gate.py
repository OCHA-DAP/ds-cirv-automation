"""Password prompt for the hosted CIRV app.

Uses the team's usual password for protected pages. Only hashes are stored
here, because this repo is public. The check runs on the server, so no data,
tables or charts are sent until the right password is entered.

"Remember me" (like our other protected pages): after the right password, the
browser keeps a cookie for 30 days and the prompt is skipped on later visits.
The cookie value is derived from the password, so it can't be rebuilt from
this file, and the server checks it the same way it checks the password.
Changing the password makes old cookies stop working.
"""
import hashlib
import hmac

import streamlit as st

PASSWORD_SHA256 = "524bf4f9f04b483effef0adac9165374f2dafdc22013b0ffa5545fdc9a8e0586"
# SHA-256 of the remember-me token (see _remember_token).
REMEMBER_SHA256 = "193089ab6bc2ddc4be8810cbfd158b1474b07f5385a1a03b9fa5e53e9cba7099"
REMEMBER_COOKIE = "cirv_remember"
REMEMBER_DAYS = 30


def _matches(value, expected_sha256):
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, expected_sha256)


def _remember_token(password):
    return hashlib.sha256(("cirv-remember-v1:" + password).encode("utf-8")).hexdigest()


def _set_cookie(token):
    max_age = REMEMBER_DAYS * 24 * 60 * 60
    st.html(
        "<script>"
        f"document.cookie = '{REMEMBER_COOKIE}={token}; path=/; max-age={max_age}; SameSite=Strict'"
        " + (location.protocol === 'https:' ? '; Secure' : '');"
        "</script>",
        unsafe_allow_javascript=True,
    )


def require_password():
    """Stop the page here unless the right password has been entered in this session."""
    if st.session_state.get("cirv_unlocked"):
        token = st.session_state.pop("cirv_remember_token", None)
        if token:
            _set_cookie(token)
        return
    cookie = st.context.cookies.get(REMEMBER_COOKIE)
    if isinstance(cookie, str) and _matches(cookie, REMEMBER_SHA256):
        st.session_state["cirv_unlocked"] = True
        return
    password = st.text_input("Password", type="password")
    remember = st.checkbox(f"Remember me for {REMEMBER_DAYS} days", value=True)
    if password:
        if _matches(password, PASSWORD_SHA256):
            st.session_state["cirv_unlocked"] = True
            if remember:
                st.session_state["cirv_remember_token"] = _remember_token(password)
            st.rerun()
        st.error("Wrong password.")
    st.stop()
