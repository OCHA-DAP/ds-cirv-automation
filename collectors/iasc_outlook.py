from pathlib import Path
from datetime import datetime, timezone, timedelta
import base64
import json
import os
import re
import sys

import msal
import requests

PROJECT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT / "data" / "raw" / "iasc" / "horizon"
PROCESSED_DIR = PROJECT / "data" / "processed"
CONFIG_DIR = PROJECT / "config"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = CONFIG_DIR / "iasc_outlook.json"
TOKEN_CACHE_FILE = CONFIG_DIR / ".iasc_graph_token_cache.json"
METADATA_FILE = PROCESSED_DIR / "iasc_outlook_metadata.json"

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]
SUPPORTED_EXTENSIONS = {".docx", ".pdf"}
DEFAULT_LOOKBACK_DAYS = 120

DEFAULT_CONFIG = {
    "tenant_id": "PASTE-YOUR-TENANT-ID-HERE",
    "client_id": "PASTE-YOUR-CLIENT-ID-HERE",
    "lookback_days": DEFAULT_LOOKBACK_DAYS,
    "subject_keywords": [
        "horizon scan",
        "horizon scanning",
        "early warning",
    ],
    "attachment_keywords": [
        "horizon",
        "horizon scan",
        "horizon scanning",
        "early warning",
    ],
    "sender_contains": [],
}


def normalize(value):
    return " ".join(str(value or "").strip().lower().split())


def ensure_config():
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(
            json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8"
        )
        raise RuntimeError(
            "Created config/iasc_outlook.json. Open it and replace the placeholder "
            "tenant_id and client_id, then run this collector again."
        )
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    tenant = str(config.get("tenant_id", "")).strip()
    client = str(config.get("client_id", "")).strip()
    if not tenant or "PASTE-YOUR" in tenant or not client or "PASTE-YOUR" in client:
        raise RuntimeError(
            "config/iasc_outlook.json still contains placeholder tenant_id/client_id."
        )
    return config


def load_cache():
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_FILE.exists():
        try:
            cache.deserialize(TOKEN_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return cache


def save_cache(cache):
    if cache.has_state_changed:
        TOKEN_CACHE_FILE.write_text(cache.serialize(), encoding="utf-8")


def acquire_token(config):
    cache = load_cache()
    authority = f"https://login.microsoftonline.com/{config['tenant_id']}"
    app = msal.PublicClientApplication(
        config["client_id"], authority=authority, token_cache=cache
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(
                "Could not start Microsoft device-code authentication: "
                + json.dumps(flow, indent=2)
            )
        print(flow["message"])
        result = app.acquire_token_by_device_flow(flow)

    save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(
            "Microsoft authentication failed: "
            + str(result.get("error_description") or result)
        )
    return result["access_token"]


def graph_get(url, token, params=None):
    response = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        params=params,
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Microsoft Graph request failed ({response.status_code}):\n"
            f"{response.text[:2000]}"
        )
    return response.json()


def sender_address(message):
    sender = message.get("from") or message.get("sender") or {}
    address = sender.get("emailAddress") or {}
    return str(address.get("address") or "").strip()


def subject_matches(subject, keywords):
    normalized = normalize(subject)
    return any(normalize(keyword) in normalized for keyword in keywords)


def sender_matches(sender, allowed_fragments):
    if not allowed_fragments:
        return True
    normalized = normalize(sender)
    return any(normalize(fragment) in normalized for fragment in allowed_fragments)


def attachment_matches(name, keywords):
    path = Path(str(name or ""))
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return False
    normalized = normalize(path.name)
    return any(normalize(keyword) in normalized for keyword in keywords)


def list_recent_messages(token, config):
    lookback = int(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback)
    cutoff_text = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{GRAPH_ROOT}/me/mailFolders/inbox/messages"
    params = {
        "$select": "id,subject,receivedDateTime,from,sender,hasAttachments",
        "$filter": f"receivedDateTime ge {cutoff_text}",
        "$orderby": "receivedDateTime desc",
        "$top": "100",
    }

    messages = []
    while url:
        payload = graph_get(url, token, params=params)
        messages.extend(payload.get("value", []))
        url = payload.get("@odata.nextLink")
        params = None
    return messages


def list_attachments(message_id, token):
    url = f"{GRAPH_ROOT}/me/messages/{message_id}/attachments"
    params = {
        "$select": "id,name,contentType,size,isInline,@odata.type,contentBytes",
        "$top": "50",
    }
    attachments = []
    while url:
        payload = graph_get(url, token, params=params)
        attachments.extend(payload.get("value", []))
        url = payload.get("@odata.nextLink")
        params = None
    return attachments


def clean_filename(name):
    name = Path(str(name)).name
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    return name.strip() or "horizon_scan_attachment"


def write_attachment(attachment, message_id, token):
    filename = clean_filename(attachment["name"])
    destination = RAW_DIR / filename

    content_bytes = attachment.get("contentBytes")
    if content_bytes:
        data = base64.b64decode(content_bytes)
    else:
        # Fallback for Graph responses that omit contentBytes.
        url = (
            f"{GRAPH_ROOT}/me/messages/{message_id}/attachments/"
            f"{attachment['id']}/$value"
        )
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Attachment download failed ({response.status_code}): "
                f"{response.text[:1000]}"
            )
        data = response.content

    # Avoid overwriting a different historical attachment with the same name.
    if destination.exists() and destination.read_bytes() != data:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = RAW_DIR / f"{destination.stem}_{stamp}{destination.suffix}"

    destination.write_bytes(data)
    return destination


