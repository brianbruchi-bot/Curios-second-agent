import json
import os
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

VIDEO = Path("output/curios_short.mp4")
TOKEN_SECRET = os.environ.get("YOUTUBE_TOKEN_JSON", "")
PRIVACY = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private").lower()
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def validate_token_info(token_info):
    if not isinstance(token_info, dict):
        raise ValueError('YOUTUBE_TOKEN_JSON must contain a JSON object.')
    required = ('client_id', 'client_secret', 'refresh_token', 'token_uri')
    missing = [key for key in required if not token_info.get(key)]
    if missing:
        raise ValueError('YouTube OAuth data is missing required fields: ' + ', '.join(missing))
    return token_info


def main():
    if not VIDEO.exists():
        raise FileNotFoundError(f"Generated video not found: {VIDEO}")
    if not TOKEN_SECRET:
        raise RuntimeError("YOUTUBE_TOKEN_JSON is missing; YouTube upload is not authorized.")
    if PRIVACY not in {"private", "unlisted", "public"}:
        raise ValueError("YOUTUBE_PRIVACY_STATUS must be private, unlisted, or public.")

    token_info = validate_token_info(json.loads(TOKEN_SECRET))
    credentials = Credentials.from_authorized_user_info(token_info, SCOPES)
    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    title = Path("output/title.txt").read_text(encoding="utf-8").replace("\n", " ").strip()
    description = Path("output/description.txt").read_text(encoding="utf-8").strip()
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
