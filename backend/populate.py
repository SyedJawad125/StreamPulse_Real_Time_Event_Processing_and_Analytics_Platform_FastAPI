# from app.database import SessionLocal
# from app.models import User
# from app.utils import get_password_hash
# from sqlalchemy.exc import SQLAlchemyError

# def populate():
#     db = SessionLocal()

#     try:
#         # Step 1: Check/Create superuser
#         superuser = db.query(User).filter(User.username == "adminuser1").first()
#         if not superuser:
#             superuser = User(
#                 username="adminuser1",
#                 email="syedjawadali92@gmail.com",
#                 hashed_password=get_password_hash("password123"),
#                 is_superuser=True,
#                 is_active=True
#             )
#             db.add(superuser)
#             db.commit()
#             db.refresh(superuser)
#             print("✅ Superuser created.")
#         else:
#             print("✅ Superuser already exists.")

#         # ✅ Skip creating role and assigning it to superuser
#         print("ℹ️ Skipping role and permission assignment for superuser. Superuser has all permissions by default.")

#     except SQLAlchemyError as e:
#         db.rollback()
#         print("❌ Error:", str(e))
#     finally:
#         db.close()

# if __name__ == "__main__":
#     populate()







# populate.py
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import User, Role, Permission
from app.utils import get_password_hash
from sqlalchemy.exc import SQLAlchemyError

# Import permissions script
from add_permissions import add_permissions_to_db, get_all_permissions


def create_super_role(db):
    """Create Super role with all permissions"""
    
    try:
        # Get all permissions from database
        all_permissions = get_all_permissions(db)
        
        if not all_permissions:
            print("⚠️  No permissions found. Run permissions_script.py first!")
            return None
        
        # Check if Super role exists
        role = db.query(Role).filter(Role.code == "su").first()
        
        if role:
            # Clear existing permissions
            role.permissions.clear()
            print(f"✅ Found existing Super role (ID: {role.id})")
        else:
            # Create new role
            role = Role(
                name="Super",
                code="su",
                description="Super Admin role with all permissions"
            )
            db.add(role)
            db.flush()  # Get the role ID immediately
            print(f"✅ Created Super role (ID: {role.id})")
        
        # Add all permissions to the role
        role.permissions.extend(all_permissions)
        db.commit()
        db.refresh(role)
        
        print(f"✅ Assigned {len(all_permissions)} permissions to Super role")
        return role
        
    except SQLAlchemyError as e:
        db.rollback()
        print(f"❌ Error creating Super role: {str(e)}")
        raise


def create_employee_role(db):
    """Create Employee role with limited permissions"""
    
    try:
        # Check if Employee role exists
        role = db.query(Role).filter(Role.code == "emp").first()
        
        if role:
            # Clear existing permissions
            role.permissions.clear()
            print(f"✅ Found existing Employee role (ID: {role.id})")
        else:
            # Create new role
            role = Role(
                name="Employee",
                code="emp",
                description="Regular employee role with limited permissions"
            )
            db.add(role)
            db.flush()  # Get the role ID immediately
            print(f"✅ Created Employee role (ID: {role.id})")
        
        # Add limited permissions (read-only for most modules)
        limited_permission_codes = [
            'read_user',
            'read_role',
            'read_permission',
            'read_employee',
            'read_image',
            'read_image_category',
        ]
        
        limited_permissions = db.query(Permission).filter(
            Permission.code.in_(limited_permission_codes)
        ).all()
        
        if limited_permissions:
            role.permissions.extend(limited_permissions)
            db.commit()
            db.refresh(role)
            print(f"✅ Assigned {len(limited_permissions)} permissions to Employee role")
        else:
            db.commit()
            db.refresh(role)
            print("⚠️  No permissions assigned to Employee role")
        
        return role
        
    except SQLAlchemyError as e:
        db.rollback()
        print(f"❌ Error creating Employee role: {str(e)}")
        raise


