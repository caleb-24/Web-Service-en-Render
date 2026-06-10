import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="Web Service en Render")

UPLOAD_DIR = Path("uploads")
MAX_IMAGE_SIZE = 5 * 1024 * 1024
BUCKET_FOTOS = "fotos"
TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Supabase client (lazy — app runs without DB if env vars absent)
# ---------------------------------------------------------------------------
_supabase = None


def get_supabase():
    global _supabase
    if _supabase is not None:
        return _supabase
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if url and key:
        from supabase import create_client
        _supabase = create_client(url, key)
    return _supabase


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/")
def home():
    return {"status": "Servidor funcionando"}


@app.get("/health")
def health():
    db_ok = get_supabase() is not None
    return {"status": "ok", "supabase": db_ok}


# ---------------------------------------------------------------------------
# QR detection
# ---------------------------------------------------------------------------

def detect_qr(image_path: Path):
    try:
        import cv2

        image = cv2.imread(str(image_path))
        if image is None:
            return {"detected": False, "data": None, "method": None,
                    "error": "No se pudo leer la imagen"}

        detector = cv2.QRCodeDetector()
        qr_data, points, _ = detector.detectAndDecode(image)
        if points is not None and qr_data:
            return {"detected": True, "data": qr_data, "method": "opencv", "error": None}
    except Exception as exc:
        opencv_error = str(exc)
    else:
        opencv_error = None

    try:
        from pyzbar.pyzbar import decode
        import cv2

        image = cv2.imread(str(image_path))
        if image is None:
            return {"detected": False, "data": None, "method": None,
                    "error": "No se pudo leer la imagen"}

        decoded_codes = decode(image)
        if decoded_codes:
            qr_data = decoded_codes[0].data.decode("utf-8", errors="replace")
            return {"detected": True, "data": qr_data, "method": "pyzbar", "error": None}
    except Exception as exc:
        if opencv_error is None and "zbar" in str(exc).lower():
            return {"detected": False, "data": None, "method": None, "error": None}
        return {"detected": False, "data": None, "method": None,
                "error": f"opencv: {opencv_error}; pyzbar: {exc}"}

    return {"detected": False, "data": None, "method": None, "error": opencv_error}


# ---------------------------------------------------------------------------
# Face detection
# ---------------------------------------------------------------------------

