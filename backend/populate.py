# populate.py  - seed permissions, default roles and (optionally) the first superuser.
#
#   python populate.py                       # prompts for the superuser's e-mail/password (hidden)
#   python populate.py --reset-roles         # also restore Operator/Analyst/Viewer to their default permissions
#   python populate.py --skip-superuser      # only permissions + roles
#
# Non-interactive: set SUPERUSER_EMAIL, SUPERUSER_PASSWORD (and optionally SUPERUSER_USERNAME).
# There are NO default credentials: nothing is created with a well-known password.
import argparse
import getpass
import os
import sys

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal  # noqa: E402
from app.models import Permission, Role, User  # noqa: E402
from app.seed import seed_permissions, seed_roles  # noqa: E402
from app.utils import get_password_hash, validate_password_strength  # noqa: E402


def create_superuser(db, super_role, email: str, username: str, password: str):
    """Create (or promote/update) a superuser holding the Super role."""
    email = email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user:
        user = User(username=username, email=email, hashed_password=get_password_hash(password),
                    is_superuser=True, is_active=True, role_id=super_role.id)
        db.add(user)
        print("✅ Created superuser")
    else:
        user.is_active = True
        user.is_superuser = True
        user.role_id = super_role.id
        user.hashed_password = get_password_hash(password)
        user.token_version += 1  # old sessions end
        if user.deleted:
            user.restore()
        print("✅ Updated existing user -> superuser")
    db.commit()
    db.refresh(user)
    print(f"   Email: {user.email}\n   Is Superuser: ✅ YES\n   Role: {super_role.name} (ID: {super_role.id})")
    return user


def populate(args) -> None:
    db = SessionLocal()
    try:
        print("=" * 60 + "\n🚀 Starting Database Population\n" + "=" * 60)

        print("\n📋 Step 1: Creating Permissions...\n" + "-" * 60)
        added, skipped = seed_permissions(db, verbose=True)
        print(f"\n📊 {added} added, {skipped} skipped")

        print("\n" + "=" * 60 + "\n👑 Step 2: Creating Roles (Super, Operator, Analyst, Viewer)...\n" + "-" * 60)
        roles = seed_roles(db, reset=args.reset_roles, verbose=True)
        super_role = roles["su"]

        if not args.skip_superuser:
            print("\n" + "=" * 60 + "\n👤 Step 3: Superuser...\n" + "-" * 60)
            existing = db.query(User).filter(User.is_superuser == True, User.deleted == False).count()  # noqa: E712
            if existing and not args.allow_additional:
                print(f"⏩ {existing} superuser(s) already exist - skipping (use --allow-additional to add another)")
            else:
                email = args.email or os.environ.get("SUPERUSER_EMAIL") or input("Superuser e-mail: ").strip()
                username = args.username or os.environ.get("SUPERUSER_USERNAME") or email.split("@")[0]
                password = os.environ.get("SUPERUSER_PASSWORD")
                if not password:
                    password = getpass.getpass(f"Password (min 10 chars, letters + digits): ")
                    if password != getpass.getpass("Repeat password: "):
                        sys.exit("❌ Passwords do not match.")
                validate_password_strength(password)
                create_superuser(db, super_role, email, username, password)

        print("\n" + "=" * 60 + "\n✅ Database Population Completed Successfully!\n" + "=" * 60)
        print("\n📊 Summary:")
        print(f"   • Permissions: {db.query(Permission).count()}")
        print(f"   • Roles: {db.query(Role).count()}")
        print(f"   • Users: {db.query(User).count()}  (superusers: {db.query(User).filter(User.is_superuser == True).count()})")  # noqa: E712
        print("\n📋 User assignments:")
        for user in db.query(User).order_by(User.id).all():
            flag = "✅ SUPERUSER" if user.is_superuser else "❌ Regular"
            print(f"   • {user.email}: Role={user.role.name if user.role else 'No Role'}, {flag}")
    except SQLAlchemyError as e:
        db.rollback()
        print(f"\n❌ Error during population: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed permissions, roles and the first superuser")
    parser.add_argument("--email")
    parser.add_argument("--username")
    parser.add_argument("--skip-superuser", action="store_true")
    parser.add_argument("--allow-additional", action="store_true", help="create another superuser even if one exists")
    parser.add_argument("--reset-roles", action="store_true", help="restore default roles' permissions")
    populate(parser.parse_args())
