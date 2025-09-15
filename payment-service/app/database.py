import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

DB_HOST = os.getenv("DB_HOST", "postgres-payment") or os.getenv("POSTGRES_HOST", "postgres-payment")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "fitflow_payments")
DB_USER = os.getenv("DB_USER", "fitflow")
DB_PASSWORD = os.getenv("DB_PASSWORD", "fitflow123")

# Timeouts (env-configurables)
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "2"))                # segundos
DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "2000"))   # milisegundos

DATABASE_URL = (
    f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# connect_timeout para psycopg2
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    poolclass=NullPool,
    connect_args={"connect_timeout": DB_CONNECT_TIMEOUT},
    # echo=True,  # habilítalo si quieres ver SQL en logs
)

# Aplica statement_timeout en cada conexión
@event.listens_for(engine, "connect")
def set_psql_timeouts(dbapi_conn, connection_record):
    try:
        with dbapi_conn.cursor() as cur:
            # Aplica el timeout a todas las sentencias de esta sesión
            cur.execute(f"SET SESSION statement_timeout = {DB_STATEMENT_TIMEOUT_MS}")
    except Exception:
        # No romper el arranque si el server no soporta el comando
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def init_db():
    from .models import Payment  # ensure model import
    Base.metadata.create_all(bind=engine)

def get_session_local():
    return SessionLocal()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
