import pyodbc
import time

print("🔌 Probando conexión a SQL Server...")

# Diferentes cadenas de conexión para probar
connection_strings = [
    # Opción 1: Con puerto específico
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost,1433;DATABASE=master;UID=sa;PWD=FitFlow123!;TrustServerCertificate=yes;Encrypt=no",
    
    # Opción 2: Sin puerto específico
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=master;UID=sa;PWD=FitFlow123!;TrustServerCertificate=yes;Encrypt=no",
    
    # Opción 3: Con timeout más alto
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost,1433;DATABASE=master;UID=sa;PWD=FitFlow123!;TrustServerCertificate=yes;Encrypt=no;Connection Timeout=30",
]

for i, conn_str in enumerate(connection_strings, 1):
    print(f"\nProbando opción {i}...")
    try:
        print("   Conectando...")
        conn = pyodbc.connect(conn_str, timeout=10)
        cursor = conn.cursor()
        
        print("   Ejecutando consulta...")
        cursor.execute("SELECT 1 as test")
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            print("   ¡CONEXIÓN EXITOSA!")
            
            # Probar crear base de datos
            try:
                cursor.execute("SELECT name FROM sys.databases WHERE name = 'fitflow_payments'")
                if cursor.fetchone():
                    print("   Base de datos fitflow_payments ya existe")
                else:
                    print("   Creando base de datos fitflow_payments...")
                    cursor.execute("CREATE DATABASE fitflow_payments")
                    conn.commit()
                    print("   Base de datos creada exitosamente")
            except Exception as db_error:
                print(f"   ⚠️  Error creando DB: {db_error}")
            
            cursor.close()
            conn.close()
            print(f"   CADENA DE CONEXIÓN FUNCIONAL:")
            print(f"   {conn_str}")
            break
            
    except Exception as e:
        print(f"   Error: {e}")

print("\n" + "="*60)
print("🧪 Probando drivers disponibles...")
try:
    drivers = pyodbc.drivers()
    print("Drivers ODBC disponibles:")
    for driver in drivers:
        print(f"   - {driver}")
        
    if not any("SQL Server" in driver for driver in drivers):
        print("No se encontró driver para SQL Server")
        print("Puede que necesites instalar el driver ODBC")
        
except Exception as e:
    print(f"Error obteniendo drivers: {e}")