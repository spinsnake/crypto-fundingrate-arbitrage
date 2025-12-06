# Final Assessment: Funding Rate Arbitrage (Asterdex vs Hyperliquid)

## 1. Feasibility of 4% Monthly Profit
**Verdict: Possible, but requires "Active Rotation" & "Sniping".**

*   **Passive Strategy (Buy & Hold):** **FAILED.**
    *   Holding a single pair (like APT) for 30 days yields only ~1.5% - 2.5%.
    *   Major coins (ATOM, DOT) yield < 1%.
    *   **Conclusion:** You will NOT hit 4% by just holding.

*   **Active Strategy (Sniper):** **POSSIBLE.**
    *   **The Math:** To get 4% month, you need ~0.13% per day.
    *   **The Opportunity:** We saw APT spread at ~10% APY (0.027% per day). This is still below target if held passively.
    *   **The "Spike" Factor:** Funding rates are volatile. You make your money by entering when the rate spikes to **0.05% - 0.1% per round** (often just before payout).
    *   **Frequency:** You need to catch about **4-5 high-yield rounds** per month (Sniping) to hit the 4% target.

## 2. Risk Assessment (Target: Level 6/10)
**Current Rating: Level 6.5 / 10** (Slightly higher than target)

### Why it fits Level 6 (Manageable):
*   **Delta Neutral:** You are hedged. Price crashes don't kill you directly.
*   **Mid-Cap Focus:** We avoid small-cap liquidity traps. APT/ATOM have decent volume.

### Why it's not lower (The Hidden Risks):
1.  **Rebalancing Risk (Rotation Cost):**
    *   To hit 4%, you must switch pairs often.
    *   Each switch costs ~0.2% in fees. If you switch 5 times, you lose 1% of your profit.
2.  **Execution Lag:**
    *   When a spike happens (e.g., APT at 10%), many bots might rush in.
    *   If you are slow, the spread might vanish before you fill both legs.
3.  **Liquidation Wicks:**
    *   Even if hedged, a flash crash on one exchange can liquidate that leg before the other leg profits. (Requires monitoring).

## 3. Strategic Recommendation
To achieve **4% at Risk Level 6**, you must upgrade from a "Manual Trader" to a "Semi-Automated System":

1.  **Alert System (Crucial):**
    *   You cannot stare at the screen 24/7.
    *   The bot must alert you: *"APT Spread is 10%! Action required."*
2.  **Execution Helper:**
    *   One-click button to "Open Long A / Short B" simultaneously to minimize leg risk.

## Final Verdict: Can we hit 4%?
**YES**, but it is **Hard Work**.
*   ❌ **Lazy Mode:** Expect 1-2% / month.
*   ✅ **Sniper Mode:** Expect 4-6% / month (if you catch the spikes).

**Recommendation:** Start with **$500**. Aim for **2% first**. If you master the "Sniping" technique (entering 30 mins before payout), then scale up to aim for 4%.
