import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_public_paths_are_normalized() -> None:
    settings = Settings(api_prefix="crous_bot_api/", admin_panel_prefix="/panel/")
    assert settings.api_prefix == "/crous_bot_api"
    assert settings.admin_panel_prefix == "/panel"
    assert settings.notification_bot_webhook_path == "/notification_bot/webhook"


@pytest.mark.parametrize(
    "value",
    ["https://example.test/panel", "/panel?preview=1", "/panel#section", "/panel/../admin"],
)
def test_path_prefixes_reject_urls_queries_fragments_and_traversal(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(admin_panel_prefix=value)


def test_path_prefixes_reject_conflicts() -> None:
    with pytest.raises(ValidationError):
        Settings(web_app_prefix="/panel", admin_panel_prefix="/panel")
