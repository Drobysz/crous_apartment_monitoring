from abc import ABC, abstractmethod

from app.geocoding.models import GeocodedPlace


class GeocodingProvider(ABC):
    @abstractmethod
    async def search(self, query: str, locale: str) -> list[GeocodedPlace]: ...
    @abstractmethod
    async def reverse(self, latitude: float, longitude: float, locale: str) -> list[GeocodedPlace]: ...
