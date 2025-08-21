import os
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Database configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.getenv("DB_NAME", "fitflow_payments")
DB_USER = os.getenv("DB_USER", "sa")
DB_PASSWORD = os.getenv("DB_PASSWORD", "FitFlow123!")

# Azure SQL connection string (para producción)
AZURE_SQL_CONNECTION_STRING = os.getenv("AZURE_SQL_CONNECTION_STRING")

if AZURE_SQL_CONNECTION_STRING:
    # Usar Azure SQL Database
    DATABASE_URL = AZURE_SQL_CONNECTION_STRING
else:
    # Usar SQL Server local
    DATABASE_URL = f"mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"

# SQLAlchemy setup
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "timeout": 20,
    } if not AZURE_SQL_CONNECTION_STRING else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    """Dependency para obtener sesión de base de datos"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def create_database():
    """Crear la base de datos y tablas"""
    try:
        # Intentar crear la base de datos si no existe (solo para SQL Server local)
        if not AZURE_SQL_CONNECTION_STRING:
            master_url = f"mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
            master_engine = create_engine(master_url)
            
            with master_engine.connect() as conn:
                conn.execute(text("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"))
                result = conn.execute(text(f"SELECT database_id FROM sys.databases WHERE name = '{DB_NAME}'"))
                if not result.fetchone():
                    conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
                    print(f"Base de datos '{DB_NAME}' creada exitosamente")
            
            master_engine.dispose()
        
        # Crear todas las tablas
        Base.metadata.create_all(bind=engine)
        print("Tablas creadas exitosamente")
        
    except Exception as e:
        print(f"Error al crear la base de datos: {e}")

def test_connection():
    """Probar la conexión a la base de datos"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as test"))
            print("Conexión a la base de datos exitosa")
            return True
    except Exception as e:
        print(f"Error de conexión a la base de datos: {e}")
        return False