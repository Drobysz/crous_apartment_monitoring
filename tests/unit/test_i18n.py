from app.core.i18n import SUPPORTED_LANGUAGES, detect_language, i18n


def test_telegram_language_detection_and_english_fallback() -> None:
    assert detect_language("ru-RU") == "ru"
    assert detect_language("fr") == "fr"
    assert detect_language("ar_EG") == "ar"
    assert detect_language("en-US") == "en"


def test_all_catalogs_have_the_same_required_keys() -> None:
    english = set(i18n.catalogs["en"])
    assert all(set(i18n.catalogs[language]) == english for language in SUPPORTED_LANGUAGES)
    assert "المنطقة" in i18n.text("ar", "area", value="Nancy")


def test_main_menu_actions_are_translated_in_every_supported_language() -> None:
    for language in SUPPORTED_LANGUAGES:
        assert i18n.text(language, "check-now") != i18n.text("en", "check-now") or language == "en"
    assert {
        "filters": i18n.text("ru", "filters"),
        "subscription": i18n.text("ru", "subscription"),
        "check-now": i18n.text("ru", "check-now"),
        "disable-monitoring": i18n.text("ru", "disable-monitoring"),
    } == {
        "filters": "⚙️ Фильтры",
        "subscription": "💳 Подписка",
        "check-now": "⚡ Проверить сейчас",
        "disable-monitoring": "Отключить мониторинг",
    }
