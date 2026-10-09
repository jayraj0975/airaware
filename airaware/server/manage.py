"""Server housekeeping from the command line.

    python -m airaware.server.manage create-admin you@example.com "Your Name"   # asks for the password
    python -m airaware.server.manage make-admin you@example.com                 # promote an existing account

    python -m airaware.server.manage reset-2fa you@example.com                  # an admin lost their authenticator

This is the only way to make an admin: the site does not verify email ownership, so it never grants admin on sign-up.
"""

import getpass
import sys

from airaware.server import auth, db


def main(argv: list[str]) -> int:
    db.init()
    if len(argv) >= 2 and argv[0] == "create-admin":
        email = auth.check_email(argv[1])
        name = argv[2] if len(argv) > 2 else email.split("@")[0]
        password = getpass.getpass("Password for the admin account: ")
        auth.check_new_password(password)
        db.run("INSERT INTO users (email, name, pw_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
               (email, name, auth.hash_password(password), db.now()))
        db.audit("admin.created_from_cli", None, email)
        print(f"Admin {email} created.")
        return 0
    if len(argv) == 2 and argv[0] == "make-admin":
        if not db.run("UPDATE users SET role = 'admin' WHERE email = ?", (argv[1],)):
            print(f"No account for {argv[1]}.")
            return 1
        db.audit("admin.promoted_from_cli", None, argv[1])
        print(f"{argv[1]} is now an admin.")
        return 0
    if len(argv) == 2 and argv[0] == "reset-2fa":
        if not db.run("UPDATE users SET totp_secret = NULL, totp_enabled_at = NULL, totp_last_step = NULL WHERE email = ?", (argv[1],)):
            print(f"No account for {argv[1]}.")
            return 1
        db.audit("admin.2fa_reset_from_cli", None, argv[1])
        print(f"Two-step sign-in turned off for {argv[1]}; they can set it up again.")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