def create_superuser(db, super_role):
    """Create or update superuser (1st superuser with Super role)"""
    
    try:
        superuser = db.query(User).filter(User.username == "superuser").first()
        
        if not superuser:
            superuser = User(
                username="superuser",
                email="superuser@example.com",
                hashed_password=get_password_hash("Admin@1234"),
                is_superuser=True,  # ✅ SUPERUSER
                is_active=True,
                role_id=super_role.id  # Super role
            )
            db.add(superuser)
            print("✅ Created superuser (1/3)")
        else:
            superuser.is_active = True
            superuser.is_superuser = True  # ✅ SUPERUSER
            superuser.role_id = super_role.id  # Super role
            superuser.hashed_password = get_password_hash("Admin@1234")
            print("✅ Updated existing superuser (1/3)")
        
        db.commit()
        db.refresh(superuser)
        
        print(f"   Username: superuser")
        print(f"   Email: superuser@example.com")
        print(f"   Password: Admin@1234")
        print(f"   Is Superuser: ✅ YES")
        print(f"   Role: {super_role.name} (ID: {super_role.id})")
        
        return superuser
        
    except SQLAlchemyError as e:
        db.rollback()
        print(f"❌ Error creating superuser: {str(e)}")
        raise


def create_admin_user(db, super_role):
    """Create or update admin user (2nd superuser with Super role)"""
    
    try:
        admin = db.query(User).filter(User.email == "syedjawadali92@gmail.com").first()
        
        if not admin:
            admin = User(
                username="syedjawadali92@gmail.com",
                email="syedjawadali92@gmail.com",
                hashed_password=get_password_hash("Admin@1234"),
                is_superuser=True,  # ✅ SUPERUSER
                is_active=True,
                role_id=super_role.id  # Super role
            )
            db.add(admin)
            print("✅ Created admin user (2/3)")
        else:
            admin.is_active = True
            admin.is_superuser = True  # ✅ SUPERUSER
            admin.role_id = super_role.id  # Super role
            admin.hashed_password = get_password_hash("Admin@1234")
            print("✅ Updated existing admin user (2/3)")
        
        db.commit()
        db.refresh(admin)
        
        print(f"   Email: syedjawadali92@gmail.com")
        print(f"   Password: Admin@1234")
        print(f"   Is Superuser: ✅ YES")
        print(f"   Role: {super_role.name} (ID: {super_role.id})")
        
        return admin
        
    except SQLAlchemyError as e:
        db.rollback()
        print(f"❌ Error creating admin user: {str(e)}")
        raise


def create_third_superuser(db, super_role):
    """Create or update 3rd superuser with Super role"""
    
    try:
        user = db.query(User).filter(User.email == "nicenick1992@gmail.com").first()
        
        if not user:
            user = User(
                username="nicenick1992@gmail.com",
                email="nicenick1992@gmail.com",
                hashed_password=get_password_hash("Admin@1234"),
                is_superuser=True,  # ✅ SUPERUSER
                is_active=True,
                role_id=super_role.id  # Super role
            )
            db.add(user)
            print("✅ Created 3rd superuser (3/3)")
        else:
            user.is_active = True
            user.is_superuser = True  # ✅ SUPERUSER
            user.role_id = super_role.id  # Super role
            user.hashed_password = get_password_hash("Admin@1234")
            print("✅ Updated existing 3rd superuser (3/3)")
        
        db.commit()
        db.refresh(user)
        
        print(f"   Email: nicenick1992@gmail.com")
        print(f"   Password: Admin@1234")
        print(f"   Is Superuser: ✅ YES")
        print(f"   Role: {super_role.name} (ID: {super_role.id})")
        
        return user
        
    except SQLAlchemyError as e:
        db.rollback()
        print(f"❌ Error creating 3rd superuser: {str(e)}")
        raise