def detect_faces(image_path: Path):
    try:
        import cv2

        image = cv2.imread(str(image_path))
        if image is None:
            return {"detected": False, "count": 0, "faces": [], "method": None,
                    "recognized": False, "user_id": None,
                    "error": "No se pudo leer la imagen"}

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        detector = cv2.CascadeClassifier(cascade_path)

        if detector.empty():
            return {"detected": False, "count": 0, "faces": [], "method": None,
                    "recognized": False, "user_id": None,
                    "error": "No se pudo cargar el detector facial"}

        faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        face_boxes = [
            {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}
            for (x, y, w, h) in faces
        ]

        return {"detected": len(face_boxes) > 0, "count": len(face_boxes),
                "faces": face_boxes, "method": "opencv-haarcascade",
                "recognized": False, "user_id": None, "error": None}
    except Exception as exc:
        return {"detected": False, "count": 0, "faces": [], "method": None,
                "recognized": False, "user_id": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

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
    face_result = detect_faces(image_path)

    # Persist access record to Supabase
    acceso_id = None
    db_error = None
    usuario = None
    imagen_url = None
    db = get_supabase()
    if db:
        try:
            # Si se detecto QR, buscar usuario con ese codigo
            if qr_result["detected"] and qr_result["data"]:
                match = (
                    db.table("usuarios")
                    .select("id, nombre, rol")
                    .eq("qr_code", qr_result["data"])
                    .limit(1)
                    .execute()
                )
                if match.data:
                    usuario = match.data[0]

            # Subir imagen al bucket publico para verla desde el dashboard
            try:
                db.storage.from_(BUCKET_FOTOS).upload(
                    path=f"accesos/{filename}",
                    file=image_bytes,
                    file_options={"content-type": "image/jpeg"},
                )
                imagen_url = db.storage.from_(BUCKET_FOTOS).get_public_url(f"accesos/{filename}")
            except Exception:
                imagen_url = None

            record = {
                "filename": filename,
                "imagen_url": imagen_url,
                "qr_detectado": qr_result["detected"],
                "qr_data": qr_result["data"],
                "rostro_detectado": face_result["detected"],
                "rostro_cantidad": face_result["count"],
                "acceso_concedido": usuario is not None,
                "usuario_id": usuario["id"] if usuario else None,
            }
            resp = db.table("accesos").insert(record).execute()
            if resp.data:
                acceso_id = resp.data[0]["id"]
        except Exception as exc:
            db_error = str(exc)

    return {
        "status": "ok",
        "filename": filename,
        "size": len(image_bytes),
        "content_type": file.content_type,
        "acceso_id": acceso_id,
        "imagen_url": imagen_url,
        "db_error": db_error,
        "qr_detectado": qr_result["detected"],
        "qr_data": qr_result["data"],
        "qr_metodo": qr_result["method"],
        "qr_error": qr_result["error"],
        "rostro_detectado": face_result["detected"],
        "rostro_cantidad": face_result["count"],
        "rostros": face_result["faces"],
        "rostro_metodo": face_result["method"],
        "rostro_reconocido": face_result["recognized"],
        "rostro_usuario_id": face_result["user_id"],
        "rostro_error": face_result["error"],
        "acceso_concedido": usuario is not None,
        "usuario": usuario,
    }


# ---------------------------------------------------------------------------
# Accesos
# ---------------------------------------------------------------------------

@app.get("/accesos")
def listar_accesos(limit: int = 50):
    db = get_supabase()
    if not db:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    resp = db.table("accesos").select("*").order("created_at", desc=True).limit(limit).execute()
    return {"total": len(resp.data), "accesos": resp.data}


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

ROL_VALORES = {"estudiante", "docente", "administrativo"}


class UsuarioCreate(BaseModel):
    nombre: str
    email: str | None = None
    aula_id: str | None = None
    rol: str = "estudiante"
    qr_code: str | None = None


@app.get("/usuarios")
def listar_usuarios():
    db = get_supabase()
    if not db:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    resp = db.table("usuarios").select("*").order("created_at", desc=True).execute()
    return {"total": len(resp.data), "usuarios": resp.data}


@app.post("/usuarios")
def crear_usuario(body: UsuarioCreate):
    db = get_supabase()
    if not db:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    if body.rol not in ROL_VALORES:
        raise HTTPException(status_code=400, detail=f"Rol invalido. Valores: {sorted(ROL_VALORES)}")
    record = {"nombre": body.nombre, "rol": body.rol}
    if body.email:
        record["email"] = body.email
    if body.aula_id:
        record["aula_id"] = body.aula_id
    if body.qr_code:
        record["qr_code"] = body.qr_code
    try:
        resp = db.table("usuarios").insert(record).execute()
    except Exception as exc:
        if "qr_code" in str(exc) and "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Ese codigo QR ya esta asignado a otro usuario")
        raise HTTPException(status_code=500, detail=str(exc))
    if not resp.data:
        raise HTTPException(status_code=500, detail="No se pudo crear el usuario")
    return {"status": "ok", "usuario": resp.data[0]}


# ---------------------------------------------------------------------------
# Aulas
# ---------------------------------------------------------------------------

class AulaCreate(BaseModel):
    nombre: str
    descripcion: str | None = None


@app.get("/aulas")
def listar_aulas():
    db = get_supabase()
    if not db:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    resp = db.table("aulas").select("*").order("nombre").execute()
    return {"total": len(resp.data), "aulas": resp.data}


