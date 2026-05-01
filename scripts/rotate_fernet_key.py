#!/usr/bin/env python3
"""Fernet key rotation: decrypt all stored tokens with the old key, re-encrypt with the new key.

All updates happen in a single transaction — if any token fails to decrypt, the
entire rotation is rolled back and the database is left unchanged.

Usage:
    python scripts/rotate_fernet_key.py --old-key OLD_KEY --new-key NEW_KEY

Generate a fresh key:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Steps:
    1. Generate a new Fernet key (command above).
    2. Run this script with the current key as --old-key and the new key as --new-key.
    3. Once the script prints "Done", set FERNET_KEY=<new-key> in your environment / .env.
    4. Restart the application.
"""
import argparse
import os
import sys

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def rotate(old_key: str, new_key: str, database_url: str) -> None:
    # Validate both keys are valid Fernet keys before touching the database.
    try:
        old_fernet = Fernet(old_key.encode())
    except Exception as exc:
        print(f"ERROR: --old-key is not a valid Fernet key: {exc}")
        sys.exit(1)

    try:
        new_fernet = Fernet(new_key.encode())
    except Exception as exc:
        print(f"ERROR: --new-key is not a valid Fernet key: {exc}")
        sys.exit(1)

    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)

    # Import after engine creation so the module-level settings object is not
    # instantiated prematurely (it requires env vars to be present).
    from app.models import User  # noqa: PLC0415

    with Session() as session:
        users = session.query(User).all()
        print(f"Found {len(users)} user(s). Starting rotation...")

        for user in users:
            # --- access_token_enc ---
            try:
                plaintext = old_fernet.decrypt(user.access_token_enc.encode()).decode()
            except InvalidToken:
                print(
                    f"ERROR: Cannot decrypt access_token for user '{user.github_login}' "
                    "with the supplied old key. Aborting — no changes written."
                )
                session.rollback()
                sys.exit(1)
            user.access_token_enc = new_fernet.encrypt(plaintext.encode()).decode()

            # --- refresh_token_enc (optional) ---
            if user.refresh_token_enc:
                try:
                    plaintext = old_fernet.decrypt(
                        user.refresh_token_enc.encode()
                    ).decode()
                except InvalidToken:
                    print(
                        f"ERROR: Cannot decrypt refresh_token for user '{user.github_login}' "
                        "with the supplied old key. Aborting — no changes written."
                    )
                    session.rollback()
                    sys.exit(1)
                user.refresh_token_enc = new_fernet.encrypt(plaintext.encode()).decode()

            print(f"  Rotated tokens for '{user.github_login}'")

        session.commit()
        print(
            f"\nDone. Rotated tokens for {len(users)} user(s).\n"
            "Next step: set FERNET_KEY=<new-key> in your environment and restart the app."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate the Fernet encryption key for all stored OAuth tokens."
    )
    parser.add_argument(
        "--old-key",
        required=True,
        help="Current FERNET_KEY value (base64url-encoded, 32 bytes).",
    )
    parser.add_argument(
        "--new-key",
        required=True,
        help="New FERNET_KEY to rotate to.",
    )
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "postgresql://localhost/zapbridge")
    rotate(args.old_key, args.new_key, database_url)


if __name__ == "__main__":
    main()
