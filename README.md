# Sistema IoT Control de Acceso

Backend minimo con FastAPI para desplegar en Render.

## Render

- Language: Python 3
- Branch: main
- Root Directory: dejar vacio
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

## Prueba local

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Luego abre `http://127.0.0.1:8000/`.

## Endpoints

### Salud

```http
GET /health
```

Respuesta:

```json
{"status": "ok"}
```

### Subir imagen desde ESP32-CAM

```http
POST /upload
```

Enviar una imagen JPEG como `multipart/form-data` usando el campo `file`.

Ejemplo:

```bash
curl -X POST \
  -F "file=@foto.jpg;type=image/jpeg" \
  https://web-service-en-render.onrender.com/upload
```

Respuesta:

```json
{
  "status": "ok",
  "filename": "20260607T170000Z-abc123.jpg",
  "size": 12345,
  "content_type": "image/jpeg",
  "qr_detectado": true,
  "qr_data": "AULA-101",
  "qr_metodo": "pyzbar",
  "qr_error": null
}
```

Si la imagen no contiene QR, `qr_detectado` sera `false` y `qr_data` sera `null`.

# Web-Service-en-Render.
EL SISTEMA IOT INTELIGENTE DE CONTROL DE ACCESO Y TRAZABILIDAD DE INGRESO A AULAS
