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


def detect_qr(image_path: Path):
    try:
        import cv2

        image = cv2.imread(str(image_path))
        if image is None:
            return {
                "detected": False,
                "data": None,
                "method": None,
                "error": "No se pudo leer la imagen",
            }

        detector = cv2.QRCodeDetector()
        qr_data, points, _ = detector.detectAndDecode(image)
        if points is not None and qr_data:
            return {
                "detected": True,
                "data": qr_data,
                "method": "opencv",
                "error": None,
            }
    except Exception as exc:
        opencv_error = str(exc)
    else:
        opencv_error = None

    try:
        from pyzbar.pyzbar import decode
        import cv2

        image = cv2.imread(str(image_path))
        if image is None:
            return {
                "detected": False,
                "data": None,
                "method": None,
                "error": "No se pudo leer la imagen",
            }

        decoded_codes = decode(image)
        if decoded_codes:
            qr_data = decoded_codes[0].data.decode("utf-8", errors="replace")
            return {
                "detected": True,
                "data": qr_data,
                "method": "pyzbar",
                "error": None,
            }
    except Exception as exc:
        if opencv_error is None and "zbar" in str(exc).lower():
            return {
                "detected": False,
                "data": None,
                "method": None,
                "error": None,
            }

        return {
            "detected": False,
            "data": None,
            "method": None,
            "error": f"opencv: {opencv_error}; pyzbar: {exc}",
        }

    return {
        "detected": False,
        "data": None,
        "method": None,
        "error": opencv_error,
    }


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
    qr_result = detect_qr(image_path)

    return {
        "status": "ok",
        "filename": filename,
        "size": len(image_bytes),
        "content_type": file.content_type,
        "qr_detectado": qr_result["detected"],
        "qr_data": qr_result["data"],
        "qr_metodo": qr_result["method"],
        "qr_error": qr_result["error"],
    }
