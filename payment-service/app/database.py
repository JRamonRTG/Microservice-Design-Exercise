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
    # Usar SQL Server local - CORREGIDO: sin autocommit en connect_args
    DATABASE_URL = f"mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=no"

# SQLAlchemy setup - CORREGIDO: configuración mejorada
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    # REMOVIDO: autocommit=True de connect_args - causaba problemas
    connect_args={
        "timeout": 30,
        "autocommit": False  # IMPORTANTE: False para transacciones correctas
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
        # CORREGIDO: Crear conexión especial para operaciones DDL
        if not AZURE_SQL_CONNECTION_STRING:
            # Conectar a master primero para crear la base de datos
            master_url = f"mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=no"
            master_engine = create_engine(
                master_url,
                connect_args={"autocommit": True}  # Autocommit SOLO para DDL
            )
            
            try:
                with master_engine.connect() as conn:
                    # Verificar si la base de datos existe
                    result = conn.execute(text(f"SELECT database_id FROM sys.databases WHERE name = '{DB_NAME}'"))
                    if not result.fetchone():
                        # CORREGIDO: Ejecutar CREATE DATABASE fuera de transacción
                        conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
                        print(f"Base de datos '{DB_NAME}' creada exitosamente")
                    else:
                        print(f"Base de datos '{DB_NAME}' ya existe")
            finally:
                master_engine.dispose()
        
        # Crear todas las tablas en la base de datos target
        print("🔧 Creando tablas...")
        Base.metadata.create_all(bind=engine)
        print("Tablas creadas exitosamente")
        
    except Exception as e:
        print(f"Error al crear la base de datos: {e}")
        # No lanzar excepción aquí - permitir que la app continue

def test_connection():
    """Probar la conexión a la base de datos"""
    try:
        # CORREGIDO: Usar connection pool correctamente
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as test"))
            row = result.fetchone()
            if row and row[0] == 1:
                print("Conexión a la base de datos exitosa")
                return True
            else:
                print("Error en consulta de prueba")
                return False
    except Exception as e:
        print(f"Error de conexión a la base de datos: {e}")
        
        # CORREGIDO: Intentar conectar a master si falla la conexión a la DB específica
        if "Cannot open database" in str(e) or "Login failed" in str(e):
            try:
                print("🔄 Intentando conexión a master...")
                master_url = f"mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=no"
                master_engine = create_engine(master_url)
                
                with master_engine.connect() as conn:
                    result = conn.execute(text("SELECT 1 as test"))
                    row = result.fetchone()
                    if row and row[0] == 1:
                        print("Conexión a master exitosa - problema con base de datos específica")
                        master_engine.dispose()
                        return False  # Conexión funciona pero DB no existe
                
                master_engine.dispose()
            except Exception as e2:
                print(f"Error conectando a master: {e2}")
                
        return False

def ensure_database_exists():
    """Asegurar que la base de datos existe antes de crear el engine principal"""
    if AZURE_SQL_CONNECTION_STRING:
        return True  # En Azure, la DB ya debe existir
    
    try:
        master_url = f"mssql+pyodbc://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=no"
        master_engine = create_engine(master_url, connect_args={"autocommit": True})
        
        with master_engine.connect() as conn:
            # Verificar si la base de datos existe
            result = conn.execute(text(f"SELECT database_id FROM sys.databases WHERE name = '{DB_NAME}'"))
            if not result.fetchone():
                print(f"Creando base de datos {DB_NAME}...")
                conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
                print(f"Base de datos '{DB_NAME}' creada")
        
        master_engine.dispose()
        return True
        
    except Exception as e:
        print(f"Error asegurando base de datos: {e}")
        return False