"""Hyperliquid public-API client (no auth required).

Uses the single ``POST /info`` endpoint that handles all read queries by
``type`` discriminator. We only need ``metaAndAssetCtxs`` for the daily
snapshot — it returns the universe (asset metadata) and per-asset context
(price, OI, funding, 24h notional volume) in one call.

Reference: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)


@dataclass
class HLAssetRow:
    """One row from a meta+ctx join, with all numeric fields coerced to float.

    Names mirror Hyperliquid's payload: ``coin`` is the perp ticker (e.g.
    ``"BTC"``, ``"@1"`` for spot LP indexes), ``mark_px`` is the current
    mark price in USD, ``prev_day_px`` is the price 24h ago, ``funding``
    is the per-hour funding rate (typically ~1e-5 to ~1e-4), and the
    notional volumes are USD over the trailing 24h.
    """
    coin: str
    mark_px: float
    prev_day_px: float
    funding: float
    open_interest: float  # in base units
    day_ntl_vlm: float    # 24h notional in USD
    day_base_vlm: float   # 24h volume in base
    sz_decimals: int

    @property
    def change_24h(self) -> float | None:
        """Fractional 24h price change, e.g. ``0.052 = +5.2%``."""
        if self.prev_day_px <= 0 or self.mark_px <= 0:
            return None
        return (self.mark_px - self.prev_day_px) / self.prev_day_px

    @property
    def open_interest_usd(self) -> float:
        return self.open_interest * self.mark_px


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class HyperliquidError(RuntimeError):
    pass


class HyperliquidClient:
    def __init__(
        self,
        *,
        info_base: str = "https://api.hyperliquid.xyz",
        user_agent: str = "smart-money-bot/0.1",
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Content-Type": "application/json"},
        )
        self._base = info_base.rstrip("/")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "HyperliquidClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _post_info(self, payload: dict[str, Any]) -> Any:
        url = f"{self._base}/info"
        log.debug("POST %s payload=%s", url, payload)
        resp = self._client.post(url, json=payload)
        if resp.status_code >= 400:
            log.warning("HL %s -> %s: %s", url, resp.status_code, resp.text[:300])
            resp.raise_for_status()
        return resp.json()

    def meta_and_asset_ctxs(self) -> list[HLAssetRow]:
        """Return one row per perp coin with all the metrics needed.

        Hyperliquid returns a 2-element list: ``[meta, ctxs]`` where
        ``meta["universe"]`` is the asset list (``name``, ``szDecimals``)
        and ``ctxs`` is a parallel list of context dicts.
        """
        data = self._post_info({"type": "metaAndAssetCtxs"})
        if not isinstance(data, list) or len(data) != 2:
            raise HyperliquidError(
                f"unexpected metaAndAssetCtxs shape: {type(data).__name__}"
            )
        meta, ctxs = data
        universe = meta.get("universe") or []
        rows: list[HLAssetRow] = []
        for asset, ctx in zip(universe, ctxs):
            coin = asset.get("name") or ""
            if not coin or coin.startswith("@"):
                # ``@N`` are spot LP indexes — exclude from a perp snapshot.
                continue
            rows.append(
                HLAssetRow(
                    coin=coin,
                    mark_px=_to_float(ctx.get("markPx")),
                    prev_day_px=_to_float(ctx.get("prevDayPx")),
                    funding=_to_float(ctx.get("funding")),
                    open_interest=_to_float(ctx.get("openInterest")),
                    day_ntl_vlm=_to_float(ctx.get("dayNtlVlm")),
                    day_base_vlm=_to_float(ctx.get("dayBaseVlm")),
                    sz_decimals=int(asset.get("szDecimals") or 0),
                )
            )
        return rows
