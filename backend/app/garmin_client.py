"""Garmin Connect access via the unofficial `garminconnect` library.

Credentials are never stored: `garmin_login.py` logs in once (handling 2FA if
enabled) and saves session tokens to TOKEN_DIR. Everything else resumes from
those tokens.
"""

from pathlib import Path

from garminconnect import Garmin

TOKEN_DIR = Path(__file__).resolve().parent.parent / ".garmin_tokens"


class GarminNotLoggedIn(RuntimeError):
    pass


def get_client() -> Garmin:
    if not TOKEN_DIR.exists() or not any(TOKEN_DIR.iterdir()):
        raise GarminNotLoggedIn("No saved Garmin session. Run `python garmin_login.py` in the backend folder.")
    client = Garmin()
    try:
        client.login(str(TOKEN_DIR))
    except Exception as e:  # expired/invalid tokens surface as auth errors without credentials
        raise GarminNotLoggedIn(f"Saved Garmin session is invalid ({e}). Run `python garmin_login.py` again.") from e
    return client
