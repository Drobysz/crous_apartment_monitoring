import pytest

from app.geocoding.provider import PhotonProvider, photon_locale


def test_photon_uses_a_supported_locale_without_changing_the_ui_language() -> None:
    assert photon_locale("fr") == "fr"
    assert photon_locale("ru") == "fr"
    assert photon_locale("ar") == "fr"


@pytest.mark.asyncio
async def test_photon_reads_city_extent_from_properties_not_a_point_fallback() -> None:
    provider = PhotonProvider()
    try:
        places = provider._convert(
            {
                "features": [
                    {
                        "geometry": {"coordinates": [6.1834097, 48.6937223]},
                        "properties": {
                            "name": "Nancy",
                            "postcode": "54000",
                            "country": "France",
                            "extent": [6.134292, 48.7092349, 6.2126188, 48.666906],
                        },
                    }
                ]
            }
        )
    finally:
        await provider.client.aclose()
    place = places[0]
    assert (place.west, place.north, place.east, place.south) == (
        6.134292,
        48.7092349,
        6.2126188,
        48.666906,
    )
