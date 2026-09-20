"""Configuration loading: .env + config/markets.yml."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

# repo root = .../opendoor-telemetry
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

CIK = 1801169  # Opendoor Technologies Inc. (verified via SEC company_tickers.json)
CIK_PADDED = f"CIK{CIK:010d}"


@dataclass(frozen=True)
class Market:
    key: str
    cbsa_name: str
    redfin_metro: list[str]
    opendoor_slug: str
    state: str
    centroid: tuple[float, float] | None = None
    radius_km: float = 80.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str
    fred_api_key: str | None
    pg_dsn: str
    cache_dir: Path
    sec_rate_limit: float
    opendoor_rate_limit: float
    markets: list[Market] = field(default_factory=list)
    fred_series: dict[str, str] = field(default_factory=dict)
    derived_series: dict[str, dict] = field(default_factory=dict)

    @property
    def redfin_metro_names(self) -> set[str]:
        """Every Redfin REGION string we care about, flattened."""
        return {name for m in self.markets for name in m.redfin_metro}

    def market_for_redfin_region(self, region: str) -> Market | None:
        for m in self.markets:
            if region in m.redfin_metro:
                return m
        return None

    def market_for_point(self, lat: float | None, lon: float | None) -> Market | None:
        """Assign a listing to an MSA by distance from the metro centroid.

        Opendoor listings carry lat/lon but no CBSA code. Matching on city
        name fails for the suburbs that make up most of a metro (Lithia
        Springs GA is Atlanta; Allen TX is DFW), and falling back to the
        state would wrongly pull Jacksonville into Tampa or Tucson into
        Phoenix. Distance from the centroid handles all of those correctly
        with no external crosswalk.

        Returns the nearest market whose radius contains the point, or None.
        """
        if lat is None or lon is None:
            return None
        best: tuple[float, Market] | None = None
        for m in self.markets:
            if m.centroid is None:
                continue
            d = _haversine_km(lat, lon, m.centroid[0], m.centroid[1])
            if d <= m.radius_km and (best is None or d < best[0]):
                best = (d, m)
        return best[1] if best else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    cfg_path = ROOT / "config" / "markets.yml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    markets = [
        Market(
            key=m["key"],
            cbsa_name=m["cbsa_name"],
            redfin_metro=list(m["redfin_metro"]),
            opendoor_slug=m["opendoor_slug"],
            state=m["state"],
            centroid=tuple(m["centroid"]) if m.get("centroid") else None,
            radius_km=float(m.get("radius_km", 80.0)),
        )
        for m in raw.get("markets", [])
    ]

    cache_dir = Path(os.getenv("CACHE_DIR", ROOT / ".cache"))
    if not cache_dir.is_absolute():
        cache_dir = ROOT / cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    ua = os.getenv("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        # SEC rejects generic agents with 403; fail loudly rather than at request time.
        raise RuntimeError(
            "SEC_USER_AGENT must be set in .env and contain a contact email, "
            'e.g. SEC_USER_AGENT="Opendoor Telemetry Research you@example.com". '
            "See https://www.sec.gov/os/webmaster-faq#developers"
        )

    return Settings(
        sec_user_agent=ua,
        fred_api_key=os.getenv("FRED_API_KEY") or None,
        pg_dsn=os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/opendoor"),
        cache_dir=cache_dir,
        sec_rate_limit=float(os.getenv("SEC_RATE_LIMIT", "8.0")),
        opendoor_rate_limit=float(os.getenv("OPENDOOR_RATE_LIMIT", "1.0")),
        markets=markets,
        fred_series=raw.get("fred_series", {}),
        derived_series=raw.get("derived_series", {}),
    )
