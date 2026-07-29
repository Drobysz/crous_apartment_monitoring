from fastapi import FastAPI

app = FastAPI(title="CROUS Bot internal API")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
