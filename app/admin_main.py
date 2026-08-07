from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="CROUS Bot administration")


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        "<title>CROUS administration</title><body><main>"
        "<h1>CROUS administration</h1><p>Administrative tools are not enabled yet.</p>"
        "</main></body></html>"
    )
