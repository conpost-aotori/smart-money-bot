"""Render the Smart Money daily snapshot as a 1200×720 PNG (dark theme).

Layout:
    ┌────────────────────────────────────────────────────────────┐
    │  📊  Smart Money Daily Snapshot                            │
    │      2026-05-07 (JST)                                      │
    ├────────────────────────────────────────────────────────────┤
    │  🟢  Top buys (24h)                                        │
    │      • BTC                  $108,420   +3.1%               │
    │      ...                                                   │
    │  🔴  Top sells (24h)                                       │
    │      ...                                                   │
    │  🔥  Sectors heating                                       │
    │      • L1 majors            $12.4B vol   +1.8%             │
    │      ...                                                   │
    ├────────────────────────────────────────────────────────────┤
    │  Auto-generated · Data via Hyperliquid public API          │
    └────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pilmoji import Pilmoji

from .collector import SnapshotRow

log = logging.getLogger(__name__)

W, H = 1200, 720
PAD = 50

# Dark palette
BG = (14, 16, 20)
CARD = (26, 29, 36)
DIVIDER = (48, 54, 61)
TEXT = (230, 237, 243)
DIM = (139, 148, 158)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
ACCENT = (139, 148, 230)

_JP_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/YuGothB.ttc", 0),
    ("C:/Windows/Fonts/YuGothM.ttc", 0),
    ("C:/Windows/Fonts/meiryob.ttc", 0),
    ("C:/Windows/Fonts/meiryo.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
]
_MONO_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/consolab.ttf", 0),
    ("C:/Windows/Fonts/consola.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf", 0),
]


def _load_font(candidates: list[tuple[str, int]], size: int) -> ImageFont.FreeTypeFont:
    for path, index in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size, index=index)
            except OSError as exc:
                log.debug("font %s failed: %s", path, exc)
                continue
    raise RuntimeError(
        "No usable font found. Install fonts-noto-cjk on Linux or use Windows."
    )


def _fmt_price_or_volume(row: SnapshotRow) -> str:
    """Left numeric column.

    For per-coin rows we show the mark price (``yes_price``). For sector
    rows ``yes_price`` is None, so we fall back to the aggregated 24h
    volume rendered in human units ($M / $B).
    """
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


def _fmt_delta(d: float | None) -> tuple[str, tuple[int, int, int]]:
    if d is None:
        return "—", DIM
    pct = d * 100
    sign = "+" if pct >= 0 else ""
    color = GREEN if pct >= 0 else RED
    return f"{sign}{pct:.1f}%", color


def _label(row: SnapshotRow, aliases: dict[str, str], max_chars: int = 30) -> str:
    if row.slug and row.slug in aliases:
        return aliases[row.slug]
    if (row.market_id or "").startswith("sector:") and row.category:
        return row.category
    base = row.market_id or row.question or "(unknown)"
    return base if len(base) <= max_chars else base[: max_chars - 1].rstrip() + "…"


def render_snapshot_png(
    *,
    snapshot_date: datetime,
    top_buys: list[SnapshotRow],
    top_sells: list[SnapshotRow],
    sectors: list[SnapshotRow],
    aliases: dict[str, str],
) -> bytes:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(_JP_FONT_CANDIDATES, 36)
    date_font = _load_font(_JP_FONT_CANDIDATES, 22)
    section_font = _load_font(_JP_FONT_CANDIDATES, 24)
    label_font = _load_font(_JP_FONT_CANDIDATES, 20)
    mono_font = _load_font(_MONO_FONT_CANDIDATES, 22)
    footer_font = _load_font(_JP_FONT_CANDIDATES, 16)

    with Pilmoji(img) as pilmoji:
        date_str = snapshot_date.strftime("%Y-%m-%d")
        pilmoji.text((PAD, 36), "📊  Smart Money Daily Snapshot",
                     font=title_font, fill=TEXT)
        draw.text((PAD, 84), f"{date_str} (JST)", font=date_font, fill=DIM)
        draw.line([(PAD, 130), (W - PAD, 130)], fill=DIVIDER, width=2)

        sections: list[tuple[str, str, list[SnapshotRow]]] = [
            ("🟢", "Top buys (24h)", top_buys),
            ("🔴", "Top sells (24h)", top_sells),
            ("🔥", "Sectors heating", sectors),
        ]

        y = 160
        for emoji, title, rows in sections:
            pilmoji.text((PAD, y), f"{emoji}  {title}",
                         font=section_font, fill=TEXT)
            y += 42

            for r in rows:
                label = _label(r, aliases)
                price_text = _fmt_price_or_volume(r)
                delta_text, delta_color = _fmt_delta(r.one_day_change)

                draw.ellipse([(PAD + 12, y + 11), (PAD + 18, y + 17)], fill=DIM)
                draw.text((PAD + 32, y), label, font=label_font, fill=TEXT)

                delta_right = 1080
                price_right = 950
                delta_w = int(mono_font.getlength(delta_text))
                price_w = int(mono_font.getlength(price_text))
                draw.text((price_right - price_w, y), price_text,
                          font=mono_font, fill=TEXT)
                draw.text((delta_right - delta_w, y), delta_text,
                          font=mono_font, fill=delta_color)

                y += 32

            y += 18

        footer_y = H - 40
        draw.line([(PAD, footer_y - 14), (W - PAD, footer_y - 14)],
                  fill=DIVIDER, width=1)
        draw.text((PAD, footer_y),
                  "Auto-generated · Data via Hyperliquid public API",
                  font=footer_font, fill=DIM)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
