import os

from app.database import SessionLocal
from app.models.user import User
from app.services.auth import hash_password


def bootstrap_admin() -> None:
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    display_name = os.getenv("ADMIN_DISPLAY_NAME", "Admin")

    if not email or not password:
        print("ADMIN_EMAIL / ADMIN_PASSWORD not set. Skipping admin bootstrap.")
        return

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            changed = False
            if existing.role != "admin":
                existing.role = "admin"
                changed = True
            if not existing.password_hash:
                existing.password_hash = hash_password(password)
                changed = True
            if not existing.display_name and display_name:
                existing.display_name = display_name
                changed = True
            if changed:
                db.commit()
                print(f"Updated existing admin user: {email}")
            else:
                print(f"Admin user already present: {email}")
            return

        admin = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name,
            role="admin",
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"Created admin user: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap_admin()
