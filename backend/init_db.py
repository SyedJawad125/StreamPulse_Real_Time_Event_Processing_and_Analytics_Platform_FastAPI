# init_db.py
from app.database import Base, engine
from app import models # ensure all models are imported
# from app.models.rank import Rank
# Create all tables
Base.metadata.create_all(bind=engine)
print("✅ Database tables created successfully.")



# delete_temp_table.py
# import sqlite3

# conn = sqlite3.connect("hrms.db")  # put your DB path
# cursor = conn.cursor()

# cursor.execute("DROP TABLE IF EXISTS _alembic_tmp_employees")
# conn.commit()
# conn.close()

# print("Temporary table removed.")
