"""Password prompt for the hosted CIRV app.

Uses the team's usual password for protected pages. The check runs on the
server, so no data, tables or charts are sent until the right password is
entered.

"Remember me" (like our other protected pages): after the right password, the
browser keeps a cookie for up to 30 days (Safari keeps it for about 7) and the
prompt is skipped on later visits. The cookie value is derived from the
password, and the server checks it the same way it checks the password.

The repo is public, so only CHECK_SHA256 is stored, a hash of the cookie value.
To change the password, replace CHECK_SHA256 with the output of:
    python -c "import hashlib; t = hashlib.sha256(b'cirv-remember-v1:' + b'NEW_PASSWORD').hexdigest(); print(hashlib.sha256(t.encode()).hexdigest())"
Old cookies then stop working too.
"""
import hashlib
import hmac

import streamlit as st

CHECK_SHA256 = "193089ab6bc2ddc4be8810cbfd158b1474b07f5385a1a03b9fa5e53e9cba7099"
REMEMBER_COOKIE = "cirv_remember"
REMEMBER_DAYS = 30


def _token(password):
    return hashlib.sha256(("cirv-remember-v1:" + password).encode("utf-8")).hexdigest()


def _token_ok(token):
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, CHECK_SHA256)


def _set_cookie(slot, token):
    max_age = REMEMBER_DAYS * 24 * 60 * 60
    slot.html(
        "<script>"
        f"document.cookie = '{REMEMBER_COOKIE}={token}; path=/; max-age={max_age}; SameSite=Strict'"
        " + (location.protocol === 'https:' ? '; Secure' : '');"
        "</script>",
        unsafe_allow_javascript=True,
    )


def require_password():
    """Stop the page here unless the right password has been entered in this session."""
    # Same hidden slot on every run, so the page below never shifts when the
    # one-off cookie script is added or removed.
    slot = st.empty()
    if st.session_state.get("cirv_unlocked"):
        token = st.session_state.get("cirv_remember_token")
        if token:
            _set_cookie(slot, token)
            del st.session_state["cirv_remember_token"]
        return
    cookie = st.context.cookies.get(REMEMBER_COOKIE)
    if isinstance(cookie, str) and _token_ok(cookie):
        st.session_state["cirv_unlocked"] = True
        return
    password = st.text_input("Password", type="password")
    remember = st.checkbox("Remember me", value=True)
    if password:
        token = _token(password)
        if _token_ok(token):
            st.session_state["cirv_unlocked"] = True
            if remember:
                st.session_state["cirv_remember_token"] = token
            st.rerun()
        st.error("Wrong password.")
    st.stop()
