# ruff: noqa: B008
from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.rate_limit import login_rate_limiter
from app.admin.schemas import (
    AdminCreateRequest,
    AdminPageResponse,
    AdminProfileResponse,
    AdminUpdateRequest,
    DashboardResponse,
    LoginRequest,
    PaidUserPageResponse,
    ReferralCreateRequest,
    ReferralPayoutActionRequest,
    ReferralPayoutRequest,
    ReferralUpdateRequest,
    ReportDetailsResponse,
    ReportPageResponse,
    TransactionDetailsResponse,
    TransactionPageResponse,
)
from app.admin.security import (
    AdminPrincipal,
    AuthenticationError,
    PasswordPolicyError,
    SessionTokens,
    create_session,
    csrf_is_valid,
    hash_password,
    normalize_username,
    refresh_csrf_is_valid,
    resolve_principal,
    rotate_session,
    verify_password,
)
from app.admin.service import (
    admin_response,
    list_admins,
    list_paid_users,
    list_reports,
    list_transactions,
    paid_user_details,
    recent_buyers,
    report_details,
    revenue_dashboard,
    transaction_details,
)
from app.core.config import Settings, get_settings
from app.db.models import Admin, AdminAudit, AdminSession, ReferralPayout, ReferralProgram
from app.db.session import get_session
from app.referrals.service import (
    ReferralBalances,
    WithdrawalError,
    create_program,
    request_payout,
)
from app.referrals.service import (
    balances as referral_balances,
)

router = APIRouter(prefix="/admin", tags=["admin"])

ACCESS_COOKIE = "crous_admin_access"
REFRESH_COOKIE = "crous_admin_refresh"
CSRF_COOKIE = "crous_admin_csrf"


def _http_auth_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _cookie_secure(settings: Settings) -> bool:
    return urlsplit(str(settings.public_base_url)).scheme == "https"


def _set_session_cookies(response: Response, tokens: SessionTokens, settings: Settings) -> None:
    access = tokens.access_token
    refresh = tokens.refresh_token
    csrf = tokens.csrf_token
    access_expires_at = tokens.access_expires_at
    refresh_expires_at = tokens.refresh_expires_at
    secure = _cookie_secure(settings)
    common = {"secure": secure, "samesite": "strict", "path": "/"}
    response.set_cookie(ACCESS_COOKIE, access, httponly=True, expires=access_expires_at, **common)
    response.set_cookie(
        REFRESH_COOKIE, refresh, httponly=True, expires=refresh_expires_at, **common
    )
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, expires=refresh_expires_at, **common)


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    for cookie in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(cookie, path="/", secure=_cookie_secure(settings), samesite="strict")


async def current_principal(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminPrincipal:
    if not access_token:
        raise _http_auth_error()
    try:
        return await resolve_principal(session, access_token, settings)
    except AuthenticationError as error:
        raise _http_auth_error() from error


async def superadmin_principal(
    principal: AdminPrincipal = Depends(current_principal),
) -> AdminPrincipal:
    if principal.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin access is required"
        )
    return principal