@app.post("/aulas")
def crear_aula(body: AulaCreate):
    db = get_supabase()
    if not db:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    record = {"nombre": body.nombre}
    if body.descripcion:
        record["descripcion"] = body.descripcion
    resp = db.table("aulas").insert(record).execute()
    if not resp.data:
        raise HTTPException(status_code=500, detail="No se pudo crear el aula")
    return {"status": "ok", "aula": resp.data[0]}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    db = get_supabase()
    accesos, total_usuarios, total_aulas, accesos_rechazados = [], 0, 0, 0
    if db:
        try:
            accesos = db.table("accesos").select("*, usuarios(nombre, rol)").order("created_at", desc=True).limit(100).execute().data or []
        except Exception:
            accesos = []
        try:
            total_usuarios = len(db.table("usuarios").select("id").execute().data or [])
        except Exception:
            total_usuarios = 0
        try:
            total_aulas = len(db.table("aulas").select("id").execute().data or [])
        except Exception:
            total_aulas = 0
        accesos_rechazados = sum(1 for a in accesos if not a.get("acceso_concedido"))
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "active": "dashboard",
            "accesos": accesos,
            "total_accesos": len(accesos),
            "total_usuarios": total_usuarios,
            "total_aulas": total_aulas,
            "accesos_rechazados": accesos_rechazados,
        },
    )


@app.get("/dashboard/usuarios", response_class=HTMLResponse)
def dashboard_usuarios(request: Request):
    db = get_supabase()
    usuarios = []
    if db:
        resp = db.table("usuarios").select("*").order("created_at", desc=True).execute()
        usuarios = resp.data or []
    return templates.TemplateResponse(
        request=request,
        name="usuarios.html",
        context={"active": "usuarios", "usuarios": usuarios},
    )


@app.get("/dashboard/aulas", response_class=HTMLResponse)
def dashboard_aulas(request: Request):
    db = get_supabase()
    aulas = []
    if db:
        resp = db.table("aulas").select("*").order("nombre").execute()
        aulas = resp.data or []
    return templates.TemplateResponse(
        request=request,
        name="aulas.html",
        context={"active": "aulas", "aulas": aulas},
    )


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------

def _calcular_reportes(accesos: list) -> dict:
    from collections import defaultdict

    por_dia: dict = defaultdict(lambda: {"total": 0, "concedidos": 0, "rechazados": 0, "qr": 0, "rostro": 0})
    for a in accesos:
        fecha = (a.get("created_at") or "")[:10] or "sin-fecha"
        por_dia[fecha]["total"] += 1
        if a.get("acceso_concedido"):
            por_dia[fecha]["concedidos"] += 1
        else:
            por_dia[fecha]["rechazados"] += 1
        if a.get("qr_detectado"):
            por_dia[fecha]["qr"] += 1
        if a.get("rostro_detectado"):
            por_dia[fecha]["rostro"] += 1

    dias = [{"fecha": k, **v} for k, v in sorted(por_dia.items(), reverse=True)]
    total = len(accesos)
    concedidos = sum(1 for a in accesos if a.get("acceso_concedido"))
    rechazados = total - concedidos

    return {
        "total": total,
        "concedidos": concedidos,
        "rechazados": rechazados,
        "porcentaje_aprobacion": round(concedidos / total * 100, 1) if total else 0,
        "qr_detectados": sum(1 for a in accesos if a.get("qr_detectado")),
        "rostros_detectados": sum(1 for a in accesos if a.get("rostro_detectado")),
        "por_dia": dias,
    }


@app.get("/reportes")
def reportes_json():
    db = get_supabase()
    if not db:
        raise HTTPException(status_code=503, detail="Base de datos no configurada")
    accesos = db.table("accesos").select("*").order("created_at", desc=True).limit(500).execute().data or []
    return _calcular_reportes(accesos)


@app.get("/dashboard/reportes", response_class=HTMLResponse)
def dashboard_reportes(request: Request):
    db = get_supabase()
    reporte = {"total": 0, "concedidos": 0, "rechazados": 0,
               "porcentaje_aprobacion": 0, "qr_detectados": 0,
               "rostros_detectados": 0, "por_dia": []}
    if db:
        try:
            accesos = db.table("accesos").select("*").order("created_at", desc=True).limit(500).execute().data or []
            reporte = _calcular_reportes(accesos)
        except Exception:
            pass
    return templates.TemplateResponse(
        request=request,
        name="reportes.html",
        context={"active": "reportes", "r": reporte},
    )
