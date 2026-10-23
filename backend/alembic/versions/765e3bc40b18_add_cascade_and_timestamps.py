"""Add CASCADE and timestamps

Revision ID: 765e3bc40b18
Revises: 01ac5fbc923b
Create Date: 2026-01-10 11:23:30.295835

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '765e3bc40b18'
down_revision: Union[str, Sequence[str], None] = '01ac5fbc923b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    
    # ====== PERMISSIONS TABLE ======
    # Add unique constraint on code (if it doesn't exist)
    op.create_unique_constraint('uq_permission_code', 'permissions', ['code'])
    
    # ====== ROLE_PERMISSION TABLE ======
    # Step 1: Add created_at column with default
    # The server_default ensures existing rows get a value automatically
    op.add_column('role_permission', 
        sa.Column('created_at', 
                  sa.DateTime(timezone=True), 
                  server_default=sa.text('CURRENT_TIMESTAMP'), 
                  nullable=False))
    
    # Step 2: Update foreign keys to add CASCADE
    # Drop existing foreign keys
    op.drop_constraint('role_permission_permission_id_fkey', 'role_permission', type_='foreignkey')
    op.drop_constraint('role_permission_role_id_fkey', 'role_permission', type_='foreignkey')
    
    # Create new foreign keys with CASCADE
    op.create_foreign_key(
        'role_permission_permission_id_fkey',  # Named constraint for easier management
        'role_permission', 'permissions',
        ['permission_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'role_permission_role_id_fkey',
        'role_permission', 'roles',
        ['role_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # ====== ROLES TABLE ======
    # Add unique constraint on code
    op.create_unique_constraint('uq_role_code', 'roles', ['code'])
    
    # ====== USER_PERMISSION TABLE ======
    # Add created_at column with default
    op.add_column('user_permission',
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP'),
                  nullable=False))
    
    # Update foreign keys to add CASCADE
    op.drop_constraint('user_permission_permission_id_fkey', 'user_permission', type_='foreignkey')
    op.drop_constraint('user_permission_user_id_fkey', 'user_permission', type_='foreignkey')
    
    op.create_foreign_key(
        'user_permission_permission_id_fkey',
        'user_permission', 'permissions',
        ['permission_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'user_permission_user_id_fkey',
        'user_permission', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # ====== USER_ROLE TABLE ======
    # Add created_at column with default
    op.add_column('user_role',
        sa.Column('created_at',
                  sa.DateTime(timezone=True),
                  server_default=sa.text('CURRENT_TIMESTAMP'),
                  nullable=False))
    
    # Update foreign keys to add CASCADE
    op.drop_constraint('user_role_user_id_fkey', 'user_role', type_='foreignkey')
    op.drop_constraint('user_role_role_id_fkey', 'user_role', type_='foreignkey')
    
    op.create_foreign_key(
        'user_role_user_id_fkey',
        'user_role', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE'
    )
    op.create_foreign_key(
        'user_role_role_id_fkey',
        'user_role', 'roles',
        ['role_id'], ['id'],
        ondelete='CASCADE'
    )


def downgrade() -> None:
    """Downgrade schema."""
    
    # ====== USER_ROLE TABLE ======
    # Drop CASCADE foreign keys
    op.drop_constraint('user_role_role_id_fkey', 'user_role', type_='foreignkey')
    op.drop_constraint('user_role_user_id_fkey', 'user_role', type_='foreignkey')
    
    # Recreate original foreign keys (without CASCADE)
    op.create_foreign_key('user_role_role_id_fkey', 'user_role', 'roles', ['role_id'], ['id'])
    op.create_foreign_key('user_role_user_id_fkey', 'user_role', 'users', ['user_id'], ['id'])
    
    # Drop created_at column
    op.drop_column('user_role', 'created_at')
    
    # ====== USER_PERMISSION TABLE ======
    # Drop CASCADE foreign keys
    op.drop_constraint('user_permission_permission_id_fkey', 'user_permission', type_='foreignkey')
    op.drop_constraint('user_permission_user_id_fkey', 'user_permission', type_='foreignkey')
    
    # Recreate original foreign keys
    op.create_foreign_key('user_permission_user_id_fkey', 'user_permission', 'users', ['user_id'], ['id'])
    op.create_foreign_key('user_permission_permission_id_fkey', 'user_permission', 'permissions', ['permission_id'], ['id'])
    
    # Drop created_at column
    op.drop_column('user_permission', 'created_at')
    
    # ====== ROLES TABLE ======
    op.drop_constraint('uq_role_code', 'roles', type_='unique')
    
    # ====== ROLE_PERMISSION TABLE ======
    # Drop CASCADE foreign keys
    op.drop_constraint('role_permission_permission_id_fkey', 'role_permission', type_='foreignkey')
    op.drop_constraint('role_permission_role_id_fkey', 'role_permission', type_='foreignkey')
    
    # Recreate original foreign keys
    op.create_foreign_key('role_permission_role_id_fkey', 'role_permission', 'roles', ['role_id'], ['id'])
    op.create_foreign_key('role_permission_permission_id_fkey', 'role_permission', 'permissions', ['permission_id'], ['id'])
    
    # Drop created_at column
    op.drop_column('role_permission', 'created_at')
    
    # ====== PERMISSIONS TABLE ======
    op.drop_constraint('uq_permission_code', 'permissions', type_='unique')