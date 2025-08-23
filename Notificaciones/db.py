import os
import urllib.parse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DB_URL = os.getenv("DB_URL") 

if not DB_URL:
    user = os.getenv("DB_USER", "sa")
    pwd = os.getenv("DB_PASS", "Admin123!")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "1433")
    database = os.getenv("DB_NAME", "fitflow")

    driver = urllib.parse.quote_plus("ODBC Driver 18 for SQL Server")
    DB_URL = f"mssql+pyodbc://{user}:{pwd}@{host}:{port}/{database}?driver={driver}&TrustServerCertificate=yes"

engine = create_engine(DB_URL, fast_executemany=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()
