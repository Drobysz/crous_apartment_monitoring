from fastapi import FastAPI

from app.admin.router import router as admin_router
from app.referrals.router import router as referral_owner_router

app = FastAPI(title="CROUS Bot internal API")
app.include_router(admin_router)
app.include_router(referral_owner_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
