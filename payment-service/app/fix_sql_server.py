"""
Script para diagnosticar y solucionar problemas con SQL Server
Ejecutar: python fix_sql_server.py
"""

import subprocess
import time
import sys
import os

def run_command(command, shell=True):
    """Ejecutar comando y retornar resultado"""
    try:
        result = subprocess.run(command, shell=shell, capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_docker_containers():
    """Verificar estado de contenedores Docker"""
    print("VERIFICANDO CONTENEDORES DOCKER")
    print("="*50)
    
    success, stdout, stderr = run_command("docker ps")
    if success:
        print("Docker está ejecutándose")
        if "fitflow-sqlserver" in stdout:
            print("Contenedor SQL Server está ejecutándose")
            
            # Verificar logs
            print("\nÚltimos logs de SQL Server:")
            success, stdout, stderr = run_command("docker logs fitflow-sqlserver --tail 10")
            if success:
                print(stdout)
            
            return True
        else:
            print("Contenedor SQL Server no está ejecutándose")
            return False
    else:
        print(f"Error con Docker: {stderr}")
        return False

def restart_sql_server():
    """Reiniciar contenedor de SQL Server"""
    print("\nREINICIANDO SQL SERVER")
    print("="*50)
    
    # Detener contenedor
    print("Deteniendo contenedor...")
    run_command("docker stop fitflow-sqlserver")
    
    # Esperar un momento
    time.sleep(2)
    
    # Iniciar contenedor
    print("Iniciando contenedor...")
    success, stdout, stderr = run_command("docker start fitflow-sqlserver")
    
    if success:
        print("Contenedor iniciado")
        
        # Esperar a que SQL Server esté listo
        print("Esperando a que SQL Server esté listo...")
        for i in range(30):
            time.sleep(2)
            success, stdout, stderr = run_command("docker exec fitflow-sqlserver /opt/mssql-tools/bin/sqlcmd -S localhost -U sa -P 'FitFlow123!' -Q 'SELECT 1' -b")
            if success:
                print("SQL Server está listo")
                return True
            print(f"   Intento {i+1}/30...")
        
        print("SQL Server no responde después de 60 segundos")
        return False
    else:
        print(f"Error iniciando contenedor: {stderr}")
        return False

def test_sql_connection():
    """Probar conexión directa a SQL Server"""
    print("\nPROBANDO CONEXIÓN SQL")
    print("="*50)
    
    try:
        import pyodbc
        print("pyodbc disponible")
        
        connection_strings = [
            "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost,1433;DATABASE=master;UID=sa;PWD=FitFlow123!;TrustServerCertificate=yes;Encrypt=no",
            "DRIVER={SQL Server};SERVER=localhost,1433;DATABASE=master;UID=sa;PWD=FitFlow123!;TrustServerCertificate=yes;Encrypt=no",
        ]
        
        for i, conn_str in enumerate(connection_strings, 1):
            try:
                print(f"Probando conexión {i}...")
                conn = pyodbc.connect(conn_str, timeout=10)
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                
                if result and result[0] == 1:
                    print("¡CONEXIÓN EXITOSA!")
                    
                    # Crear base de datos si no existe
                    try:
                        cursor.execute("SELECT name FROM sys.databases WHERE name = 'fitflow_payments'")
                        if cursor.fetchone():
                            print("Base de datos fitflow_payments ya existe")
                        else:
                            print("Creando base de datos fitflow_payments...")
                            cursor.execute("CREATE DATABASE fitflow_payments")
                            conn.commit()
                            print("Base de datos creada")
                    except Exception as e:
                        print(f"Error con base de datos: {e}")
                    
                    cursor.close()
                    conn.close()
                    return True
                    
            except Exception as e:
                print(f"Error conexión {i}: {e}")
        
        return False
        
    except ImportError:
        print("pyodbc no está instalado")
        print("Instalar con: pip install pyodbc")
        return False

def fix_docker_compose():
    """Corregir docker-compose si es necesario"""
    print("\nVERIFICANDO DOCKER-COMPOSE")
    print("="*50)
    
    # Verificar si docker-compose.yml existe
    if os.path.exists("../docker-compose.yml"):
        print("docker-compose.yml encontrado")
    else:
        print("docker-compose.yml no encontrado")
        return False
    
    # Reiniciar servicios con docker-compose
    print("Reiniciando servicios con docker-compose...")
    os.chdir("..")  # Ir al directorio padre donde está docker-compose.yml
    
    success, stdout, stderr = run_command("docker-compose down")
    if success:
        print("Servicios detenidos")
    else:
        print(f"Error deteniendo servicios: {stderr}")
    
    time.sleep(2)
    
    success, stdout, stderr = run_command("docker-compose up -d")
    if success:
        print("Servicios iniciados")
        
        # Esperar a que SQL Server esté listo
        print("Esperando a que los servicios estén listos...")
        time.sleep(10)
        
        return True
    else:
        print(f"❌ Error iniciando servicios: {stderr}")
        return False

def main():
    """Función principal"""
    print("SCRIPT DE DIAGNÓSTICO Y REPARACIÓN SQL SERVER")
    print("="*60)
    
    # Paso 1: Verificar Docker
    if not check_docker_containers():
        print("\nIntentando arreglar con docker-compose...")
        if fix_docker_compose():
            time.sleep(5)
            if not check_docker_containers():
                print("No se pudo arreglar Docker - verificar manualmente")
                return
        else:
            print("No se pudo arreglar con docker-compose")
            return
    
    # Paso 2: Probar conexión SQL
    if not test_sql_connection():
        print("\n🔄 Intentando reiniciar SQL Server...")
        if restart_sql_server():
            time.sleep(5)
            if not test_sql_connection():
                print("Conexión SQL sigue fallando")
                
                print("\nSOLUCIONES MANUALES:")
                print("1. Verificar contraseña: FitFlow123!")
                print("2. Verificar puerto: 1433")
                print("3. Reinstalar ODBC Driver 18")
                print("4. Verificar firewall de Windows")
                return
        else:
            print("No se pudo reiniciar SQL Server")
            return
    
    # Paso 3: Resumen final
    print("\nDIAGNÓSTICO COMPLETADO")
    print("="*60)
    print("Docker: Funcionando")
    print("SQL Server: Funcionando") 
    print("Base de datos: Lista")
    print("\nAhora puedes ejecutar:")
    print("   cd app")
    print("   python main.py")

if __name__ == "__main__":
    main()