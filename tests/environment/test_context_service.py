import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.environment import EnvironmentContextService


def test_ingest_snapshot_writes_current():
    async def _run():
        writes: list = []
        snapshots: list = []

        async def fake_fetcher(user_id: str) -> Dict[str, Any]:
            return {"success": True, "context": {}}

        async def fake_writer(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            writes.append((user_id, payload))
            return {"success": True}

        async def fake_snapshot_writer(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            snapshots.append((user_id, payload))
            return {"success": True}

        service = EnvironmentContextService(
            min_distance_m=10.0,
            min_heading_deg=10.0,
            ttl_seconds=60.0,
            env_fetcher=fake_fetcher,
            env_writer=fake_writer,
            snapshot_writer=fake_snapshot_writer,
        )

        await service.start()
        try:
            ack = await service.ingest_snapshot(
                "user-1",
                {"lat": 25.0, "lon": 121.5, "heading_deg": 90, "tz": "Asia/Taipei"},
            )
            assert ack["success"] is True

            await asyncio.sleep(0.05)
            assert writes, "should enqueue current write"
            assert snapshots, "should enqueue snapshot write"

            ctx = await service.get_context("user-1", allow_stale=True)
            assert ctx["lat"] == 25.0
            assert ctx["heading_cardinal"] == "E"
        finally:
            await service.shutdown()

    asyncio.run(_run())


def test_ingest_snapshot_with_geocode():
    async def _run():
        writes: list = []

        async def fake_fetcher(user_id: str) -> Dict[str, Any]:
            return {"success": False}

        async def fake_writer(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            writes.append(payload)
            return {"success": True}

        service = EnvironmentContextService(
            min_distance_m=0.0,
            min_heading_deg=0.0,
            ttl_seconds=60.0,
            env_fetcher=fake_fetcher,
            env_writer=fake_writer,
            snapshot_writer=None,
        )

        async def geocode(lat: float, lon: float) -> Dict[str, Any]:
            return {"city": "Taipei", "address_display": "Taipei City"}

        await service.start()
        try:
            await service.ingest_snapshot(
                "geo-user",
                {"lat": 25.0, "lon": 121.5},
                geocode_provider=geocode,
            )
            await asyncio.sleep(0.05)
            ctx = await service.get_context("geo-user", allow_stale=True)
            assert ctx.get("city") == "Taipei"
            assert any(entry.get("city") == "Taipei" for entry in writes)
        finally:
            await service.shutdown()

    asyncio.run(_run())