async def csrf_protected(
    request: Request,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    principal: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AdminPrincipal:
    expected_origin = str(settings.public_base_url).rstrip("/")
    if request.headers.get("origin") != expected_origin or not await csrf_is_valid(
        session, principal, csrf_token
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return principal


async def _audit(
    session: AsyncSession,
    principal: AdminPrincipal,
    action: str,
    target_type: str,
    target_id: str | None,
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        AdminAudit(
            actor_admin_id=principal.admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata,
        )
    )


@router.post("/auth/login")
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    client_key = forwarded_for or (request.client.host if request.client else "unknown")
    if not login_rate_limiter.allow(client_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many sign-in attempts"
        )
    try:
        _, username_key = normalize_username(payload.username)
    except ValueError:
        username_key = "invalid"
    admin = await session.scalar(select(Admin).where(Admin.username_key == username_key))
    if (
        admin is None
        or not admin.is_active
        or not await verify_password(payload.password, admin.password_hash if admin else None)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        )
    try:
        tokens = await create_session(session, admin, settings)
    except AuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Admin sessions are unavailable"
        ) from error
    admin.last_login_at = datetime.now(UTC)
    await session.commit()
    _set_session_cookies(response, tokens, settings)
    return {"admin": admin_response(admin).model_dump(mode="json")}


@router.post("/auth/refresh")
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    if (
        request.headers.get("origin") != str(settings.public_base_url).rstrip("/")
        or not refresh_token
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    if not await refresh_csrf_is_valid(session, refresh_token, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    try:
        admin, tokens = await rotate_session(session, refresh_token, settings)
    except AuthenticationError as error:
        _clear_session_cookies(response, settings)
        raise _http_auth_error() from error
    await session.commit()
    _set_session_cookies(response, tokens, settings)
    return {"admin": admin_response(admin).model_dump(mode="json")}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    principal: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    admin_session = await session.get(AdminSession, principal.session_id)
    if admin_session is not None:
        admin_session.revoked_at = datetime.now(UTC)
        await _audit(session, principal, "logout", "admin_session", str(admin_session.id))
    await session.commit()
    _clear_session_cookies(response, settings)
    return response


@router.get("/me", response_model=AdminProfileResponse)
async def me(
    principal: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> AdminProfileResponse:
    admin = await session.get(Admin, principal.admin_id)
    if admin is None:
        raise _http_auth_error()
    return AdminProfileResponse(**admin_response(admin).model_dump())


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    period: str = Query(default="month", pattern="^(week|month|year)$"),
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> DashboardResponse:
    return await revenue_dashboard(session, period)


@router.get("/dashboard/recent-buyers")
async def dashboard_recent_buyers(
    limit: int = Query(default=10, ge=1, le=50),
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return {
        "items": [buyer.model_dump(mode="json") for buyer in await recent_buyers(session, limit)]
    }


@router.get("/admins", response_model=AdminPageResponse)
async def admins(
    q: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> AdminPageResponse:
    items, meta = await list_admins(session, q, page, page_size)
    return AdminPageResponse(items=items, meta=meta)


@router.post("/admins", response_model=AdminProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_admin(
    payload: AdminCreateRequest,
    principal: AdminPrincipal = Depends(superadmin_principal),
    _: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
) -> AdminProfileResponse:
    try:
        username, username_key = normalize_username(payload.username)
        password_hash = await hash_password(payload.password)
    except (ValueError, PasswordPolicyError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error
    existing = await session.scalar(select(Admin.id).where(Admin.username_key == username_key))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An administrator with this username already exists",
        )
    admin = Admin(
        name=payload.name.strip(),
        username=username,
        username_key=username_key,
        password_hash=password_hash,
        role=payload.role,
    )
    session.add(admin)
    await session.flush()
    await _audit(session, principal, "admin.created", "admin", str(admin.id), {"role": admin.role})
    await session.commit()
    return AdminProfileResponse(**admin_response(admin).model_dump())


@router.patch("/admins/{admin_id}", response_model=AdminProfileResponse)
async def update_admin(
    admin_id: int,
    payload: AdminUpdateRequest,
    principal: AdminPrincipal = Depends(superadmin_principal),
    _: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
) -> AdminProfileResponse:
    admin = await session.get(Admin, admin_id)
    if admin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Administrator not found")
    if admin.id == principal.admin_id and payload.role is not None and payload.role != admin.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrators cannot change their own role",
        )
    removing_superadmin = admin.role == "superadmin" and (
        payload.role == "admin" or payload.is_active is False
    )
    if removing_superadmin:
        active_superadmins = int(
            await session.scalar(
                select(func.count())
                .select_from(Admin)
                .where(Admin.role == "superadmin", Admin.is_active.is_(True))
            )
            or 0
        )
        if active_superadmins <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The last active superadmin cannot be changed or deactivated",
            )
    if payload.name is not None:
        admin.name = payload.name.strip()
    if payload.role is not None:
        admin.role = payload.role
    if payload.is_active is not None:
        admin.is_active = payload.is_active
    if payload.password is not None:
        try:
            admin.password_hash = await hash_password(payload.password)
        except PasswordPolicyError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
            ) from error
    await _audit(session, principal, "admin.updated", "admin", str(admin.id))
    await session.commit()
    return AdminProfileResponse(**admin_response(admin).model_dump())


@router.get("/paid-users", response_model=PaidUserPageResponse)
async def paid_users(
    q: str | None = Query(default=None, max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> PaidUserPageResponse:
    items, meta = await list_paid_users(session, q, page, page_size)
    return PaidUserPageResponse(items=items, meta=meta)


@router.get("/paid-users/{user_id}")
async def paid_user(
    user_id: int,
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    result = await paid_user_details(session, user_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    details, user, searches = result
    return {
        **details.model_dump(mode="json"),
        "language": user.language,
        "searches": [
            {
                "id": search.id,
                "location": search.location_display_name,
                "is_active": search.is_active,
                "last_checked_at": search.last_checked_at.isoformat()
                if search.last_checked_at
                else None,
            }
            for search in searches
        ],
    }


@router.get("/transactions", response_model=TransactionPageResponse)
async def transactions(
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> TransactionPageResponse:
    items, meta = await list_transactions(session, q, page, page_size)
    return TransactionPageResponse(items=items, meta=meta)


@router.get("/transactions/{transaction_id}", response_model=TransactionDetailsResponse)
async def transaction(
    transaction_id: int,
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> TransactionDetailsResponse:
    result = await transaction_details(session, transaction_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
    item, purchase = result
    return TransactionDetailsResponse(
        **item.model_dump(), processed_at=purchase.processed_at, user_id=purchase.user_id
    )


@router.get("/reports", response_model=ReportPageResponse)
async def reports(
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> ReportPageResponse:
    items, meta = await list_reports(session, q, page, page_size)
    return ReportPageResponse(items=items, meta=meta)


@router.get("/reports/{report_id}", response_model=ReportDetailsResponse)
async def report(
    report_id: int,
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> ReportDetailsResponse:
    item = await report_details(session, report_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return item


def _referral_payload(
    program: ReferralProgram, balance: ReferralBalances, settings: Settings
) -> dict[str, object]:
    return {
        "id": program.id,
        "referral_code": program.referral_code,
        "owner_telegram_username": program.owner_telegram_username,
        "owner_telegram_user_id": program.owner_telegram_user_id,
        "is_active": program.is_active,
        "commission_rate_basis_points": program.commission_rate_basis_points,
        "created_at": program.created_at,
        "deep_link": f"https://t.me/{settings.telegram_bot_username or ''}?start=ref_{program.referral_code}",
        "lifetime_earned_cents": balance.earned_cents,
        "available_cents": balance.available_cents,
        "reserved_cents": balance.reserved_cents,
        "paid_cents": balance.paid_cents,
        "reversed_cents": balance.reversed_cents,
    }


@router.get("/referrals")
async def referrals(
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    programs = list(
        await session.scalars(select(ReferralProgram).order_by(ReferralProgram.created_at.desc()))
    )
    return {
        "items": [
            _referral_payload(item, await referral_balances(session, item.id), settings)
            for item in programs
        ]
    }


@router.post("/referrals", status_code=status.HTTP_201_CREATED)
async def create_referral(
    payload: ReferralCreateRequest,
    principal: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    try:
        program = await create_program(
            session,
            owner_username=payload.owner_telegram_username,
            referral_code=payload.referral_code,
            created_by_admin_id=principal.admin_id,
        )
        await session.commit()
    except ValueError as error:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": str(error)}
        ) from error
    return _referral_payload(program, await referral_balances(session, program.id), settings)


@router.get("/referrals/{referral_id}")
async def referral_detail(
    referral_id: int,
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    program = await session.get(ReferralProgram, referral_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    return _referral_payload(program, await referral_balances(session, program.id), settings)


@router.patch("/referrals/{referral_id}")
async def update_referral(
    referral_id: int,
    payload: ReferralUpdateRequest,
    principal: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, object]:
    program = await session.get(ReferralProgram, referral_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    changed = program.is_active != payload.is_active
    program.is_active = payload.is_active
    if changed:
        await _audit(
            session,
            principal,
            "referral_reactivated" if payload.is_active else "referral_deactivated",
            "referral_program",
            str(program.id),
        )
    await session.commit()
    return _referral_payload(program, await referral_balances(session, program.id), settings)


@router.get("/referrals/{referral_id}/stats")
async def referral_stats(
    referral_id: int,
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    program = await session.get(ReferralProgram, referral_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    value = await referral_balances(session, program.id)
    return {
        "pending_cents": value.pending_cents,
        "earned_cents": value.earned_cents,
        "available_cents": value.available_cents,
        "reserved_cents": value.reserved_cents,
        "paid_cents": value.paid_cents,
        "reversed_cents": value.reversed_cents,
        "currency": "EUR",
    }


@router.get("/referrals/{referral_id}/payouts")
async def referral_payouts(
    referral_id: int,
    _: AdminPrincipal = Depends(current_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    values = list(
        await session.scalars(
            select(ReferralPayout)
            .where(ReferralPayout.referral_program_id == referral_id)
            .order_by(ReferralPayout.requested_at.desc())
        )
    )
    return {
        "items": [
            {
                "id": item.id,
                "amount_cents": item.amount_cents,
                "currency": item.currency,
                "status": item.status,
                "requested_at": item.requested_at,
                "provider_transfer_id": item.provider_transfer_id,
                "failure_code": item.failure_code,
            }
            for item in values
        ]
    }


@router.post("/referrals/{referral_id}/payouts", status_code=status.HTTP_201_CREATED)
async def admin_request_payout(
    referral_id: int,
    payload: ReferralPayoutRequest,
    principal: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    program = await session.get(ReferralProgram, referral_id)
    if program is None:
        raise HTTPException(status_code=404, detail="Referral not found")
    try:
        payout = await request_payout(
            session,
            program=program,
            amount_cents=payload.amount_cents,
            idempotency_key=payload.idempotency_key,
        )
        payout.created_by_admin_id = principal.admin_id
        await session.commit()
    except WithdrawalError as error:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": error.code,
                "available_balance": f"{error.available_cents / 100:.2f}",
                "currency": "EUR",
            },
        ) from error
    return {"id": payout.id, "status": payout.status, "amount_cents": payout.amount_cents}


@router.post("/referral-payouts/{payout_id}/approve")
async def approve_referral_payout(
    payout_id: int,
    _: ReferralPayoutActionRequest,
    principal: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    payout = await session.get(ReferralPayout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.status != "requested":
        raise HTTPException(status_code=409, detail={"code": "payout_not_requestable"})
    payout.status, payout.approved_at = "approved", datetime.now(UTC)
    await _audit(session, principal, "payout_approved", "referral_payout", str(payout.id))
    await session.commit()
    return {"id": payout.id, "status": payout.status}


@router.post("/referral-payouts/{payout_id}/paid")
async def pay_referral_payout(
    payout_id: int,
    payload: ReferralPayoutActionRequest,
    principal: AdminPrincipal = Depends(csrf_protected),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    payout = await session.get(ReferralPayout, payout_id)
    if payout is None:
        raise HTTPException(status_code=404, detail="Payout not found")
    if payout.status != "approved" or not payload.external_reference:
        raise HTTPException(
            status_code=409, detail={"code": "payout_not_approved_or_reference_missing"}
        )
    payout.status, payout.paid_at, payout.provider_transfer_id = (
        "paid",
        datetime.now(UTC),
        payload.external_reference,
    )
    await _audit(
        session,
        principal,
        "payout_paid",
        "referral_payout",
        str(payout.id),
        {"external_reference": payload.external_reference},
    )
    await session.commit()
    return {"id": payout.id, "status": payout.status}
