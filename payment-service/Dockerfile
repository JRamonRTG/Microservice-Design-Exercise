# Usar Python 3.11 slim como base
FROM python:3.11-slim

# Establecer directorio de trabajo
WORKDIR /app

# Instalar dependencias del sistema para SQL Server
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        gnupg \
        unixodbc-dev \
        g++ \
    && curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql18 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copiar archivos de dependencias
COPY requirements.txt .

# Instalar dependencias Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY app/ ./app/

# Crear usuario no-root para seguridad
RUN useradd --create-home --shell /bin/bash fitflow
RUN chown -R fitflow:fitflow /app
USER fitflow

# Exponer puerto
EXPOSE 8002

# Variables de entorno
ENV PYTHONPATH=/app
ENV SERVICE_PORT=8002
ENV SERVICE_HOST=0.0.0.0

# Comando para ejecutar la aplicación
CMD ["python", "app/main.py"]