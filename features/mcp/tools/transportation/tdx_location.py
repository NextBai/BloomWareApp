import logging
from typing import Any, Dict, Iterable, Optional, Tuple

from ..base_tool import ExecutionError

logger = logging.getLogger("mcp.tools.tdx.location")

CITY_CODE_MAP = {
    "台北": "Taipei",
    "臺北": "Taipei",
    "新北": "NewTaipei",
    "桃園": "Taoyuan",
    "台中": "Taichung",
    "臺中": "Taichung",
    "台南": "Tainan",
    "臺南": "Tainan",
    "高雄": "Kaohsiung",
    "新竹": "Hsinchu",
    "基隆": "Keelung",
    "苗栗": "MiaoliCounty",
    "彰化": "ChanghuaCounty",
    "南投": "NantouCounty",
    "雲林": "YunlinCounty",
    "嘉義市": "Chiayi",
    "嘉義": "Chiayi",
    "嘉義縣": "ChiayiCounty",
    "屏東": "PingtungCounty",
    "宜蘭": "YilanCounty",
    "花蓮": "HualienCounty",
    "台東": "TaitungCounty",
    "臺東": "TaitungCounty",
    "金門": "KinmenCounty",
    "澎湖": "PenghuCounty",
    "連江": "LienchiangCounty",
    "馬祖": "LienchiangCounty",
}

METRO_OPERATOR_MAP = {
    "台北": "TRTC",
    "臺北": "TRTC",
    "新北": "NTMC",
    "桃園": "TYMC",
    "台中": "TMRT",
    "臺中": "TMRT",
    "高雄": "KRTC",
}

CITY_NEIGHBORS = {
    "Taipei": ["NewTaipei", "Keelung", "Taoyuan"],
    "NewTaipei": ["Taipei", "Keelung", "Taoyuan", "YilanCounty"],
    "Taoyuan": ["NewTaipei", "Taipei", "Hsinchu", "HsinchuCounty"],
    "Hsinchu": ["HsinchuCounty", "Taoyuan", "MiaoliCounty"],
    "HsinchuCounty": ["Hsinchu", "Taoyuan", "MiaoliCounty"],
    "MiaoliCounty": ["HsinchuCounty", "Hsinchu", "Taichung"],
    "Taichung": ["MiaoliCounty", "ChanghuaCounty", "NantouCounty", "YunlinCounty"],
    "ChanghuaCounty": ["Taichung", "NantouCounty", "YunlinCounty"],
    "NantouCounty": ["Taichung", "ChanghuaCounty", "YunlinCounty", "ChiayiCounty", "Tainan"],
    "YunlinCounty": ["ChanghuaCounty", "NantouCounty", "Chiayi", "ChiayiCounty", "Taichung"],
    "Chiayi": ["ChiayiCounty", "YunlinCounty", "Tainan"],
    "ChiayiCounty": ["Chiayi", "YunlinCounty", "Tainan", "Kaohsiung"],
    "Tainan": ["ChiayiCounty", "Kaohsiung"],
    "Kaohsiung": ["Tainan", "PingtungCounty"],
    "PingtungCounty": ["Kaohsiung", "TaitungCounty"],
    "Keelung": ["Taipei", "NewTaipei"],
    "YilanCounty": ["NewTaipei", "HualienCounty"],
    "HualienCounty": ["YilanCounty", "TaitungCounty"],
    "TaitungCounty": ["HualienCounty", "PingtungCounty"],
}


