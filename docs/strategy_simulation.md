# Funding Rate Arbitrage: Logic & Simulation

## 1. Core Logic (The "Short High, Long Low" Rule)
To make profit, you must be on the **Receiving** side of the Funding Rate.

*   **Positive Funding Rate (+):** Longs PAY Shorts. -> **You want to Short.**
*   **Negative Funding Rate (-):** Shorts PAY Longs. -> **You want to Long.**

**The Winning Formula:**
1.  **Exchange A (High Rate +0.05%):** Open **Short** (Receive 0.05%)
2.  **Exchange B (Low Rate +0.01%):** Open **Long** (Pay 0.01%)
3.  **Net Profit:** 0.05% - 0.01% = **+0.04% per round (8 hours)**

---

## 2. Simulation: XRP Case Study
**Scenario:**
*   **Capital:** $1,000
*   **Position Split:** $500 Long (Asterdex) / $500 Short (Hyperliquid)
*   **Leverage:** 1x (Effective)
*   **Rates:**
    *   Hyperliquid: **+0.05%** (We Short here to Receive)
    *   Asterdex: **+0.01%** (We Long here and Pay)

### Cash Flow Calculation (Per 8 Hours)
1.  **Hyperliquid (Short $500):** Receive $500 * 0.05% = **+$0.25**
2.  **Asterdex (Long $500):** Pay $500 * 0.01% = **-$0.05**
3.  **Net Profit per Round:** $0.20

### Daily Projection (3 Rounds/Day)
*   **Daily Profit:** $0.20 * 3 = **$0.60**
*   **Daily ROI:** $0.60 / $1,000 = **0.06%**

### Monthly Projection (30 Days)
*   **Gross Profit:** $0.60 * 30 = **$18.00**
*   **Gross ROI:** **1.8%**

---

## 3. Fee Impact & Time to Target
To achieve **4% Net Profit ($40)**, we must account for trading fees (Open + Close).

**Estimated Fees (Taker 0.05% x 4 legs):**
*   Open Long + Open Short + Close Long + Close Short
*   Total Volume Traded: $1,000 (Open) + $1,000 (Close) = $2,000
*   Total Fees: $2,000 * 0.05% = **$1.00** (approx)

**Target Calculation:**
*   Target Net Profit: **$40.00** (4%)
*   Required Gross Profit: $40.00 + $1.00 (Fees) = **$41.00**
*   Daily Profit: **$0.60**

**Time Required:**
*   $41.00 / $0.60 = **68.3 Days**

### Conclusion for this Scenario
With a spread of **0.04%**, it takes ~68 days to hit 4%.
**To hit 4% in 30 days**, you need a spread of approx **0.09% - 0.10% per round** (or use 2x-3x leverage to amplify the yield).

> **Note:** If you use **2x Leverage** ($1000 Collateral -> $2000 Position), the time is cut in half to **~34 Days**.

---

## 4. Advanced: The "Sniper" Strategy (Timing the Payout)
**Question:** Do I need to hold for the full 8 hours?
**Answer:** No. You only need to hold the position at the **exact moment of the snapshot** (e.g., 07:00, 15:00, 23:00).

### The "Sniper" Approach
*   **Strategy:** Enter 15-30 minutes before the funding time.
*   **Pros:**
    *   **Capital Efficiency:** Your money is locked for only ~1 hour instead of 8 hours.
    *   **Rotation:** You can reuse the same capital for other pairs.
*   **Cons (Risks):**
    *   **Front-running:** Prices often move unfavorably just before funding as everyone tries to enter.
    *   **Spread Compression:** The arbitrage gap often disappears 5-10 mins before the deadline.
*   **Recommendation:** Start by entering **1 hour before**. Don't wait until the last minute.

---

## 5. CLI Helpers (Opening/Closing the Spread)
We added simple scripts to open/close the spread with limit + slippage buffer (using `ExecutionManager`).

- Open spread (Long Asterdex / Short Hyperliquid):  
  `python open_order.py HEMI 500`  
  *Parameters*: `symbol` (base, e.g., HEMI), `notional` per leg in quote (USDT/USDC), e.g., 500.

- Close spread:  
  `python close_order.py HEMI 32695 32847`  
  *Parameters*: `symbol`, `qty_long` (Asterdex long leg qty, base), `qty_short` (Hyperliquid short leg qty, base).

Notes:
- Scripts use limit orders with slippage buffer from `SLIPPAGE_BPS` in `src/config.py`.
- Adapters currently have mock `place_order`; wire to real API before trading live.
