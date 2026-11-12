from pathlib import Path
import json
import time

import requests


# ==================================================
# PROJECT PATHS
# ==================================================

project_folder = Path(__file__).resolve().parent.parent

credentials_file = (
    project_folder
    / "config"
    / "acled_credentials.json"
)

auth_folder = (
    project_folder
    / "data"
    / "raw"
    / "acled"
    / "auth"
)

token_file = auth_folder / "acled_token.json"


# ==================================================
# ACLED AUTHENTICATION URLS
# ==================================================

ACLED_LOGIN_URL = "https://acleddata.com/user/login?_format=json"
ACLED_LOGOUT_URL = "https://acleddata.com/user/logout?_format=json"
ACLED_OAUTH_URL = "https://acleddata.com/oauth/token"


# ==================================================
# PRIVATE CREDENTIALS
# ==================================================
#
# Credentials are NOT stored in this Python file.
#
# Create config/acled_credentials.json containing:
#
# {
#   "ACLED_USERNAME": "YOUR_EMAIL",
#   "ACLED_PASSWORD": "YOUR_PASSWORD"
# }
#
# Do not upload that JSON file or the auth folder.
# ==================================================

ACLED_USERNAME = ""
ACLED_PASSWORD = ""


def validate_credentials():
    """Load and validate credentials from the private JSON file."""

    global ACLED_USERNAME, ACLED_PASSWORD

    if not credentials_file.is_file():
        raise RuntimeError(
            "Missing private ACLED credentials file.\n"
            f"Create: {credentials_file}\n"
            "It must contain ACLED_USERNAME and ACLED_PASSWORD."
        )

    try:
        credentials = json.loads(
            credentials_file.read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "Could not read config/acled_credentials.json.\n"
            "Check that it contains valid JSON."
        ) from exc

    if not isinstance(credentials, dict):
        raise RuntimeError(
            "config/acled_credentials.json must contain a JSON object."
        )

    username = credentials.get("ACLED_USERNAME", "")
    password = credentials.get("ACLED_PASSWORD", "")

    invalid_values = {
        "",
        "YOUR_EMAIL",
        "YOUR_PASSWORD",
        "YOUR_ACLED_EMAIL",
        "YOUR_ACLED_PASSWORD",
        "EMAIL-HERE",
        "PASSWORD-HERE",
        "redacted",
        "REDACTED",
    }

    if not isinstance(username, str):
        raise RuntimeError("ACLED_USERNAME must be a text value.")

    if not isinstance(password, str):
        raise RuntimeError("ACLED_PASSWORD must be a text value.")

    username = username.strip()

    if username in invalid_values:
        raise RuntimeError(
            "Set your actual ACLED_USERNAME in "
            "config/acled_credentials.json."
        )

    if password.strip() in invalid_values:
        raise RuntimeError(
            "Set your actual ACLED_PASSWORD in "
            "config/acled_credentials.json."
        )

    ACLED_USERNAME = username
    ACLED_PASSWORD = password


# ==================================================
# STANDARD SESSION
# ==================================================

def create_base_session():
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/130.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        }
    )

    return session


# ==================================================
# COOKIE-BASED AUTHENTICATION
# ==================================================

def create_authenticated_session():
    """Create an authenticated browser-style session."""

    validate_credentials()

    session = create_base_session()

    payload = {
        "name": ACLED_USERNAME,
        "pass": ACLED_PASSWORD,
    }

    print("Authenticating with myACLED...")

    response = session.post(
        ACLED_LOGIN_URL,
        json=payload,
        timeout=60,
    )

    if response.status_code != 200:
        session.close()
        raise RuntimeError(
            "myACLED login failed.\n"
            f"HTTP status: {response.status_code}\n"
            "Check your credentials and ACLED account access."
        )

    try:
        login_data = response.json()
    except ValueError as exc:
        session.close()
        raise RuntimeError(
            "myACLED login did not return JSON."
        ) from exc

    if not isinstance(login_data, dict):
        session.close()
        raise RuntimeError(
            "myACLED returned an unexpected login response."
        )

    current_user = login_data.get("current_user", {})

    user_id = (
        current_user.get("uid")
        if isinstance(current_user, dict)
        else None
    )

    if not user_id:
        session.close()
        raise RuntimeError(
            "myACLED did not confirm a logged-in user. "
            "Check the username and password."
        )

    print("myACLED authentication successful.")

    return session


