import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash
from firebase_db import create_user, get_user_by_username

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)

if __name__ == "__main__":
    admin_user = os.getenv("ADMIN_USER")
    admin_pass = os.getenv("ADMIN_PASS")
    admin_email = os.getenv("ADMIN_EMAIL")

    if not admin_user or not admin_pass:
        print("Set ADMIN_USER and ADMIN_PASS in the environment to create an admin user automatically.")
    else:
        if get_user_by_username(admin_user):
            print("Admin user already exists")
        else:
            create_user(admin_user, generate_password_hash(admin_pass), admin_email, "admin")
            print("Admin user created successfully")
