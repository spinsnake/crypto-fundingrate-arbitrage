"""Helpers for dealing with exchange tick sizes (placeholder)."""

from __future__ import annotations

from typing import Optional


def quantize(price: float, tick_size: Optional[float]) -> float:
    if not tick_size:
        return price
    ticks = round(price / tick_size)
    return ticks * tick_size


__all__ = ["quantize"]
