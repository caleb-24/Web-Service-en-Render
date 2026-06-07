from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile

app = FastAPI(title="Web Service en Render")

UPLOAD_DIR = Path("uploads")
MAX_IMAGE_SIZE = 5 * 1024 * 1024


@app.get("/")
def home():
    return {"status": "Servidor funcionando"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    if file.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status_code=400, detail="Solo se aceptan imagenes JPEG")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="La imagen esta vacia")

    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="La imagen supera el limite de 5 MB")

    if not image_bytes.startswith(b"\xff\xd8"):
        raise HTTPException(status_code=400, detail="El archivo no parece ser un JPEG valido")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{created_at}-{uuid4().hex}.jpg"
    image_path = UPLOAD_DIR / filename
    image_path.write_bytes(image_bytes)

    return {
        "status": "ok",
        "filename": filename,
        "size": len(image_bytes),
        "content_type": file.content_type,
    }
