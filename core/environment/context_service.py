import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple


EnvFetcher = Callable[[str], Awaitable[Dict[str, Any]]]
EnvWriter = Callable[[str, Dict[str, Any]], Awaitable[Dict[str, Any]]]
GeoFetcher = Callable[[float, float], Awaitable[Optional[Dict[str, Any]]]]


@dataclass
class EnvironmentSnapshot:
    data: Dict[str, Any]
    updated_at: float = field(default_factory=lambda: time.time())


class EnvironmentContextService:
    """
    管理即時環境資訊：
    - 記憶體快取 + TTL
    - 節流距離/方位差
    - Firestore 寫入排程（current + snapshots）
    - 反地理查詢背景處理
    """

    def __init__(
        self,
        *,
        min_distance_m: float,
        min_heading_deg: float,
        ttl_seconds: float,
        env_fetcher: EnvFetcher,
        env_writer: EnvWriter,
        snapshot_writer: Optional[EnvWriter] = None,
    ) -> None:
        self._min_distance = max(min_distance_m, 0.0)
        self._min_heading = max(min_heading_deg, 0.0)
        self._ttl = max(ttl_seconds, 1.0)
        self._env_fetcher = env_fetcher
        self._env_writer = env_writer
        self._snapshot_writer = snapshot_writer

        self._cache: Dict[str, EnvironmentSnapshot] = {}
        self._write_queue: "asyncio.Queue[Tuple[str, Dict[str, Any]]]" = asyncio.Queue()
        self._snapshot_queue: "asyncio.Queue[Tuple[str, Dict[str, Any]]]" = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        self._snapshot_task: Optional[asyncio.Task] = None
        self._geo_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # --------------------------------------------------------------------- #
    # 公開介面
    # --------------------------------------------------------------------- #
    async def start(self) -> None:
        if self._writer_task is None:
            self._writer_task = asyncio.create_task(self._write_loop(), name="env-current-writer")
        if self._snapshot_writer and self._snapshot_task is None:
            self._snapshot_task = asyncio.create_task(self._snapshot_loop(), name="env-snapshot-writer")

    async def shutdown(self) -> None:
        for pending in self._geo_tasks.values():
            pending.cancel()
        self._geo_tasks.clear()

        if self._writer_task:
            self._writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer_task
            self._writer_task = None

        if self._snapshot_task:
            self._snapshot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._snapshot_task
            self._snapshot_task = None

    async def ingest_snapshot(
        self,
        user_id: str,
        raw_payload: Dict[str, Any],
        *,
        geocode_provider: Optional[GeoFetcher] = None,
    ) -> Dict[str, Any]:
        """
        接收前端發送的環境快照，立即回傳 ACK 與基本資料，
        寫入 Firestore 與反地理查詢則交由背景處理。
        """
        if not user_id:
            raise ValueError("user_id is required for environment snapshot ingestion")

        normalized, write_snapshot = await self._normalize_snapshot(user_id, raw_payload)

        async with self._lock:
            self._cache[user_id] = EnvironmentSnapshot(data=normalized)

        await self._write_queue.put((user_id, normalized))
        if write_snapshot and self._snapshot_writer:
            await self._snapshot_queue.put((user_id, normalized))

        if geocode_provider and self._needs_geocode(normalized):
            await self._schedule_geocode(user_id, normalized, geocode_provider)

        ack = {
            "success": True,
            "geohash_7": normalized.get("geohash_7"),
            "heading_cardinal": normalized.get("heading_cardinal"),
        }
        return ack

    async def get_context(self, user_id: str, *, allow_stale: bool = False) -> Dict[str, Any]:
        async with self._lock:
            cached = self._cache.get(user_id)
            if cached and (allow_stale or not self._is_stale(cached)):
                return dict(cached.data)

        data = await self._env_fetcher(user_id)
        if data.get("success"):
            ctx = data.get("context") or {}
            async with self._lock:
                self._cache[user_id] = EnvironmentSnapshot(data=ctx)
            return dict(ctx)

        return {}

    # --------------------------------------------------------------------- #
    # 內部流程
    # --------------------------------------------------------------------- #
    async def _normalize_snapshot(
        self,
        user_id: str,
        raw_payload: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool]:
        lat = _safe_float(raw_payload.get("lat"))
        lon = _safe_float(raw_payload.get("lon"))
        accuracy = _safe_float(raw_payload.get("accuracy_m"))
        heading_deg = _safe_float(raw_payload.get("heading_deg"))

        ctx = {
            "lat": lat,
            "lon": lon,
            "accuracy_m": accuracy,
            "heading_deg": heading_deg,
            "heading_cardinal": _heading_to_cardinal(heading_deg) if heading_deg is not None else None,
            "tz": raw_payload.get("tz"),
            "locale": raw_payload.get("locale"),
            "device": raw_payload.get("device"),
            "city": raw_payload.get("city"),
            "admin": raw_payload.get("admin"),
            "country_code": raw_payload.get("country_code"),
            "address_display": raw_payload.get("address_display"),
            "geohash_7": _encode_geohash(lat, lon),
            "updated_at": time.time(),
        }

        previous = await self._get_cached(user_id)
        should_snapshot = self._should_snapshot(previous, ctx)

        if previous and not self._has_position_change(previous.data, ctx):
            # 沒有座標變化時保留先前的精細地理資訊
            for key in (
                "detailed_address",
                "label",
                "road",
                "house_number",
                "suburb",
                "city_district",
                "postcode",
                "amenity",
                "shop",
                "building",
                "office",
                "leisure",
                "tourism",
                "name",
            ):
                ctx[key] = previous.data.get(key)

        return ctx, should_snapshot

    async def _schedule_geocode(
        self,
        user_id: str,
        ctx: Dict[str, Any],
        geocode_provider: GeoFetcher,
    ) -> None:
        if user_id in self._geo_tasks:
            # 已有任務在跑，避免重複
            return

        async def _task() -> None:
            try:
                if ctx.get("lat") is None or ctx.get("lon") is None:
                    return
                enriched = await geocode_provider(ctx["lat"], ctx["lon"])
                if not enriched:
                    return

                async with self._lock:
                    cached = self._cache.get(user_id)
                    if not cached:
                        cached = EnvironmentSnapshot(data=dict(ctx))
                        self._cache[user_id] = cached
                    cached.data.update(enriched)
                    cached.updated_at = time.time()

                await self._write_queue.put((user_id, dict(cached.data)))
                if self._snapshot_writer:
                    await self._snapshot_queue.put((user_id, dict(cached.data)))
            finally:
                self._geo_tasks.pop(user_id, None)

        self._geo_tasks[user_id] = asyncio.create_task(_task(), name=f"env-geocode-{user_id}")

    async def _write_loop(self) -> None:
        while True:
            user_id, payload = await self._write_queue.get()
            try:
                await self._env_writer(user_id, payload)
            except Exception:
                # 寫入失敗時稍後重試
                await asyncio.sleep(1.0)
                await self._write_queue.put((user_id, payload))
            finally:
                self._write_queue.task_done()

    async def _snapshot_loop(self) -> None:
        while True:
            user_id, payload = await self._snapshot_queue.get()
            try:
                await self._snapshot_writer(user_id, payload)
            except Exception:
                await asyncio.sleep(2.0)
                await self._snapshot_queue.put((user_id, payload))
            finally:
                self._snapshot_queue.task_done()

    async def _get_cached(self, user_id: str) -> Optional[EnvironmentSnapshot]:
        async with self._lock:
            return self._cache.get(user_id)

    def _should_snapshot(self, previous: Optional[EnvironmentSnapshot], current: Dict[str, Any]) -> bool:
        if previous is None:
            return True
        return self._has_position_change(previous.data, current)

    def _has_position_change(self, previous: Dict[str, Any], current: Dict[str, Any]) -> bool:
        if previous.get("lat") is None or previous.get("lon") is None:
            return True
        if current.get("lat") is None or current.get("lon") is None:
            return False

        distance = _haversine_m(previous["lat"], previous["lon"], current["lat"], current["lon"])
        if distance >= self._min_distance:
            return True

        prev_heading = previous.get("heading_deg")
        curr_heading = current.get("heading_deg")
        if prev_heading is None or curr_heading is None:
            return False

        heading_diff = abs(curr_heading - prev_heading)
        heading_diff = min(heading_diff, 360 - heading_diff)
        return heading_diff >= self._min_heading

    def _is_stale(self, snapshot: EnvironmentSnapshot) -> bool:
        return (time.time() - snapshot.updated_at) > self._ttl

    def _needs_geocode(self, ctx: Dict[str, Any]) -> bool:
        if ctx.get("lat") is None or ctx.get("lon") is None:
            return False
        return not any(ctx.get(field) for field in ("city", "address_display", "label", "detailed_address"))


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _heading_to_cardinal(deg: Optional[float]) -> Optional[str]:
    if deg is None:
        return None
    try:
        val = float(deg)
    except (TypeError, ValueError):
        return None

    dirs = [
        "N",
        "NNE",
        "NE",
        "ENE",
        "E",
        "ESE",
        "SE",
        "SSE",
        "S",
        "SSW",
        "SW",
        "WSW",
        "W",
        "WNW",
        "NW",
        "NNW",
    ]
    idx = int((val % 360) / 22.5 + 0.5) % len(dirs)
    return dirs[idx]


def _encode_geohash(lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    if lat is None or lon is None:
        return None
    try:
        from geohash2 import encode as gh_encode  # type: ignore
    except Exception:
        return None
    try:
        return gh_encode(lat, lon, precision=7)
    except Exception:
        return None


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    使用哈弗辛公式計算兩點距離（公尺）
    """
    rad_lat1 = math.radians(lat1)
    rad_lat2 = math.radians(lat2)
    dlat = rad_lat2 - rad_lat1
    dlon = math.radians(lon2 - lon1)

    a = math.sin(dlat / 2) ** 2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return 6371000.0 * c


import contextlib  # noqa: E402  # placed at end to avoid circular import at module load
