# Mu.Orbita API

Backend FastAPI para la plataforma de agricultura de precisión Mu.Orbita.

## Características

- 🔐 **Autenticación**: Email/password + Google OAuth 2.0
- 📊 **Dashboard API**: Endpoints para dashboard de cliente
- 🔗 **Webhooks**: Integración con n8n para procesar jobs
- 🗄️ **PostgreSQL**: Base de datos en Neon (serverless)
- 🐳 **Docker**: Ready para deploy

## Estructura del Proyecto

```
muorbita-api/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings
│   ├── database.py          # Conexión PostgreSQL
│   ├── dependencies.py      # Auth middleware
│   ├── models/              # SQLAlchemy models
│   │   ├── client.py
│   │   ├── parcel.py
│   │   ├── job.py
│   │   ├── kpi.py
│   │   └── report.py
│   ├── routers/             # API endpoints
│   │   ├── auth.py          # Login, register, OAuth
│   │   ├── dashboard.py     # Dashboard del cliente
│   │   └── webhooks.py      # Webhooks de n8n
│   ├── schemas/             # Pydantic schemas
│   └── services/            # Lógica de negocio
│       └── auth.py          # JWT, OAuth helpers
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Instalación Local

### 1. Clonar y crear entorno virtual

```bash
cd muorbita-api
python -m venv venv
source venv/bin/activate  # Linux/Mac
# o: venv\Scripts\activate  # Windows
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con tus valores reales
```

Variables requeridas:
- `DATABASE_URL`: Connection string de Neon PostgreSQL
- `JWT_SECRET_KEY`: Secreto para firmar JWT tokens
- `GOOGLE_CLIENT_ID`: Client ID de Google OAuth (si usas Google login)
- `GOOGLE_CLIENT_SECRET`: Client Secret de Google OAuth

### 4. Ejecutar

```bash
# Desarrollo (con hot reload)
uvicorn app.main:app --reload --port 8000

# O con Python directamente
python -m app.main
```

### 5. Verificar

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## Docker

### Desarrollo

```bash
docker-compose up --build
```

### Producción

```bash
docker build -t muorbita-api .
docker run -p 8000:8000 --env-file .env muorbita-api
```

## API Endpoints

### Auth (`/api/v1/auth`)

| Method | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/register` | Registro con email/password |
| POST | `/login` | Login con email/password |
| GET | `/google` | Iniciar OAuth con Google |
| GET | `/google/callback` | Callback de Google |
| POST | `/google/token` | Login con code de Google |
| POST | `/refresh` | Renovar tokens |
| GET | `/me` | Datos del usuario actual |
| POST | `/change-password` | Cambiar contraseña |
| POST | `/logout` | Cerrar sesión |

### Dashboard (`/api/v1/dashboard`)

| Method | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/summary` | Resumen del dashboard |
| GET | `/parcels` | Lista de parcelas |
| POST | `/parcels` | Crear parcela |
| GET | `/parcels/{id}` | Detalle de parcela |
| PATCH | `/parcels/{id}` | Actualizar parcela |
| DELETE | `/parcels/{id}` | Desactivar parcela |
| GET | `/parcels/{id}/kpis` | KPIs de una parcela |
| GET | `/jobs` | Historial de jobs |
| GET | `/jobs/{id}` | Detalle de job |
| GET | `/reports` | Historial de reportes |
| GET | `/reports/{id}/download` | Descargar PDF |
| GET | `/alerts` | Alertas activas |

### Webhooks (`/api/v1/webhooks`)

| Method | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/job-started` | n8n notifica job iniciado |
| POST | `/job-completed` | n8n notifica job completado |
| POST | `/kpis` | n8n envía batch de KPIs |
| POST | `/report-sent` | n8n notifica reporte enviado |
| POST | `/client-created` | n8n notifica nuevo cliente |
| GET | `/health` | Health check |

## Configurar Google OAuth

1. Ir a [Google Cloud Console](https://console.cloud.google.com)
2. Crear proyecto o seleccionar existente
3. Ir a "APIs & Services" > "Credentials"
4. Crear "OAuth 2.0 Client ID" (tipo Web Application)
5. Añadir URIs autorizados:
   - Desarrollo: `http://localhost:8000/api/v1/auth/google/callback`
   - Producción: `https://api.muorbita.com/api/v1/auth/google/callback`
6. Copiar Client ID y Client Secret a `.env`

## Integración con n8n

### Header de autenticación

n8n debe enviar el header `X-Webhook-Secret` con el valor de `N8N_WEBHOOK_SECRET`:

```
X-Webhook-Secret: tu-secreto-n8n
```

### Payload job-completed

```json
{
  "job_id": "JOB_1699999999999",
  "status": "completed",
  "pdf_url": "https://drive.google.com/...",
  "ndvi_mean": 0.58,
  "ndvi_p10": 0.42,
  "ndvi_p90": 0.71,
  "ndwi_mean": 0.15,
  "stress_area_ha": 12.5,
  "stress_area_pct": 8.2
}
```

### Payload KPIs

```json
{
  "parcel_id": "uuid-de-parcela",
  "job_id": "uuid-de-job",
  "kpis": [
    {
      "observation_date": "2025-12-01",
      "ndvi_mean": 0.58,
      "ndwi_mean": 0.15,
      "satellite_source": "sentinel2"
    }
  ]
}
```

## Deploy en VPS

### Con Docker

```bash
# 1. Copiar archivos al servidor
scp -r muorbita-api user@server:/home/user/

# 2. En el servidor
cd /home/user/muorbita-api
cp .env.example .env
nano .env  # Configurar variables

# 3. Build y ejecutar
docker-compose up -d

# 4. Verificar
curl http://localhost:8000/health
```

### Con Systemd (sin Docker)

```bash
# /etc/systemd/system/muorbita-api.service
[Unit]
Description=Mu.Orbita API
After=network.target

[Service]
User=www-data
WorkingDirectory=/home/user/muorbita-api
ExecStart=/home/user/muorbita-api/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable muorbita-api
sudo systemctl start muorbita-api
```

## Licencia

Propietario - Mu.Orbita © 2025
