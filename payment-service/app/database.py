
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

DB_HOST = os.getenv("DB_HOST", "postgres-payment") or os.getenv("POSTGRES_HOST", "postgres-payment")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "fitflow_payments")
DB_USER = os.getenv("DB_USER", "fitflow")
DB_PASSWORD = os.getenv("DB_PASSWORD", "fitflow123")

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL, pool_pre_ping=True, poolclass=NullPool)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    from .models import Payment  # ensure model is imported
    Base.metadata.create_all(bind=engine)

def get_session_local():
    return SessionLocal()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
