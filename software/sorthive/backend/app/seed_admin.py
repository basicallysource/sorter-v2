from app.database import SessionLocal
from app.models.user import User
from app.services.auth import hash_password


def seed_admin():
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "admin@sorthive.local").first()
        if existing:
            print("Admin user already exists.")
            return

        admin = User(
            email="admin@sorthive.local",
            password_hash=hash_password("admin"),
            display_name="Admin",
            role="admin",
        )
        db.add(admin)
        db.commit()
        print("Admin user created: admin@sorthive.local / admin")
    finally:
        db.close()


if __name__ == "__main__":
    seed_admin()
