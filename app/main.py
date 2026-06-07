from fastapi import FastAPI

app = FastAPI(title="Web Service en Render")


@app.get("/")
def home():
    return {"status": "Servidor funcionando"}


@app.get("/health")
def health():
    return {"status": "ok"}
