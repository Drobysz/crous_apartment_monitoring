from app.core.i18n import SUPPORTED_LANGUAGES, detect_language, i18n


def test_telegram_language_detection_and_french_fallback() -> None:
    assert detect_language("ru-RU") == "ru"
    assert detect_language("fr") == "fr"
    assert detect_language("ar_EG") == "ar"
    assert detect_language("en-US") == "fr"


def test_all_catalogs_have_the_same_required_keys() -> None:
    french = set(i18n.catalogs["fr"])
    assert all(set(i18n.catalogs[language]) == french for language in SUPPORTED_LANGUAGES)
    assert "المنطقة" in i18n.text("ar", "area", value="Nancy")
