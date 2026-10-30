# Curious Second — YouTube Shorts Agent

An automated workflow that finds reusable Wikimedia Commons video, creates a vertical narrated Short, adds captions and attribution, validates the output, and can upload to YouTube after the channel owner authorizes it.

## What it currently does

- Searches Wikimedia Commons for footage with public-domain, CC0, or CC BY 3.0/4.0 licenses.
- Rejects sources with weak or non-English descriptions and avoids sources already recorded in its learning memory.
- Creates English narration from the source creator's description; it does not intentionally invent factual claims.
- Generates a vertical 1080×1920 MP4 with voiceover, subtitles, title, and source attribution.
- Validates video dimensions, audio/video streams, file size, and duration before treating a render as successful.
- Stores a small learning history between GitHub Actions runs using the Actions cache, avoids previously used sources, and favors underused search topics to diversify future Shorts.
- Runs automated tests and Python checks on every push.
- Uploads only when the owner configures YouTube OAuth credentials and explicitly enables uploads. Upload privacy is currently set to **private**.

## Run it

Open the repository's **Actions** tab, choose **Run YouTube Clipping Agent**, then select **Run workflow**. A daily scheduled run is also configured.

Generated MP4 and metadata are saved as a workflow artifact for seven days.

## Release readiness

The automated Python compilation, unit tests, and critical-error lint checks have passed on the current main-branch revision. This verifies code-level behavior only; it does not yet prove that Wikimedia discovery, Edge TTS, FFmpeg rendering, artifact creation, or a real YouTube upload work end to end.

Before enabling public publishing:
1. Run the agent manually and inspect the generated MP4 and attribution metadata.
2. Complete Google OAuth as the channel owner and store the authorized-user JSON in GitHub Actions Secrets.
3. Keep the first upload private and verify the video, title, captions, audio, and attribution in YouTube Studio.
4. Enable public publishing only after the private upload is confirmed.

The agent's current local learning memory tracks successful renders and topic usage. Audience-based optimization is not implemented until YouTube Analytics authorization and real performance data are available.

## YouTube connection

YouTube upload is deliberately disabled until OAuth is configured. The YouTube Data API requires the channel owner to authorize the app; service-account-only access is not supported for ordinary personal channels. Never put Google passwords, OAuth tokens, or client secrets in source files or chat messages. Store credentials only in GitHub Actions Secrets.

Required repository secrets:
- `YOUTUBE_TOKEN_JSON` — OAuth authorized-user JSON with a refresh token.
- `YOUTUBE_UPLOAD_ENABLED` — set to the exact text `true` only after testing.

The workflow currently uploads privately. Change to public only after the owner explicitly chooses that setting.

## Learning

The agent keeps a bounded history of source pages and successful render metadata so it can avoid repeating footage and track its own production history. This is not yet audience-based learning: view duration, retention, likes, and comments require YouTube Analytics authorization and actual published video data. No performance-based optimization is claimed until that connection is implemented and tested.

## Current limitations

- A human must complete the one-time Google OAuth authorization.
- Source footage and metadata quality vary; generated Shorts must still be reviewed before public release.
- Narration is grounded in the source description, not independent fact-checking.
- The agent cannot guarantee views, subscribers, or revenue.
