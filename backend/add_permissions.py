# permissions_script.py
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.permission import Permission


# Define all permissions
PERMISSIONS = [
    # ---------- Role ----------
    {"name": "Show Role", "code": "show_role", "module_name": "Role", "description": "User can see role"},
    {"name": "Create Role", "code": "create_role", "module_name": "Role", "description": "User can create role"},
    {"name": "Read Role", "code": "read_role", "module_name": "Role", "description": "User can read role"},
    {"name": "Update Role", "code": "update_role", "module_name": "Role", "description": "User can update role"},
    {"name": "Delete Role", "code": "delete_role", "module_name": "Role", "description": "User can delete role"},

    # ---------- User ----------
    {"name": "Show User", "code": "show_user", "module_name": "User", "description": "User can see user"},
    {"name": "Create User", "code": "create_user", "module_name": "User", "description": "User can create user"},
    {"name": "Read User", "code": "read_user", "module_name": "User", "description": "User can read user"},
    {"name": "Update User", "code": "update_user", "module_name": "User", "description": "User can update user"},
    {"name": "Delete User", "code": "delete_user", "module_name": "User", "description": "User can delete user"},
    {"name": "Deactivate User", "code": "toggle_user", "module_name": "User", "description": "User can deactivate user"},

    # ---------- Image ----------
    {"name": "Create Image", "code": "create_image", "module_name": "Image", "description": "User can create Image"},
    {"name": "Read Image", "code": "read_image", "module_name": "Image", "description": "User can read Image"},
    {"name": "Update Image", "code": "update_image", "module_name": "Image", "description": "User can update Image"},
    {"name": "Delete Image", "code": "delete_image", "module_name": "Image", "description": "User can delete Image"},

    # ---------- Image Category ----------
    {"name": "Create Image Category", "code": "create_image_category", "module_name": "Image Category", "description": "User can create Image Category"},
    {"name": "Read Image Category", "code": "read_image_category", "module_name": "Image Category", "description": "User can read Image Category"},
    {"name": "Update Image Category", "code": "update_image_category", "module_name": "Image Category", "description": "User can update Image Category"},
    {"name": "Delete Image Category", "code": "delete_image_category", "module_name": "Image Category", "description": "User can delete Image Category"},
    
    # ---------- Permission ----------
    {"name": "Show Permission", "code": "show_permission", "module_name": "Permission", "description": "User can see Permission"},
    {"name": "Create Permission", "code": "create_permission", "module_name": "Permission", "description": "User can create Permission"},
    {"name": "Read Permission", "code": "read_permission", "module_name": "Permission", "description": "User can read Permission"},
    {"name": "Update Permission", "code": "update_permission", "module_name": "Permission", "description": "User can update Permission"},
    {"name": "Delete Permission", "code": "delete_permission", "module_name": "Permission", "description": "User can delete Permission"},

    # ---------- Employee ----------
    {"name": "Create Employee", "code": "create_employee", "module_name": "Employee", "description": "User can create employee"},
    {"name": "Read Employee", "code": "read_employee", "module_name": "Employee", "description": "User can read employee"},
    {"name": "Update Employee", "code": "update_employee", "module_name": "Employee", "description": "User can update employee"},
    {"name": "Delete Employee", "code": "delete_employee", "module_name": "Employee", "description": "User can delete employee"},
]


def add_permissions_to_db(db: Session):
    """Add permissions to database if they don't exist"""
    added_count = 0
    skipped_count = 0
    
    for perm_data in PERMISSIONS:
        existing = db.query(Permission).filter_by(code=perm_data["code"]).first()
        if not existing:
            new_perm = Permission(**perm_data)
            db.add(new_perm)
            added_count += 1
            print(f"✅ Added: {perm_data['name']}")
        else:
            skipped_count += 1
            print(f"⏩ Skipped (already exists): {perm_data['name']}")
    
    db.commit()
    
    print(f"\n📊 Summary: {added_count} added, {skipped_count} skipped")
    return db.query(Permission).all()


def get_all_permissions(db: Session):
    """Get all permissions from database"""
    return db.query(Permission).all()


if __name__ == "__main__":
    print("🚀 Populating permissions...\n")
    db = SessionLocal()
    try:
        add_permissions_to_db(db)
        print("\n✅ Permissions populated successfully!")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        db.rollback()
    finally:
        db.close()