import ast
import json
import os
import re
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

VIDEO = Path("output/curios_short.mp4")
TITLE_FILE = Path("output/title.txt")
DESCRIPTION_FILE = Path("output/description.txt")
ATTRIBUTION_FILE = Path("output/attribution.json")
TOKEN_SECRET = os.environ.get("YOUTUBE_TOKEN_JSON", "")
REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
OAUTH_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
PRIVACY = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private").lower()
PUBLIC_PUBLISH_ENABLED = os.environ.get("YOUTUBE_PUBLIC_PUBLISH_ENABLED", "false").lower() == "true"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def parse_token_secret(raw):
    """Accept JSON and common copied JavaScript/Python object formatting."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Quote unquoted object keys, then accept either JSON or a Python-style dict.
        normalized = re.sub(
            r'([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:',
            r'\1"\2":',
            raw.strip(),
        )
        try:
            data = json.loads(normalized)
        except json.JSONDecodeError:
            try:
                data = ast.literal_eval(normalized)
            except (ValueError, SyntaxError) as exc:
                raise ValueError(
                    "YOUTUBE_TOKEN_JSON is not a valid token object. Store only the JSON object, "
                    "not the HTTP request/response text."
                ) from exc

    if not isinstance(data, dict):
        raise ValueError("YOUTUBE_TOKEN_JSON must contain one object.")

    # OAuth Playground responses commonly use access_token/scope rather than
    # the field names expected by google-auth's authorized-user loader.
    if not data.get("token") and data.get("access_token"):
        data["token"] = data["access_token"]
    if not data.get("refresh_token") and REFRESH_TOKEN:
        data["refresh_token"] = REFRESH_TOKEN
    if not data.get("client_id") and OAUTH_CLIENT_ID:
        data["client_id"] = OAUTH_CLIENT_ID
    if not data.get("client_secret") and OAUTH_CLIENT_SECRET:
        data["client_secret"] = OAUTH_CLIENT_SECRET
    data.setdefault("token_uri", "https://oauth2.googleapis.com/token")
    scopes = data.get("scopes", data.get("scope", SCOPES))
    if isinstance(scopes, str):
        data["scopes"] = scopes.split()
    else:
        data["scopes"] = scopes
    return data


def validate_token_info(token_info):
    if not isinstance(token_info, dict):
        raise ValueError("YOUTUBE_TOKEN_JSON must contain a JSON object.")
    required = ("client_id", "client_secret", "refresh_token", "token_uri")
    missing = [key for key in required if not token_info.get(key)]
    if missing:
        raise ValueError(
            "YouTube OAuth data is missing required fields: " + ", ".join(missing)
            + ". The refresh token and OAuth client ID/secret are required for automatic uploads."
        )
    scopes = token_info.get("scopes", [])
    if isinstance(scopes, str):
        scopes = scopes.split()
    if "https://www.googleapis.com/auth/youtube.upload" not in scopes:
        raise ValueError("OAuth token is missing the YouTube upload scope.")
    return token_info


def validate_privacy_settings(privacy, public_enabled):
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public.")
    if privacy == "public" and not public_enabled:
        raise ValueError("Public publishing is locked. Set YOUTUBE_PUBLIC_PUBLISH_ENABLED=true only after a private test upload is reviewed.")
    return privacy


def validate_upload_package():
    if not VIDEO.exists() or VIDEO.stat().st_size < 100_000:
        raise FileNotFoundError(f"Generated video is missing or too small: {VIDEO}")
    if not TITLE_FILE.exists() or not TITLE_FILE.read_text(encoding="utf-8").strip():
        raise ValueError("Generated YouTube title is missing or empty.")
    if not DESCRIPTION_FILE.exists():
        raise FileNotFoundError(f"Video description is missing: {DESCRIPTION_FILE}")
    description = DESCRIPTION_FILE.read_text(encoding="utf-8").strip()
    if not description or "Footage:" not in description or "License:" not in description:
        raise ValueError("Video description must include source footage and license attribution.")
    if not ATTRIBUTION_FILE.exists():
        raise FileNotFoundError(f"Attribution metadata is missing: {ATTRIBUTION_FILE}")
    attribution = json.loads(ATTRIBUTION_FILE.read_text(encoding="utf-8"))
    required = ("source_page", "license", "creator", "video_title")
    missing = [key for key in required if not attribution.get(key)]
    if missing:
        raise ValueError("Attribution metadata is incomplete: " + ", ".join(missing))
    if attribution["source_page"] not in description:
        raise ValueError("Video description does not contain the attributed source page.")
    return description


def main():
    if not VIDEO.exists():
        raise FileNotFoundError(f"Generated video not found: {VIDEO}")
    validate_upload_package()
    validate_privacy_settings(PRIVACY, PUBLIC_PUBLISH_ENABLED)

    if TOKEN_SECRET:
        token_info = validate_token_info(parse_token_secret(TOKEN_SECRET))
        credentials = Credentials.from_authorized_user_info(token_info, SCOPES)
    elif REFRESH_TOKEN and OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET:
        credentials = Credentials(
            token=None,
            refresh_token=REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=OAUTH_CLIENT_ID,
            client_secret=OAUTH_CLIENT_SECRET,
            scopes=SCOPES,
        )
    else:
        raise RuntimeError("YouTube OAuth is incomplete. Configure YOUTUBE_TOKEN_JSON, or YOUTUBE_REFRESH_TOKEN plus YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET.")
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    title = TITLE_FILE.read_text(encoding="utf-8").replace("\n", " ").strip()
    description = DESCRIPTION_FILE.read_text(encoding="utf-8").strip()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "categoryId": "27",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(str(VIDEO), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk(num_retries=5)
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError(f"YouTube did not return a video ID: {response}")
    print(f"UPLOAD_SUCCESS video_id={video_id} privacy={PRIVACY}")
    print(f"https://www.youtube.com/watch?v={video_id}")


if __name__ == "__main__":
    try:
        main()
    except (HttpError, ValueError, RuntimeError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"UPLOAD_FAILED: {exc}", file=sys.stderr)
        raise
