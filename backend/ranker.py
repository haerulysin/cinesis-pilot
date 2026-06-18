from math import atan2, cos, radians, sin, sqrt
from typing import Any

import requests
try:
    from .util import get_logger
except ImportError:
    from util import get_logger

logger = get_logger("cinesis.ranker")

GEOCODE_CACHE: dict[str, tuple[float, float] | None] = {}
GEOCODE_HEADERS = {"User-Agent": "cinesis-demo/1.0"}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    # R =   
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return round(3958.8 * c, 3)


def _normalize_equipment_types(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item) for item in values if item is not None and str(item).strip()]


def _allowed_equipment_reason(load_trailer: str, equipment_types: list[str]) -> str:
    allowed = "/".join(equipment_types) if equipment_types else "no equipment"
    return f"{load_trailer} trailer — driver runs {allowed} only"


def _overweight_reason(weight: Any, capacity: Any) -> str:
    weight_str = f"{weight:,}" if isinstance(weight, (int, float)) else str(weight)
    capacity_str = f"{capacity:,}" if isinstance(capacity, (int, float)) else str(capacity)
    return f"Overweight ({weight_str} lb exceeds {capacity_str} lb capacity)"


def _geocode_location(query: str | None) -> tuple[float, float] | None:
    if not query or not str(query).strip():
        return None

    normalized = str(query).strip().lower()
    if normalized in GEOCODE_CACHE:
        return GEOCODE_CACHE[normalized]

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers=GEOCODE_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if not data:
            GEOCODE_CACHE[normalized] = None
            return None

        coords = (float(data[0]["lat"]), float(data[0]["lon"]))
        GEOCODE_CACHE[normalized] = coords
        return coords
    except Exception:
        GEOCODE_CACHE[normalized] = None
        return None


def _resolve_coords(source: dict[str, Any], lat_key: str, lon_key: str, location_key: str) -> tuple[float, float] | None:
    lat = source.get(lat_key)
    lon = source.get(lon_key)

    print(lat, lon, location_key, flush=True)
    if lat is not None and lon is not None:
        try:
            return float(lat), float(lon)
        except Exception:
            return None
    return _geocode_location(source.get(location_key))


def find_candidate_cities(
    origin_lat: float,
    origin_lon: float,
    radius_miles: float,
    limit: int = 15,
) -> list[dict[str, Any]]:
    """
    Search Nominatim for cities within radius_miles of origin.
    Returns list of {"name": str, "lat": float, "lon": float}
    """
    delta = radius_miles / 69.0
    viewbox = f"{origin_lon - delta},{origin_lat + delta},{origin_lon + delta},{origin_lat - delta}"
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": "city",
                "format": "json",
                "bounded": 1,
                "viewbox": viewbox,
                "featuretype": "city",
                "limit": limit,
            },
            headers=GEOCODE_HEADERS,
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        cities: list[dict[str, Any]] = []
        for item in data:
            name = item.get("display_name", "").split(",")[0].strip()
            lat = float(item["lat"])
            lon = float(item["lon"])
            if name:
                cities.append({"name": name, "lat": lat, "lon": lon})
        return cities
    except Exception:
        return []