# ==================================================
# TOKEN VALIDATION AND STORAGE
# ==================================================

def _save_token_response(response):
    """Validate and save an OAuth token response."""

    try:
        token_data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "ACLED OAuth response was not JSON."
        ) from exc

    if not isinstance(token_data, dict):
        raise RuntimeError(
            "ACLED OAuth returned an unexpected response."
        )

    if not token_data.get("access_token"):
        raise RuntimeError(
            "ACLED OAuth response did not contain an access token."
        )

    try:
        expires_in = int(token_data.get("expires_in", 86400))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "ACLED OAuth returned an invalid token expiry."
        ) from exc

    token_data["obtained_at"] = int(time.time())
    token_data["expires_at"] = (
        token_data["obtained_at"] + expires_in
    )

    auth_folder.mkdir(parents=True, exist_ok=True)

    token_file.write_text(
        json.dumps(token_data, indent=2),
        encoding="utf-8",
    )

    return token_data


# ==================================================
# OAUTH ACCESS TOKEN
# ==================================================

def request_new_oauth_token():
    """Request a new OAuth token using private credentials."""

    validate_credentials()

    payload = {
        "username": ACLED_USERNAME,
        "password": ACLED_PASSWORD,
        "grant_type": "password",
        "client_id": "acled",
        "scope": "authenticated",
    }

    response = requests.post(
        ACLED_OAUTH_URL,
        data=payload,
        timeout=60,
    )

    if response.status_code != 200:
        raise RuntimeError(
            "ACLED OAuth authentication failed.\n"
            f"HTTP status: {response.status_code}\n"
            "Check your credentials and ACLED account access."
        )

    token_data = _save_token_response(response)

    print("New ACLED OAuth token obtained.")

    return token_data


# ==================================================
# LOAD SAVED TOKEN
# ==================================================

def load_saved_token():
    if not token_file.exists():
        return None

    try:
        token_data = json.loads(
            token_file.read_text(encoding="utf-8")
        )
    except (ValueError, OSError):
        return None

    if not isinstance(token_data, dict):
        return None

    if not token_data.get("access_token"):
        return None

    return token_data


# ==================================================
# REFRESH TOKEN
# ==================================================

def refresh_oauth_token(refresh_token):
    payload = {
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "client_id": "acled",
    }

    response = requests.post(
        ACLED_OAUTH_URL,
        data=payload,
        timeout=60,
    )

    if response.status_code != 200:
        return request_new_oauth_token()

    return _save_token_response(response)


# ==================================================
# GET VALID TOKEN
# ==================================================

def get_oauth_token():
    token_data = load_saved_token()
    current_time = int(time.time())

    if token_data:
        try:
            expires_at = int(token_data.get("expires_at", 0))
        except (TypeError, ValueError):
            expires_at = 0

        # Refresh five minutes before expiration.
        if expires_at > current_time + 300:
            return token_data["access_token"]

        refresh_token = token_data.get("refresh_token")

        if refresh_token:
            token_data = refresh_oauth_token(refresh_token)
            return token_data["access_token"]

    token_data = request_new_oauth_token()

    return token_data["access_token"]


# ==================================================
# CREATE API SESSION
# ==================================================

def create_api_session():
    access_token = get_oauth_token()

    session = create_base_session()

    session.headers.update(
        {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
    )

    return session


# ==================================================
# AUTHENTICATION TEST
# ==================================================

if __name__ == "__main__":
    session = create_authenticated_session()

    try:
        response = session.get(
            "https://acleddata.com/api/acled/read?limit=1",
            timeout=60,
        )

        print()
        print("=" * 70)
        print("ACLED AUTHENTICATION TEST")
        print("=" * 70)
        print(f"HTTP status: {response.status_code}")
        print(
            "Response type: "
            f"{response.headers.get('Content-Type')}"
        )
    finally:
        session.close()