def _normalize_city_text(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = str(value).strip()
    for suffix in ("市", "縣"):
        if normalized.endswith(suffix):
            normalized = normalized[:-1]
    return normalized.strip()


def resolve_city_code(city_like: Optional[str], allowed: Optional[Iterable[str]] = None) -> Optional[str]:
    normalized = _normalize_city_text(city_like)
    if not normalized:
        return None
    if normalized in CITY_CODE_MAP:
        code = CITY_CODE_MAP[normalized]
    elif city_like in CITY_CODE_MAP:
        code = CITY_CODE_MAP[city_like]
    elif city_like and str(city_like).strip() in CITY_CODE_MAP.values():
        code = str(city_like).strip()
    else:
        code = None

    if code and allowed and code not in set(allowed):
        return None
    return code


def resolve_metro_operator(city_like: Optional[str]) -> Optional[str]:
    normalized = _normalize_city_text(city_like)
    if not normalized:
        return None
    return METRO_OPERATOR_MAP.get(normalized)


def resolve_city_candidates(
    *,
    city_like: Optional[str],
    geo_city: Optional[str],
    geo_admin: Optional[str],
    allowed_city_codes: Iterable[str],
    include_neighbors: bool = True,
) -> list[str]:
    allowed = set(allowed_city_codes)
    ordered: list[str] = []

    def push(code: Optional[str]) -> None:
        if code and code in allowed and code not in ordered:
            ordered.append(code)

    base = resolve_city_code(city_like, allowed=allowed) or resolve_city_code(geo_city, allowed=allowed) or resolve_city_code(geo_admin, allowed=allowed)
    push(base)

    if include_neighbors and base:
        for neighbor in CITY_NEIGHBORS.get(base, []):
            push(neighbor)

    if not ordered:
        ordered.extend(sorted(allowed))

    return ordered


def resolve_metro_operator_candidates(
    *,
    city_like: Optional[str],
    geo_city: Optional[str],
    geo_admin: Optional[str],
) -> list[str]:
    base = resolve_metro_operator(city_like) or resolve_metro_operator(geo_city) or resolve_metro_operator(geo_admin)
    if base == "NTMC" or base == "TRTC":
        return ["TRTC", "NTMC"]
    if base:
        return [base]
    return ["TRTC", "NTMC", "TYMC", "TMRT", "KRTC"]


async def resolve_coordinates(
    *,
    lat: Optional[float],
    lon: Optional[float],
    location_query: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float], Optional[Dict[str, Any]]]:
    if lat is not None and lon is not None:
        return float(lat), float(lon), None

    query = (location_query or "").strip()
    if not query:
        return lat, lon, None

    from ..location.geocoding_tool import ForwardGeocodeTool

    result = await ForwardGeocodeTool.execute({"query": query, "limit": 1})
    best_match = result.get("best_match") or {}
    if best_match.get("lat") is None or best_match.get("lon") is None:
        raise ExecutionError(f"無法解析位置「{query}」")

    logger.info("📍 [TDXLocation] location_query=%s -> (%s, %s)", query, best_match["lat"], best_match["lon"])
    return float(best_match["lat"]), float(best_match["lon"]), best_match


async def resolve_geo_context(
    *,
    lat: Optional[float],
    lon: Optional[float],
) -> Dict[str, Any]:
    if lat is None or lon is None:
        return {}
    from ..location.geocode_tool import ReverseGeocodeTool
    result = await ReverseGeocodeTool.execute({"lat": float(lat), "lon": float(lon)})
    return {
        "city": result.get("city") or "",
        "admin": result.get("admin") or "",
        "label": result.get("label") or "",
        "detailed_address": result.get("detailed_address") or "",
        "road": result.get("road") or "",
        "house_number": result.get("house_number") or "",
        "city_code": resolve_city_code(result.get("city") or result.get("admin")),
        "metro_operator": resolve_metro_operator(result.get("city") or result.get("admin")),
    }


async def resolve_location_context(
    *,
    lat: Optional[float],
    lon: Optional[float],
    location_query: Optional[str],
    city_like: Optional[str] = None,
    allowed_city_codes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    resolved_lat, resolved_lon, geocode_match = await resolve_coordinates(
        lat=lat,
        lon=lon,
        location_query=location_query,
    )
    geo_ctx = await resolve_geo_context(lat=resolved_lat, lon=resolved_lon)
    explicit_city_code = resolve_city_code(city_like, allowed=allowed_city_codes)
    city_code = explicit_city_code or resolve_city_code(
        geo_ctx.get("city") or geo_ctx.get("admin"),
        allowed=allowed_city_codes,
    )

    return {
        "lat": resolved_lat,
        "lon": resolved_lon,
        "city_code": city_code,
        "geo": geo_ctx,
        "geocode_match": geocode_match or {},
    }