def populate():
    """Main populate function"""
    db = SessionLocal()
    
    try:
        print("=" * 60)
        print("🚀 Starting Database Population")
        print("=" * 60)
        
        # Step 1: Create permissions
        print("\n📋 Step 1: Creating Permissions...")
        print("-" * 60)
        add_permissions_to_db(db)
        
        # Step 2: Create Super role FIRST
        print("\n" + "=" * 60)
        print("👑 Step 2: Creating Super Role...")
        print("-" * 60)
        super_role = create_super_role(db)
        
        if not super_role:
            print("\n❌ Cannot proceed without Super role. Exiting...")
            return
        
        # Step 3: Create Employee role SECOND (for future use)
        print("\n" + "=" * 60)
        print("👔 Step 3: Creating Employee Role...")
        print("-" * 60)
        employee_role = create_employee_role(db)
        
        # Verify role IDs
        print("\n" + "=" * 60)
        print("🔍 Verifying Role IDs...")
        print("-" * 60)
        print(f"✅ Super role ID: {super_role.id}")
        if employee_role:
            print(f"✅ Employee role ID: {employee_role.id}")
        
        # Step 4: Create 1st superuser
        print("\n" + "=" * 60)
        print("👤 Step 4: Creating 1st Superuser...")
        print("-" * 60)
        create_superuser(db, super_role)
        
        # Step 5: Create 2nd superuser
        print("\n" + "=" * 60)
        print("👤 Step 5: Creating 2nd Superuser...")
        print("-" * 60)
        create_admin_user(db, super_role)
        
        # Step 6: Create 3rd superuser (nicenick1992@gmail.com)
        print("\n" + "=" * 60)
        print("👤 Step 6: Creating 3rd Superuser...")
        print("-" * 60)
        create_third_superuser(db, super_role)  # ✅ Changed: Now creates as superuser
        
        print("\n" + "=" * 60)
        print("✅ Database Population Completed Successfully!")
        print("=" * 60)
        
        # Summary
        print("\n📊 Summary:")
        print(f"   • Permissions: {db.query(Permission).count()}")
        print(f"   • Roles: {db.query(Role).count()}")
        print(f"   • Total Users: {db.query(User).count()}")
        print(f"   • Total Superusers: {db.query(User).filter(User.is_superuser == True).count()}")
        
        print("\n👥 User Details:")
        print(f"   • Users with Super role: {db.query(User).filter(User.role_id == super_role.id).count()}")
        if employee_role:
            print(f"   • Users with Employee role: {db.query(User).filter(User.role_id == employee_role.id).count()}")
        
        print("\n📋 All User Assignments:")
        users_with_roles = db.query(User).all()
        for user in users_with_roles:
            role_name = user.role.name if user.role else "No Role"
            superuser_status = "✅ SUPERUSER" if user.is_superuser else "❌ Regular"
            print(f"   • {user.email}: Role={role_name} (ID: {user.role_id}), {superuser_status}")
        
    except SQLAlchemyError as e:
        db.rollback()
        print(f"\n❌ Error during population: {str(e)}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    populate()
# ```

# ## Key Changes:

# 1. **✅ All 3 users are now SUPERUSERS**:
#    - **User 1** (superuser@example.com): `is_superuser=True`, `role_id = super_role.id`
#    - **User 2** (syedjawadali92@gmail.com): `is_superuser=True`, `role_id = super_role.id`
#    - **User 3** (nicenick1992@gmail.com): `is_superuser=True`, `role_id = super_role.id` ✅ **CHANGED**

# 2. **✅ Created separate function** `create_third_superuser()` for the 3rd user

# 3. **✅ Employee role is still created** (for future use)

# ## Expected Output:
# ```
# 📋 All User Assignments:
#    • superuser@example.com: Role=Super (ID: 1), ✅ SUPERUSER
#    • syedjawadali92@gmail.com: Role=Super (ID: 1), ✅ SUPERUSER
#    • nicenick1992@gmail.com: Role=Super (ID: 1), ✅ SUPERUSER