def rank_loads(profile: dict[str, Any], loads: list[dict[str, Any]]) -> dict[str, Any]:
    equipment_types = _normalize_equipment_types(profile.get("equipment_types"))
    weight_capacity = profile.get("weight_capacity_lb")
    current_coords = _resolve_coords(profile, "current_lat", "current_lon", "current_location")
    home_coords = _resolve_coords(profile, "home_lat", "home_lon", "home_base")

    top_candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for load in loads:
        load_id = load.get("load_id")
        trailer = load.get("trailer")
        weight = load.get("weight")
        price = load.get("price")
        origin = load.get("origin")
        destination = load.get("destination")

        # equipment check — exit immediately if fails
        if trailer not in equipment_types:
            rejected.append(
                {
                    "load_id": load_id,
                    "reason": _allowed_equipment_reason(str(trailer), equipment_types),
                }
            )
            continue

        # price check
        if price is None:
            rejected.append({"load_id": load_id, "reason": "Missing price"})
            continue

        # weight check
        if weight is None or weight_capacity is None or weight > weight_capacity:
            rejected.append(
                {
                    "load_id": load_id,
                    "reason": _overweight_reason(weight, weight_capacity),
                }
            )
            continue

        if current_coords is None:
            rejected.append({"load_id": load_id, "reason": "Unable to geocode current location"})
            continue

        if home_coords is None:
            rejected.append({"load_id": load_id, "reason": "Unable to geocode home base"})
            continue

        origin_coords = _resolve_coords(load, "origin_lat", "origin_lon", "origin")
        if origin_coords is None:
            rejected.append({"load_id": load_id, "reason": f"Unable to geocode origin {origin}"})
            continue

        if destination is None:
            min_rate = profile.get("min_rate_per_mile", 2.0)
            max_total = price / min_rate

            # check from current location
            leg1_current = haversine(
                current_coords[0], current_coords[1],
                origin_coords[0], origin_coords[1],
            )
            leg3_current = haversine(
                origin_coords[0], origin_coords[1],
                home_coords[0], home_coords[1],
            )
            fixed_current = leg1_current + leg3_current
            remaining_current = max_total - fixed_current

            # check from home base
            leg1_home = haversine(
                home_coords[0], home_coords[1],
                origin_coords[0], origin_coords[1],
            )
            leg3_home = haversine(
                origin_coords[0], origin_coords[1],
                home_coords[0], home_coords[1],
            )
            fixed_home = leg1_home + leg3_home
            remaining_home = max_total - fixed_home

            # pick best position (highest remaining budget)
            if remaining_current >= remaining_home:
                best_start = profile.get("current_location", "current location")
                best_start_coords = current_coords
                best_leg1 = leg1_current
                best_leg3_min = leg3_current
                best_fixed = fixed_current
                best_remaining = remaining_current
            else:
                best_start = profile.get("home_base", "home base")
                best_start_coords = home_coords
                best_leg1 = leg1_home
                best_leg3_min = leg3_home
                best_fixed = fixed_home
                best_remaining = remaining_home

            # if best remaining <= 0, reject immediately — no city search needed
            if best_remaining <= 0:
                rejected.append({
                    "load_id": load_id,
                    "reason": (
                        f"Destination missing. "
                        f"Best starting position: {best_start}. "
                        f"Fixed legs ({best_start}→{origin} {best_leg1:.0f} mi + "
                        f"{origin}→home {best_leg3_min:.0f} mi) = {best_fixed:.0f} mi "
                        f"already exceeds max budget {max_total:.0f} mi at ${min_rate:.2f}/mi. "
                        f"Checked both current location ({profile.get('current_location')}) "
                        f"and home base ({profile.get('home_base')}) — load unviable from either position."
                    )
                })
                continue

            # if remaining > 0, search for viable cities near origin
            candidates = find_candidate_cities(
                origin_coords[0], origin_coords[1],
                best_remaining / 2,
            )

            best_eff_rate = 0.0
            best_city = None
            best_leg2 = 0.0
            best_leg3 = 0.0

            for city in candidates:
                leg2 = haversine(origin_coords[0], origin_coords[1], city["lat"], city["lon"])
                leg3 = haversine(city["lat"], city["lon"], home_coords[0], home_coords[1])
                total = best_leg1 + leg2 + leg3
                eff_rate = round(price / total, 3) if total else 0.0
                if eff_rate > best_eff_rate:
                    best_eff_rate = eff_rate
                    best_city = city
                    best_leg2 = leg2
                    best_leg3 = leg3

            if best_city and best_eff_rate >= min_rate:
                top_candidates.append({
                    "load_id": load_id,
                    "origin": origin,
                    "destination": best_city["name"],
                    "trailer": trailer,
                    "weight": weight,
                    "price": price,
                    "leg1_mi": best_leg1,
                    "leg2_mi": best_leg2,
                    "leg3_mi": best_leg3,
                    "total_mi": round(best_leg1 + best_leg2 + best_leg3, 3),
                    "eff_rate_per_mile": best_eff_rate,
                    "estimated": True,
                    "starting_from": best_start,
                    "note": f"Destination estimated as {best_city['name']} starting from {best_start} — unconfirmed. Offer with caveat.",
                })
            else:
                best_name = best_city["name"] if best_city else "any city"
                rejected.append({
                    "load_id": load_id,
                    "reason": (
                        f"Destination missing. Searched cities within {best_remaining / 2:.0f} mi of {origin} "
                        f"starting from {best_start} — best estimated rate ${best_eff_rate:.3f}/mi ({best_name}) "
                        f"below driver minimum ${min_rate:.2f}/mi. Load unviable from any position."
                    ),
                    "best_estimated_city": best_city["name"] if best_city else None,
                    "best_estimated_rate": best_eff_rate,
                })
            continue



        dest_coords = _resolve_coords(load, "destination_lat", "destination_lon", "destination")
        if dest_coords is None:
            rejected.append({"load_id": load_id, "reason": f"Unable to geocode destination {destination}"})
            continue


        # deadhead_to_origin 
        leg1 = haversine(current_coords[0], current_coords[1], origin_coords[0], origin_coords[1])
        # loaded_miles 
        leg2 = haversine(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])
        # deadhead_home 
        leg3 = haversine(dest_coords[0], dest_coords[1], home_coords[0], home_coords[1])
        total_miles = round(leg1 + leg2 + leg3, 3)
        eff_rate_per_mile = round(price / total_miles, 3) if total_miles else 0.0

        top_candidates.append(
            {
                "load_id": load_id,
                "origin": origin,
                "destination": destination,
                "trailer": trailer,
                "weight": weight,
                "price": price,
                "leg1_mi": leg1,
                "leg2_mi": leg2,
                "leg3_mi": leg3,
                "total_mi": total_miles,
                "eff_rate_per_mile": eff_rate_per_mile,
            }
        )

    top_candidates.sort(key=lambda item: item["eff_rate_per_mile"], reverse=True)

    logger.info(f"Top candidates: {top_candidates}")
    logger.info(f"Rejected: {rejected}")
    top3 = []
    for index, load in enumerate(top_candidates[:3], start=1):
        top3.append({"rank": index, **load})

    return {"top3": top3, "rejected": rejected}
