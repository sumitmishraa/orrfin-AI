from fastapi import FastAPI

app = FastAPI(title="Orrfin.ai mock ERP")


@app.get("/health")
def health():
    return {"status": "ok"}
