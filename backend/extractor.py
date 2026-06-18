from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

try:
    from .util import get_logger
except ImportError:
    from util import get_logger

logger = get_logger("cinesis.extractor")

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

GATEWAY_PROMPT = """You are an AI dispatcher assistant. Read the following driver conversation transcript and extract a structured driver profile.
Return ONLY valid JSON with these exact keys:
- current_location: string, city and state
- home_base: string, city and state
- min_rate_per_mile: float, dollar amount per mile
- equipment_types: array of strings
- weight_capacity_lb: integer, maximum payload in pounds

Rules:
- The driver never states these as clean fields. Infer them from natural speech.
- Extract only the driver's actual preferences, constraints, and operating details.
- Do not treat the dispatcher's example load rate as the driver's minimum rate unless the driver clearly accepts it as their minimum.
- current_location is where the truck/driver is now, not where they are usually based.
- home_base is where the driver normally returns or is based.
- weight_capacity_lb must be a plain integer in pounds.
- Normalize weight phrases:
  - "20k" -> 20000
  - "20,000 lbs" -> 20000
  - "twenty thousand pounds" -> 20000
- equipment_types must be an array.
- Use only these equipment values when applicable: "Hotshot", "Gooseneck", "Flatbed", "Van".
- "hotshot" and "gooseneck" are separate valid values.
- Normalize equipment aliases:
  - "hot shot" -> "Hotshot"
  - "hotshot" -> "Hotshot"
  - "goose neck" -> "Gooseneck"
  - "gooseneck" -> "Gooseneck"
  - "flat bed" -> "Flatbed"
  - "dry van" -> "Van"
CRITICAL RULE for weight_capacity_lb:
- This field means the DRIVER'S truck maximum payload capacity
- Only extract weight from lines where Speaker = "Driver"
- The dispatcher mentions "44,000 pounds" — this is a load weight, NOT the driver's capacity
- The driver never states their own weight capacity in this transcript
- If no Driver line explicitly states a weight capacity, return 16000
- 16000 is the legal max payload for a hotshot gooseneck trailer

- If multiple equipment types are mentioned, include all valid types.
- Return ONLY the JSON object.
- Do not include explanation.
- Do not include markdown.

"""

# Mock gateway response used while the live API call is disabled.
MOCK_RESPONSE: dict[str, Any] = {
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": (
                        '{"current_location":"Dallas, TX","home_base":"San Antonio, TX",'
                        '"min_rate_per_mile":2.0,"equipment_types":["Hotshot","Gooseneck"],'
                        '"weight_capacity_lb":44000}'
                    ),
                }
            ],
        }
    ]
}


def _load_env() -> None:
    load_dotenv(ENV_PATH, override=False)


def _extract_text(value: Any) -> str:
    texts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            texts.append(node)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if isinstance(node, dict):
            for key in ("output_text", "text"):
                if isinstance(node.get(key), str):
                    texts.append(node[key])
            for key in ("content", "output", "message"):
                if key in node:
                    walk(node[key])
            for key, child in node.items():
                if isinstance(child, (dict, list)) and key not in {"content", "output", "message"}:
                    walk(child)

    walk(value)
    return "\n".join(part for part in texts if part)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _extract_first_json_object(text: str) -> str:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    raise ValueError("No JSON object found")


def _parse_json_payload(text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(text)
    candidates = [cleaned]
    if cleaned != text:
        candidates.append(text)
    try:
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        extracted = _extract_first_json_object(cleaned)
        
        return json.loads(extracted)
    except Exception as exc:
        raise ValueError("Invalid JSON payload") from exc


def _geocode_location(query: str | None) -> tuple[float, float] | None:
    if not query:
        return None

    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "cinesis-demo/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception:
        logger.warning("Geocoding failed for %r", query)

    return None


def _resolve_coords(
    profile: dict[str, Any], lat_key: str, lon_key: str, location: str
) -> tuple[float, float] | None:
    if profile.get(lat_key) is not None and profile.get(lon_key) is not None:
        return float(profile[lat_key]), float(profile[lon_key])
    return _geocode_location(location)


def _normalize_profile(profile: dict[str, Any], raw_ai_response: str) -> dict[str, Any]:
    current_location = profile.get("current_location")
    home_base = profile.get("home_base")
    min_rate_per_mile = profile.get("min_rate_per_mile")
    equipment_types = profile.get("equipment_types")
    weight_capacity_lb = profile.get("weight_capacity_lb", 16000)

    if not isinstance(current_location, str) or not current_location.strip():
        raise ValueError("current_location missing")
    if not isinstance(home_base, str) or not home_base.strip():
        raise ValueError("home_base missing")
    if not isinstance(min_rate_per_mile, (int, float)):
        raise ValueError("min_rate_per_mile missing")

    if not isinstance(equipment_types, list):
        equipment_types = []
    equipment_types = [str(item) for item in equipment_types if item is not None and str(item).strip()]
    if not equipment_types:
        raise ValueError("equipment_types missing")

    try:
        weight_capacity_lb = int(weight_capacity_lb)
    except Exception as exc:
        raise ValueError("weight_capacity_lb invalid") from exc

    normalized: dict[str, Any] = {
        "current_location": current_location.strip(),
        "home_base": home_base.strip(),
        "min_rate_per_mile": float(min_rate_per_mile),
        "equipment_types": equipment_types,
        "weight_capacity_lb": weight_capacity_lb,
        "rawAiResponse": raw_ai_response,
    }

    current_coords = _resolve_coords(profile, "current_lat", "current_lon", current_location)
    if current_coords is not None:
        normalized["current_lat"], normalized["current_lon"] = current_coords

    home_coords = _resolve_coords(profile, "home_lat", "home_lon", home_base)
    if home_coords is not None:
        normalized["home_lat"], normalized["home_lon"] = home_coords

    return normalized


def extract_driver_profile(transcript: str) -> dict[str, Any]:
    _load_env()
    api_key = os.getenv("AI_GATEWAY_API_KEY", "").strip()
    api_url = os.getenv("AI_GATEWAY_URL", "").strip()
    model = os.getenv("AI_MODEL", "").strip()
    
    if not api_key:
        raise RuntimeError("missing api key")
    if not api_url:
        raise RuntimeError("missing api url")
    if not model:
        raise RuntimeError("missing model")
    
    response = requests.post(
        api_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "instructions": GATEWAY_PROMPT,
            "input": transcript,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    logger.info("API response: %s", payload)

    # payload = MOCK_RESPONSE

    text = _extract_text(payload)
    if not text.strip():
        raise ValueError("missing model text")

    parsed = _parse_json_payload(text)
    if not isinstance(parsed, dict):
        raise ValueError("model output was not an object")

    normalized = _normalize_profile(parsed, text)
    # logger.info("Normalized driver profile: %s", normalized)
    return normalized
