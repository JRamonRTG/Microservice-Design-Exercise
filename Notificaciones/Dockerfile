# Usar Python 3.11
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Exponer puerto 80 para Azure Container Apps
EXPOSE 80

# Ejecutar uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
