"""Format the snapshot for Discord (rich embed) and X (280-char tweet)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .collector import SnapshotRow

JST = ZoneInfo("Asia/Tokyo")
DISCORD_COLOR_DEFAULT = 0x5865F2


def _label(row: SnapshotRow, aliases: dict[str, str], max_chars: int = 40) -> str:
    if row.slug and row.slug in aliases:
        return aliases[row.slug]
    if (row.market_id or "").startswith("sector:") and row.category:
        return row.category
    base = row.market_id or row.question or "(unknown)"
    return base if len(base) <= max_chars else base[: max_chars - 1].rstrip() + "…"


def _fmt_price(row: SnapshotRow) -> str:
    if row.yes_price is not None and row.yes_price > 0:
        p = row.yes_price
        if p >= 1000:
            return f"${p:,.0f}"
        if p >= 1:
            return f"${p:.2f}"
        return f"${p:.4f}"
    v = row.volume_24h_usd
    if v >= 1e9:
        return f"${v / 1e9:.1f}B vol"
    if v >= 1e6:
        return f"${v / 1e6:.0f}M vol"
    return f"${v / 1e3:.0f}K vol"


def _fmt_delta(d: float | None) -> str:
    if d is None:
        return "—"
    pct = d * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


# ---------- Discord ----------


def build_discord_embed(
    *,
    snapshot_date: datetime,
    top_buys: list[SnapshotRow],
    top_sells: list[SnapshotRow],
    sectors: list[SnapshotRow],
    aliases: dict[str, str],
    color: int = DISCORD_COLOR_DEFAULT,
    footer_text: str = "Auto-generated · Data via Hyperliquid public API",
) -> dict[str, Any]:
    date_str = snapshot_date.astimezone(JST).strftime("%Y-%m-%d")
    fields: list[dict[str, Any]] = []

    def block(emoji: str, name: str, rows: list[SnapshotRow]) -> dict[str, Any] | None:
        if not rows:
            return None
        lines = [
            f"• {_label(r, aliases)}  **{_fmt_price(r)}**  {_fmt_delta(r.one_day_change)}"
            for r in rows
        ]
        return {"name": f"{emoji} {name}", "value": "\n".join(lines), "inline": False}

    for b in (
        block("🟢", "Top buys (24h)", top_buys),
        block("🔴", "Top sells (24h)", top_sells),
        block("🔥", "Sectors heating", sectors),
    ):
        if b is not None:
            fields.append(b)

    return {
        "title": "📊 Smart Money Daily Snapshot",
        "description": f"**{date_str} (JST)**",
        "color": color,
        "fields": fields,
        "footer": {"text": footer_text},
        "timestamp": snapshot_date.astimezone(JST).isoformat(),
    }


# ---------- X (Twitter) ----------

X_MAX_CHARS = 280


def build_tweet(
    *,
    snapshot_date: datetime,
    top_buys: list[SnapshotRow],
    top_sells: list[SnapshotRow],
    aliases: dict[str, str],
    hashtags: str = "#Hyperliquid #SmartMoney #BTC #ETH",
) -> str:
    """Compress the snapshot into a single 280-char tweet.

    Strategy: header + top buys + top sells + hashtags. Progressive
    shrink: drop label aliases first, then drop the bottom row from each
    section.
    """
    date_str = snapshot_date.astimezone(JST).strftime("%m/%d JST")
    header = f"📊 Smart Money Daily {date_str}"

    def render(buys: list[SnapshotRow], sells: list[SnapshotRow], label_max: int) -> str:
        parts = [header]
        if buys:
            parts.append("🟢 Top buys (24h)")
            parts.extend(
                f"• {_label(r, aliases, max_chars=label_max)} {_fmt_delta(r.one_day_change)}"
                for r in buys
            )
        if sells:
            parts.append("🔴 Top sells (24h)")
            parts.extend(
                f"• {_label(r, aliases, max_chars=label_max)} {_fmt_delta(r.one_day_change)}"
                for r in sells
            )
        if hashtags:
            parts.append(hashtags)
        return "\n".join(parts)

    for label_max in (32, 24, 20, 16, 12):
        text = render(top_buys, top_sells, label_max)
        if len(text) <= X_MAX_CHARS:
            return text

    # Drop one row from each side if still too long.
    for label_max in (24, 20, 16, 12):
        text = render(top_buys[:-1] or top_buys, top_sells[:-1] or top_sells, label_max)
        if len(text) <= X_MAX_CHARS:
            return text

    return render(top_buys[:1], top_sells[:1], 12)[:X_MAX_CHARS]
