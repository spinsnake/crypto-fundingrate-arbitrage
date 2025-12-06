# Crypto Funding Rate Arbitrage Scanner Task List

- [x] **Planning & Setup**
    - [x] Define requirements (Funding Rate Arb, Mid-caps, Risk 6/10) <!-- id: 0 -->
    - [x] Verify API connectivity for Asterdex & Hyperliquid <!-- id: 8 -->
    - [x] Create project structure & Install dependencies <!-- id: 1 -->

- [x] **Phase 1: POC & Data Validation**
    - [x] Implement `poc_connectivity.py` <!-- id: 11 -->
    - [x] Implement `funding_scanner.py` <!-- id: 18 -->
    - [x] Validate data accuracy (Found APT > 10%) <!-- id: 12 -->

- [x] **Phase 2: Backtesting Engine**
    - [x] Implement `backtest_engine.py` <!-- id: 13 -->
    - [x] Run simulation on APT, ATOM, DOT <!-- id: 14 -->
    - [x] Analyze results (Confirmed Active Rotation strategy needed) <!-- id: 19 -->

- [x] **Phase 3: Production Architecture**
    - [x] **Structure**: Setup `src/` (Core, Strategy, Notification, Execution) <!-- id: 15 -->
    - [x] **Core**: Implement Unified Exchange Interface (Adapter Pattern) <!-- id: 16 -->
    - [x] **Strategy**: Port scanning logic to `ArbitrageStrategy` class <!-- id: 17 -->
    - [x] **Notification**: Implement Telegram/Line Alert system <!-- id: 20 -->
    - [x] **Execution**: Implement `OrderManager` (Start with Alert-only mode) <!-- id: 21 -->
    - [x] **Main**: Create `main_bot.py` loop <!-- id: 22 -->

- [ ] **Verification**
    - [ ] Run full system in "Alert Mode" for 24h <!-- id: 6 -->
