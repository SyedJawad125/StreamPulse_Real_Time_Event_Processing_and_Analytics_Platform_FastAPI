"""Test script to verify model definitions without loading config"""
import sys
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

# Create a minimal Base for testing
Base = declarative_base()

# Manually import the model definitions without database connection
sys.path.insert(0, '.')

# Check each model file
print("Checking model files...")

# Check User model
try:
    with open('app/models/user.py', 'r') as f:
        content = f.read()
        assert 'class User' in content
        assert 'employee' in content
        assert 'created_employees' in content
        assert 'created_images' in content
        assert 'created_image_categories' in content
        print("✅ User model - OK")
except Exception as e:
    print(f"❌ User model - ERROR: {e}")

# Check Employee model
try:
    with open('app/models/employee.py', 'r') as f:
        content = f.read()
        assert 'class Employee' in content
        assert 'department_id' in content
        assert 'rank_id' in content
        assert 'creator' in content
        assert 'updater' in content
        assert 'deleter' in content
        print("✅ Employee model - OK")
except Exception as e:
    print(f"❌ Employee model - ERROR: {e}")

# Check Image model
try:
    with open('app/models/image.py', 'r') as f:
        content = f.read()
        assert 'class Image' in content
        assert 'class ImageCategory' in content
        assert 'original_filename' in content
        assert 'file_size' in content
        assert 'mime_type' in content
        assert 'bulletsdescription' in content
        print("✅ Image model - OK")
except Exception as e:
    print(f"❌ Image model - ERROR: {e}")

# Check models/__init__.py
try:
    with open('app/models/__init__.py', 'r') as f:
        content = f.read()
        assert 'from app.models.employee import Employee' in content
        assert 'from app.models.image import Image' in content
        assert 'from app.models.image_category import ImageCategory' in content
        assert '"Employee"' in content
        assert '"Image"' in content
        assert '"ImageCategory"' in content
        print("✅ models/__init__.py - OK")
except Exception as e:
    print(f"❌ models/__init__.py - ERROR: {e}")

# Check seed.py for permissions
try:
    with open('app/seed.py', 'r') as f:
        content = f.read()
        assert 'employee' in content.lower()
        assert 'image' in content.lower()
        assert 'image_category' in content.lower()
        print("✅ seed.py permissions - OK")
except Exception as e:
    print(f"❌ seed.py permissions - ERROR: {e}")

print("\n✅ All model checks completed!")
