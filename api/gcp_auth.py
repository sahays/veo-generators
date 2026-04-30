"""Service-account access tokens for direct Vertex AI WebSocket calls.

The Cloud Run runtime identity has the access we need for the allowlisted
Gemini Live preview model. We mint a short-lived OAuth token here whenever a
new live session opens; tokens last ~1 hour, sessions are minutes, so no
in-session refresh is wired up.
"""

from google.auth import default as google_default_creds
from google.auth.transport.requests import Request as GoogleAuthRequest

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def vertex_access_token() -> str:
    creds, _ = google_default_creds(scopes=[_SCOPE])
    creds.refresh(GoogleAuthRequest())
    if not creds.token:
        raise RuntimeError("google.auth returned empty access token")
    return creds.token
