from dataclasses import dataclass


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float

    @staticmethod
    def normalize(lat, lon):
        lon = ((lon + 180) % 360) - 180
        lat = max(min(lat, 90.0), -90.0)
        return GeoPoint(lat, lon)

    def key(self):
        return f"{self.lat:.5f}_{self.lon:.5f}"
