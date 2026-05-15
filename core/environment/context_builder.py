from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class EnvironmentInjection:
    summary_text: str
    raw_context: Dict[str, Any]
    metadata: Dict[str, Any]


class EnvironmentContextBuilder:
    """
    將最新環境快照轉成固定可注入格式。

    設計目標：
    1. 每回合固定注入，但內容結構固定，避免 prompt 漂移
    2. 同時保留 raw context，供工具與 runtime 做更細緻決策
    3. 缺資料時明確標記 freshness / completeness，而不是靜默忽略
    """

    def build(
        self,
        env_context: Optional[Dict[str, Any]],
        *,
        now: Optional[datetime] = None,
    ) -> EnvironmentInjection:
        ctx = dict(env_context or {})
        current_time = now or datetime.now(timezone.utc)

        lines = [
            f"snapshot_time_utc: {current_time.isoformat()}",
            f"has_location: {self._has_location(ctx)}",
            f"has_address: {bool(ctx.get('detailed_address') or ctx.get('address_display') or ctx.get('label'))}",
            f"has_timezone: {bool(ctx.get('tz'))}",
            f"has_locale: {bool(ctx.get('locale'))}",
        ]

        if ctx.get("detailed_address"):
            lines.append(f"detailed_address: {ctx['detailed_address']}")
        elif ctx.get("address_display"):
            lines.append(f"address_display: {ctx['address_display']}")
        elif ctx.get("label"):
            lines.append(f"label: {ctx['label']}")

        if ctx.get("city"):
            lines.append(f"city: {ctx['city']}")
        if ctx.get("admin"):
            lines.append(f"admin: {ctx['admin']}")
        if ctx.get("country_code"):
            lines.append(f"country_code: {ctx['country_code']}")
        if ctx.get("precision"):
            lines.append(f"precision: {ctx['precision']}")
        if ctx.get("poi_label"):
            lines.append(f"poi_label: {ctx['poi_label']}")
        if ctx.get("road"):
            lines.append(f"road: {ctx['road']}")
        if ctx.get("house_number"):
            lines.append(f"house_number: {ctx['house_number']}")
        if ctx.get("tz"):
            lines.append(f"timezone: {ctx['tz']}")
        if ctx.get("locale"):
            lines.append(f"locale: {ctx['locale']}")
        if ctx.get("heading_cardinal"):
            lines.append(f"heading: {ctx['heading_cardinal']}")
        elif ctx.get("heading_deg") is not None:
            lines.append(f"heading_deg: {ctx['heading_deg']}")
        if ctx.get("accuracy_m") is not None:
            lines.append(f"accuracy_m: {ctx['accuracy_m']}")
        if ctx.get("lat") is not None and ctx.get("lon") is not None:
            lines.append(f"coordinates: {ctx['lat']},{ctx['lon']}")

        metadata = {
            "source": "environment_context_service",
            "freshness": "latest_available" if ctx else "missing",
            "has_location": self._has_location(ctx),
            "has_timezone": bool(ctx.get("tz")),
            "has_locale": bool(ctx.get("locale")),
        }

        return EnvironmentInjection(
            summary_text="\n".join(lines),
            raw_context=ctx,
            metadata=metadata,
        )

    @staticmethod
    def _has_location(ctx: Dict[str, Any]) -> bool:
        return ctx.get("lat") is not None and ctx.get("lon") is not None
