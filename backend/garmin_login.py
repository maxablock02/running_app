"""One-time Garmin login. Run from the backend folder:

    .venv\\Scripts\\python garmin_login.py

Prompts for email, password and (if your account has it) a 2FA code, then
saves session tokens to .garmin_tokens/. Your password is not stored.
"""

import getpass

from garminconnect import Garmin

from app.garmin_client import TOKEN_DIR


def main() -> None:
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    TOKEN_DIR.mkdir(exist_ok=True)

    client = Garmin(email, password, prompt_mfa=lambda: input("2FA code (check email/app): ").strip())
    client.login(str(TOKEN_DIR))
    client.client.dump(str(TOKEN_DIR))
    print(f"Logged in as {client.full_name or client.display_name}. Tokens saved to {TOKEN_DIR}")


if __name__ == "__main__":
    main()
