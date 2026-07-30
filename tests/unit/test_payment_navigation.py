from types import SimpleNamespace

import pytest

import app.main as application
from app.db.models import SubscriptionPlan, User
from app.payments.stripe import ProcessedPayment


@pytest.mark.asyncio
async def test_payment_confirmation_refreshes_the_visible_main_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(id=17, telegram_user_id=700, telegram_chat_id=701, language="ru", active_navigation_screen="main")
    plan = SubscriptionPlan(id=4, code="season", name="Season", price_cents=1000)
    payment = ProcessedPayment(user, plan)
    sent: list[tuple[object, ...]] = []
    operational_messages: list[str] = []
    refreshed: list[tuple[object, object, object]] = []

    class FakeBot:
        async def send_message(self, *args: object, **_: object) -> SimpleNamespace:
            sent.append(args)
            return SimpleNamespace()

    class FakeSession:
        async def get(self, _: object, user_id: int) -> User | None:
            return user if user_id == user.id else None

        async def commit(self) -> None:
            return None

    class FakeSessionContext:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *_: object) -> None:
            return None

    async def fake_refresh(bot: object, session: object, refreshed_user: object) -> None:
        refreshed.append((bot, session, refreshed_user))

    async def fake_operational_notification(_: object, text: str) -> None:
        operational_messages.append(text)

    fake_bot = FakeBot()
    monkeypatch.setattr(application, "bot", fake_bot)
    monkeypatch.setattr(application, "SessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(application, "refresh_visible_main_screen", fake_refresh)
    monkeypatch.setattr(application, "send_operational_notification", fake_operational_notification)

    await application.notify_payment_confirmation(payment)

    assert sent == [(701, "Оплата подтверждена. Доступ «Сезонный» активирован.")]
    assert operational_messages == [
        "💳 Подтверждена оплата\nПользователь: Telegram ID 700\nТариф: Сезонный\nСумма: 10,00 €"
    ]
    assert refreshed and refreshed[0][0] is fake_bot and refreshed[0][2] is user


@pytest.mark.asyncio
async def test_duplicate_payment_refreshes_the_main_screen_without_resending_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    user = User(id=18, telegram_user_id=800, telegram_chat_id=801, language="en", active_navigation_screen="payment")
    plan = SubscriptionPlan(id=5, code="season", name="Season", price_cents=1000)
    payment = ProcessedPayment(user, plan, duplicate=True)
    rendered: list[tuple[object, ...]] = []

    class FakeSession:
        async def get(self, _: object, __: int) -> User:
            return user

        async def commit(self) -> None:
            return None

    class FakeSessionContext:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *_: object) -> None:
            return None

    class FakeBot:
        async def send_message(self, *_: object, **__: object) -> None:
            raise AssertionError("duplicate payments must not resend confirmation")

    async def fake_main_screen(*args: object, **_: object) -> None:
        rendered.append(args)

    monkeypatch.setattr(application, "bot", FakeBot())
    monkeypatch.setattr(application, "SessionLocal", lambda: FakeSessionContext())
    monkeypatch.setattr(application, "main_screen", fake_main_screen)
    monkeypatch.setattr(
        application,
        "send_operational_notification",
        lambda *_: (_ for _ in ()).throw(AssertionError("duplicate payments must not resend operational notice")),
    )

    await application.notify_payment_confirmation(payment)

    assert rendered and rendered[0][2] is user
