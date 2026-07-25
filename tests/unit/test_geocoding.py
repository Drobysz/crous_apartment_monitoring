from app.geocoding.provider import photon_locale


def test_photon_uses_a_supported_locale_without_changing_the_ui_language() -> None:
    assert photon_locale("fr") == "fr"
    assert photon_locale("ru") == "fr"
    assert photon_locale("ar") == "fr"
