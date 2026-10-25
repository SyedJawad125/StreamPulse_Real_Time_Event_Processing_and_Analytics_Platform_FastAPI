# add_permissions.py  - create any missing permissions:  python add_permissions.py
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Permission
from app.seed import PERMISSIONS, seed_permissions  # noqa: F401  (PERMISSIONS re-exported for convenience)


def add_permissions_to_db(db: Session):
    """Add permissions to the database if they don't exist."""
    added, skipped = seed_permissions(db, verbose=True)
    print(f"\n📊 Summary: {added} added, {skipped} skipped")
    return db.query(Permission).all()


def get_all_permissions(db: Session):
    return db.query(Permission).all()


if __name__ == "__main__":
    print("🚀 Populating permissions...\n")
    db = SessionLocal()
    try:
        add_permissions_to_db(db)
        print("\n✅ Permissions populated successfully!")
    except Exception as e:  # noqa: BLE001
        print(f"\n❌ Error: {e}")
        db.rollback()
        raise
    finally:
        db.close()
