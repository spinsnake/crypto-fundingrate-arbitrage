# Crypto Spread Arbitrage (Asterdex ↔ Hyperliquid)

## What it does
- Scans funding rates on Asterdex and Hyperliquid, normalizes to 8h, filters by volume/delist/price-edge, and ranks spreads (`src/strategies/funding_arb.py`).
- Live loop (`main_bot.py`) fetches data, sends alerts to Telegram/Discord, shows live PnL for watchlist legs, and can auto-close based on return or leg drawdown.
- Adapters wrap each exchange: `src/adapters/asterdex.py` (Binance-style REST) and `src/adapters/hyperliquid.py` (Hyperliquid /info + SDK if available).
- `ExecutionManager` (`src/core/execution_manager.py`) applies slippage buffers, places paired orders, and logs to `logs/trade_log.csv`.
- `funding_scanner.py` is a quick one-off scan that outputs CSV of opportunities.

## Configure
Edit `src/config.py`:
- Percent scales use integer percent values (e.g., 4.0 = 4%, 0.2 = 0.2%):
  - `MIN_MONTHLY_RETURN`, `TARGET_MONTHLY_RETURN`
  - `MIN_SPREAD_PER_ROUND`, `ESTIMATED_FEE_PER_ROTATION`
  - `ASTERDEX_TAKER_FEE`, `HYPERLIQUID_TAKER_FEE`
  - `MIN_PRICE_SPREAD_PCT`
- Execution:
  - `ENABLE_TRADING`: `False` for alert-only, `True` to allow auto-close logic.
  - `AUTO_CLOSE_RET_PCT`: auto-close if portfolio return ≥ this percent.
  - `AUTO_CLOSE_SIDE_DD_PCT`: auto-close if any leg drawdown ≤ -this percent.
  - `POLL_INTERVAL`: seconds between scans.
- Filters: enable/disable volume, delist, price-edge checks; set `WATCHLIST` symbols to always monitor.
- Costs/slippage: `SLIPPAGE_BPS`, `REBALANCE_FIXED_COST_USDC`, `DEFAULT_LEVERAGE`.
- Notifications: set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DISCORD_WEBHOOK_URL`.

Environment variables (`.env`):
- `asterdex_api_key`, `asterdex_api_secret`
- `hyperliquid_private_key`, `hyperliquid_wallet_address`
- (Optional) override config tokens/chat IDs here if you prefer

## Install
```
pip install -r requirements.txt
```

## Run
- Live loop (alerts/auto-close): `python main_bot.py`
  - Prints scan summary, sends alerts, and evaluates auto-close triggers.
  - Trades are mocked if keys are missing; ensure `ENABLE_TRADING` is set consciously.
- Quick scan (CSV): `python funding_scanner.py`
  - Writes `funding_opportunities.csv` with top spreads.
- Logs: trades append to `logs/trade_log.csv`; live PnL uses that log to match open positions.

## Key logic notes
- Strategy normalizes funding to 8h, subtracts fee+slippage (using config percents / 100 in code) and enforces:
  - volume/delist filters (unless watchlist),
  - minimum price-edge between marks,
  - break-even horizon (`MAX_BREAK_EVEN_ROUNDS`) before accepting a signal.
- Auto-close triggers in `main_bot.py`:
  - Portfolio return ≥ `AUTO_CLOSE_RET_PCT`.
  - Any leg drawdown ≤ -`AUTO_CLOSE_SIDE_DD_PCT`.
- Adapters provide balances, positions, funding history, fees, VWAP fills; fall back to mock behavior without credentials.

## Safety checklist
- Keep `ENABLE_TRADING = False` until keys and size controls are confirmed.
- Replace sample Discord webhook and set your own Telegram bot/chat IDs.
- Confirm percent values after the scale change: numbers are now literal percents.
