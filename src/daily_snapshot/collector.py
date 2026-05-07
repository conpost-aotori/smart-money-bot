"""Daily snapshot data collection — Hyperliquid edition.

A single ``POST /info`` call to ``metaAndAssetCtxs`` yields every active
perp's mark/prev_day price, OI, funding, and 24h notional volume. From
that we derive three views:

- ``top_buys``       : top movers up (24h)        → "Smart Money buying"
- ``top_sells``      : top movers down (24h)      → "Smart Money selling"
- ``sectors_heating``: 24h volume aggregated by sector tag

The ``SnapshotRow`` shape is reused from the original Polymarket template
so the renderer / formatter / DB schema can stay unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from ..hyperliquid_client import HLAssetRow, HyperliquidClient

log = logging.getLogger(__name__)


@dataclass
class SnapshotRow:
    """A single row rendered in one of the snapshot's sections.

    Field semantics for the Hyperliquid bot:
        market_id      : coin ticker, upper-case (e.g. ``"BTC"``)
        slug           : coin ticker, lower-case (used as the alias key)
        question       : human-readable summary, e.g. ``"BTC OI $42M funding +1.2%/yr"``
        yes_price      : mark price in USD (rendered as the left numeric column)
        one_day_change : fractional 24h price change (e.g. 0.052 = +5.2%)
        volume_24h_usd : 24h notional volume in USD
        tag_slugs      : ``[sector_label]`` (one element)
        category       : the sector label (mirror of ``tag_slugs[0]``)
        event_slug     : unused — kept for renderer compatibility
        event_title    : unused
    """
    market_id: str
    slug: str | None
    question: str
    yes_price: float | None
    one_day_change: float | None
    volume_24h_usd: float
    tag_slugs: list[str]
    category: str | None
    event_slug: str | None = None
    event_title: str | None = None


def _classify_sector(coin: str, sector_map: dict[str, list[str]]) -> str:
    """First-match lookup of ``coin`` in any sector list, else the catch-all."""
    coin_u = coin.upper()
    catch_all = None
    for label, members in sector_map.items():
        if not members:
            catch_all = label
            continue
        if coin_u in {m.upper() for m in members}:
            return label
    return catch_all or "Other"


def _row_from_hl(row: HLAssetRow, sector_map: dict[str, list[str]]) -> SnapshotRow:
    sector = _classify_sector(row.coin, sector_map)
    funding_pct_per_year = row.funding * 24 * 365 * 100  # rough APR
    summary = (
        f"{row.coin} OI ${row.open_interest_usd / 1e6:.1f}M  "
        f"funding {funding_pct_per_year:+.1f}%/yr"
    )
    return SnapshotRow(
        market_id=row.coin.upper(),
        slug=row.coin.lower(),
        question=summary,
        yes_price=row.mark_px,
        one_day_change=row.change_24h,
        volume_24h_usd=row.day_ntl_vlm,
        tag_slugs=[sector],
        category=sector,
    )


def collect_snapshot(
    client: HyperliquidClient,
    *,
    fetch_limit: int = 250,
    min_volume_24h_usd: float = 5_000_000,
    sector_map: dict[str, list[str]],
) -> list[SnapshotRow]:
    """Fetch the perp universe and return rows above the volume threshold."""
    raw = client.meta_and_asset_ctxs()
    rows: list[SnapshotRow] = []
    for hl in raw[:fetch_limit]:
        if hl.day_ntl_vlm < min_volume_24h_usd:
            continue
        if hl.change_24h is None:
            continue
        rows.append(_row_from_hl(hl, sector_map))

    log.info(
        "snapshot universe: %d perps after volume filter (from %d raw, threshold $%.0f)",
        len(rows),
        len(raw),
        min_volume_24h_usd,
    )
    return rows


# ---- views ----


def top_buys(rows: list[SnapshotRow], *, n: int = 3) -> list[SnapshotRow]:
    """Top n coins by positive 24h price change.

    Interpretation: where price rallied → net buying pressure → "Smart
    Money buying" (loosely, since HL is dominated by leveraged traders).
    Funding is rendered alongside in the row label so a reader can see if
    the rally was driven by longs paying premium (bullish conviction).
    """
    eligible = [r for r in rows if (r.one_day_change or 0) > 0]
    eligible.sort(key=lambda r: r.one_day_change or 0.0, reverse=True)
    return eligible[:n]


def top_sells(rows: list[SnapshotRow], *, n: int = 3) -> list[SnapshotRow]:
    """Top n coins by negative 24h price change."""
    eligible = [r for r in rows if (r.one_day_change or 0) < 0]
    eligible.sort(key=lambda r: r.one_day_change or 0.0)
    return eligible[:n]


def sectors_heating(rows: list[SnapshotRow], *, n: int = 3) -> list[SnapshotRow]:
    """Aggregate 24h volume by sector and return top ``n`` sectors as
    pseudo-rows. ``yes_price`` is None (no per-coin price), and
    ``one_day_change`` is the volume-weighted average 24h move.
    """
    by_sector: dict[str, list[SnapshotRow]] = {}
    for r in rows:
        by_sector.setdefault(r.category or "Other", []).append(r)

    out: list[SnapshotRow] = []
    for sector, members in by_sector.items():
        total_vol = sum(m.volume_24h_usd for m in members)
        if total_vol <= 0:
            continue
        weighted_change = (
            sum((m.one_day_change or 0.0) * m.volume_24h_usd for m in members)
            / total_vol
        )
        # Top coin in the sector by volume — used as a tooltip-ish hint.
        leader = max(members, key=lambda m: m.volume_24h_usd)
        out.append(
            SnapshotRow(
                market_id=f"sector:{sector}",
                slug=f"sector:{sector.lower().replace(' ', '-')}",
                question=(
                    f"{sector} — vol ${total_vol / 1e6:.0f}M ({len(members)} coins, "
                    f"top {leader.market_id})"
                ),
                yes_price=None,
                one_day_change=weighted_change,
                volume_24h_usd=total_vol,
                tag_slugs=[sector],
                category=sector,
            )
        )

    out.sort(key=lambda r: r.volume_24h_usd, reverse=True)
    return out[:n]


def coins_for_translation(rows: Iterable[SnapshotRow]) -> list[SnapshotRow]:
    """Filter out sector-aggregate rows; only per-coin rows get JP labels."""
    return [r for r in rows if not (r.market_id or "").startswith("sector:")]
