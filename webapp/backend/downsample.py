"""Downsample per-point streams before sending them to the browser.

Charts don't need 2000+ points; index-aligned decimation keeps every channel
(time/distance/latlng/hr/…) in sync so a given chart x-index maps to the same
moment across series.
"""
from __future__ import annotations


def decimate(values: list, target: int = 1200) -> list:
    """Return at most ``target`` items, evenly strided across ``values``."""
    n = len(values)
    if target <= 0 or n <= target:
        return values
    return [values[int(i * n / target)] for i in range(target)]


def decimate_streams(streams: dict, target: int = 1200) -> dict:
    """Decimate every stream's ``data`` array by a shared index map.

    Streams shorter than the reference length (or non-list) are passed through
    unchanged. Channels are decimated in lockstep so latlng[i] still lines up
    with time[i], hr[i], etc.
    """
    if not streams:
        return {}
    lengths = [
        len(v["data"]) for v in streams.values()
        if isinstance(v, dict) and isinstance(v.get("data"), list)
    ]
    n = max(lengths) if lengths else 0
    if n <= target:
        return streams

    idxs = [int(i * n / target) for i in range(target)]
    out: dict = {}
    for key, obj in streams.items():
        data = obj.get("data") if isinstance(obj, dict) else None
        if isinstance(data, list) and len(data) == n:
            out[key] = {
                **obj,
                "data": [data[i] for i in idxs],
                "original_size": n,
                "resolution": "low",
            }
        else:
            out[key] = obj
    return out
