# Implementation Plan - Phase 3: Production Architecture (Modular & Flexible)

# Goal Description
Build a highly modular trading system where Exchanges and Strategies are plug-and-play.
**Key Requirement:** Standardized Adapters for both Exchanges and Strategies.

## Architecture Overview
```
src/
├── core/
│   ├── interfaces.py   # Abstract Base Classes (The Standard)
│   ├── models.py       # Data Classes (Signal, Order, Ticker)
│   └── engine.py       # The Orchestrator (Runs the loop)
├── adapters/           # Exchange Implementations
│   ├── asterdex.py     # Implements ExchangeInterface
│   └── hyperliquid.py  # Implements ExchangeInterface
├── strategies/         # Strategy Implementations
│   └── funding_arb.py  # Implements StrategyInterface
├── notification/
│   └── telegram.py
└── main.py
```

## Proposed Changes

### 1. The Standards (`src/core/interfaces.py`)
#### ExchangeInterface
- `get_market_data(symbol: str) -> MarketData`
- `get_all_funding_rates() -> Dict[str, FundingRate]`
- `get_balance() -> Balance`
- `place_order(order: Order) -> OrderResult`

#### StrategyInterface
- `analyze(market_data: Dict) -> List[Signal]`
- **Benefit:** You can swap `FundingArb` with `TriangularArb` just by changing one line in config.

### 2. Data Models (`src/core/models.py`)
- Standardize data passing using `dataclasses`.
- `Signal`: {symbol, side, quantity, reason}
- `Order`: {symbol, side, type, price, quantity}

### 3. Implementations
- **Adapters:** Port existing logic to new classes.
- **Strategy:** Move logic from `funding_scanner.py` to `FundingArbitrageStrategy`.

## Verification Plan
- **Interface Check:** Ensure all implementations strictly follow the base class.
- **Mock Test:** Run `FundingArbitrageStrategy` with fake data to verify signal generation.
