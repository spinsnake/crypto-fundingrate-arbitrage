import csv
import os
import time

from src.adapters.asterdex import AsterdexAdapter
from src.adapters.hyperliquid import HyperliquidAdapter
from src.adapters.lighter import LighterAdapter
from src.config import POLL_INTERVAL


LOG_PATH = os.path.join("logs", "funding_rate_history.csv")
MAX_ROWS_PER_KEY = 72


def _append_row(
    now_ms: int,
    exchange_name: str,
    symbol: str,
    interval: float,
    rate_raw: float,
    rate_per_hour: float,
    bucket: int,
) -> None:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    file_exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if not file_exists:
            writer.writerow(
                [
                    "timestamp_ms",
                    "exchange",
                    "symbol",
                    "interval_h",
                    "rate_raw",
                    "rate_per_hour",
                    "hour_bucket",
                ]
            )
        writer.writerow(
            [
                now_ms,
                exchange_name,
                symbol,
                f"{interval:.6f}",
                f"{rate_raw:.10f}",
                f"{rate_per_hour:.10f}",
                bucket,
            ]
        )


def _load_last_buckets(csv_path: str) -> dict:
    if not os.path.exists(csv_path):
        return {}
    last_bucket_by_key = {}
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            exchange = (row.get("exchange") or "").strip()
            symbol = (row.get("symbol") or "").strip()
            if not exchange or not symbol:
                continue
            try:
                bucket = int(row.get("hour_bucket") or 0)
            except Exception:
                continue
            key = (exchange, symbol)
            prev = last_bucket_by_key.get(key)
            if prev is None or bucket > prev:
                last_bucket_by_key[key] = bucket
    return last_bucket_by_key


def _trim_csv(csv_path: str, max_rows_per_key: int) -> None:
    if not os.path.exists(csv_path):
        return
    rows_by_key = {}
    fieldnames = None
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        for row in reader:
            exchange = (row.get("exchange") or "").strip()
            symbol = (row.get("symbol") or "").strip()
            if not exchange or not symbol:
                continue
            rows_by_key.setdefault((exchange, symbol), []).append(row)

    if not fieldnames:
        fieldnames = [
            "timestamp_ms",
            "exchange",
            "symbol",
            "interval_h",
            "rate_raw",
            "rate_per_hour",
            "hour_bucket",
        ]

    trimmed_rows = []
    for key, rows in rows_by_key.items():
        rows.sort(
            key=lambda item: (
                int(item.get("hour_bucket") or 0),
                int(item.get("timestamp_ms") or 0),
            )
        )
        if len(rows) > max_rows_per_key:
            rows = rows[-max_rows_per_key:]
        trimmed_rows.extend(rows)

    trimmed_rows.sort(
        key=lambda item: (
            int(item.get("hour_bucket") or 0),
            item.get("exchange", ""),
            item.get("symbol", ""),
        )
    )

    temp_path = f"{csv_path}.tmp"
    with open(temp_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(trimmed_rows)
    os.replace(temp_path, csv_path)


def main() -> None:
    exchanges = [AsterdexAdapter(), HyperliquidAdapter(), LighterAdapter()]
    last_bucket_by_key = _load_last_buckets(LOG_PATH)
    last_trim_bucket = None
    poll_seconds = max(10, int(POLL_INTERVAL))

    print("--- Funding Rate Logger ---")
    print(f"Logging to {LOG_PATH}")
    print(f"Polling every {poll_seconds}s")

    while True:
        now_ms = int(time.time() * 1000)
        bucket = now_ms // 3600000
        wrote_any = False
        for exchange in exchanges:
            name = exchange.get_name()
            try:
                rates = exchange.get_all_funding_rates()
            except Exception as exc:
                print(f"[{name}] fetch error: {exc}")
                continue
            print(f"[{name}] Got {len(rates)} rates")
            for symbol, rate_obj in rates.items():
                interval = getattr(rate_obj, "funding_interval_hours", 1) or 1
                rate_raw = float(getattr(rate_obj, "rate", 0.0) or 0.0)
                rate_per_hour = rate_raw / interval if interval else rate_raw
                key = (name, symbol)
                if last_bucket_by_key.get(key) == bucket:
                    continue
                last_bucket_by_key[key] = bucket
                _append_row(
                    now_ms,
                    name,
                    symbol,
                    interval,
                    rate_raw,
                    rate_per_hour,
                    bucket,
                )
                wrote_any = True
        if wrote_any and bucket != last_trim_bucket:
            _trim_csv(LOG_PATH, MAX_ROWS_PER_KEY)
            last_trim_bucket = bucket
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
