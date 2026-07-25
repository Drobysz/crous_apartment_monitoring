import pytest

from app.geocoding.provider import PhotonProvider, photon_locale


def test_photon_uses_a_supported_locale_without_changing_the_ui_language() -> None:
    assert photon_locale("fr") == "fr"
    assert photon_locale("ru") == "fr"
    assert photon_locale("ar") == "fr"


@pytest.mark.asyncio
async def test_forward_geocoding_deduplicates_same_city_and_postcode() -> None:
    provider = PhotonProvider()
    try:
        places = provider._convert(
            {
                "features": [
                    {
                        "geometry": {"coordinates": [6.18, 48.69]},
                        "properties": {
                            "name": "Nancy",
                            "postcode": "54000",
                            "country": "France",
                            "extent": [6.13, 48.71, 6.21, 48.66],
                        },
                    },
                    {
                        "geometry": {"coordinates": [6.19, 48.68]},
                        "properties": {
                            "city": "Nancy",
                            "postcode": "54000",
                            "country": "France",
                            "extent": [6.13, 48.71, 6.21, 48.66],
                        },
                    },
                ]
            }
        )
    finally:
        await provider.client.aclose()

    assert [place.display_name for place in places] == ["Nancy (54000)"]


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


@pytest.mark.asyncio
async def test_reverse_geocoding_uses_a_french_city_boundary() -> None:
    provider = PhotonProvider()
    try:
        places = provider._convert_nominatim(
            {
                "features": [
                    {
                        "geometry": {"coordinates": [6.0243622, 47.2380222]},
                        "bbox": [5.9409668, 47.2006872, 6.0835059, 47.3200746],
                        "properties": {
                            "address": {
                                "city": "Besançon",
                                "postcode": "25000",
                                "country_code": "fr",
                            }
                        },
                    }
                ]
            }
        )
    finally:
        await provider.client.aclose()

    assert [(place.display_name, place.provider) for place in places] == [
        ("Besançon (25000)", "nominatim")
    ]
    assert (places[0].west, places[0].north, places[0].east, places[0].south) == (
        5.9409668,
        47.3200746,
        6.0835059,
        47.2006872,
    )