def find_latest_horizon_attachment(messages, token, config):
    subject_keywords = config.get("subject_keywords", [])
    attachment_keywords = config.get("attachment_keywords", [])
    sender_fragments = config.get("sender_contains", [])

    candidates = []

    for message in messages:
        if not message.get("hasAttachments"):
            continue
        subject = str(message.get("subject") or "")
        sender = sender_address(message)
        subject_ok = subject_matches(subject, subject_keywords)
        sender_ok = sender_matches(sender, sender_fragments)
        if not sender_ok:
            continue

        attachments = list_attachments(message["id"], token)
        for attachment in attachments:
            if attachment.get("isInline"):
                continue
            if "fileAttachment" not in str(attachment.get("@odata.type", "")):
                continue
            name = str(attachment.get("name") or "")
            attachment_ok = attachment_matches(name, attachment_keywords)

            # Require a strong signal from either the message subject or file name.
            if not (subject_ok or attachment_ok):
                continue
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue

            received = pd_timestamp(message.get("receivedDateTime"))
            candidates.append({
                "message": message,
                "attachment": attachment,
                "received": received,
                "subject_match": subject_ok,
                "attachment_match": attachment_ok,
            })

    if not candidates:
        raise RuntimeError(
            "No recent Outlook attachment matched the Horizon Scan rules. "
            "Review config/iasc_outlook.json keywords/lookback_days."
        )

    candidates.sort(
        key=lambda item: (
            item["received"],
            item["attachment_match"],
            item["subject_match"],
        ),
        reverse=True,
    )
    return candidates[0], candidates


def pd_timestamp(value):
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def save_metadata(selected, destination, candidate_count, config):
    message = selected["message"]
    attachment = selected["attachment"]
    metadata = {
        "source": "Microsoft Outlook via Microsoft Graph",
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "received_at": message.get("receivedDateTime"),
        "email_subject": message.get("subject"),
        "sender": sender_address(message),
        "attachment_filename": attachment.get("name"),
        "saved_path": str(destination),
        "message_id": message.get("id"),
        "attachment_id": attachment.get("id"),
        "attachment_size": attachment.get("size"),
        "subject_match": selected["subject_match"],
        "attachment_match": selected["attachment_match"],
        "qualifying_candidates": candidate_count,
        "lookback_days": int(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS)),
    }
    METADATA_FILE.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def update_iasc_outlook():
    print("Connecting to Outlook through Microsoft Graph...")
    config = ensure_config()
    token = acquire_token(config)

    print("Searching recent Inbox messages for IASC Horizon Scan attachments...")
    messages = list_recent_messages(token, config)
    print(f"Recent messages checked: {len(messages)}")

    selected, candidates = find_latest_horizon_attachment(messages, token, config)
    message = selected["message"]
    attachment = selected["attachment"]

    print("Selected email:")
    print(f"  Received: {message.get('receivedDateTime')}")
    print(f"  Sender: {sender_address(message)}")
    print(f"  Subject: {message.get('subject')}")
    print(f"  Attachment: {attachment.get('name')}")

    destination = write_attachment(attachment, message["id"], token)
    save_metadata(selected, destination, len(candidates), config)

    print("\nIASC OUTLOOK DOWNLOAD COMPLETE")
    print(f"Saved attachment:\n{destination}")
    print(f"Metadata:\n{METADATA_FILE}")
    return destination


if __name__ == "__main__":
    try:
        update_iasc_outlook()
    except Exception as exc:
        print(f"\nIASC OUTLOOK DOWNLOAD FAILED\n{exc}", file=sys.stderr)
        raise
