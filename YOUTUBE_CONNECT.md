# Connect Curious Second to YouTube

This is a one-time owner authorization. The agent cannot bypass Google's consent screen, and you should never share your Google password or OAuth token in ChatGPT.

## 1. Create the Google API project

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project named `Curious Second`.
3. In **APIs & Services → Library**, enable **YouTube Data API v3**.
4. Configure the OAuth consent screen. If the app is in Testing, add the Google account that owns the YouTube channel as a test user. Google may expire refresh tokens for apps left in Testing; check the current Google OAuth policy before relying on unattended long-term uploads.
5. Create an OAuth client ID. For the OAuth Playground method below, use a Web application client and add this exact authorized redirect URI:
   `https://developers.google.com/oauthplayground`

## 2. Authorize the YouTube channel

1. Open the [Google OAuth 2.0 Playground](https://developers.google.com/oauthplayground/).
2. Open its settings (gear icon), enable **Use your own OAuth credentials**, and enter the OAuth client ID and client secret from the Cloud Console.
3. In the scope field, request:
   `https://www.googleapis.com/auth/youtube.upload`
4. Authorize the API using the Google account that owns the intended channel.
5. Exchange the authorization code for tokens. Ensure offline access is requested so a refresh token is returned.
6. Keep the resulting refresh token and client credentials private.

## 3. Store credentials in GitHub

In the repository, open **Settings → Secrets and variables → Actions → New repository secret**.

Create:
- `YOUTUBE_TOKEN_JSON` — a JSON object containing the returned `token`, `refresh_token`, `token_uri` (`https://oauth2.googleapis.com/token`), `client_id`, `client_secret`, and `scopes` array containing `https://www.googleapis.com/auth/youtube.upload`.
- `YOUTUBE_UPLOAD_ENABLED` — exact value `true` only when you are ready to enable uploads.
- Optional: `YOUTUBE_PRIVACY_STATUS` — `private`, `unlisted`, or `public`. If omitted, uploads remain **private**.

Do not put token JSON in repository files, issues, or chat messages.

## 4. Test safely

Run the workflow manually once. Keep privacy set to `private` for the first test and confirm the video appears in YouTube Studio before changing privacy. The workflow skips upload unless both required secrets are configured.
