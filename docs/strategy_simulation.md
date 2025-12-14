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

---

## 6. Signal Filters (Current Logic)
- Must have data from both exchanges; passes delist/volume filters (unless in `WATCHLIST`).
- Net per 8h round is `diff - fees - slippage`. Signals are shown only if **net_per_round > 0** (watchlist bypass).
- Monthly projection shown is informational only (net_per_round * 90); not used to filter signals.
- Break-even: if net_per_round > 0 → 1 round, else 999 (not profitable per round).

---

## 7. กลยุทธ์เพิ่มเติม (Advanced Strategies) 🇹🇭

### 7.1 Funding Rate Arbitrage (กินส่วนต่างดอกเบี้ย)
นี่คือกลยุทธ์หลักของบอทตัวนี้ หัวใจสำคัญคือการ **"กินส่วนต่างระหว่าง 2 ตลาด"**

**หลักการ:**
1.  หาราคา Funding Rate ของ 2 ตลาดที่ไม่เท่ากัน
2.  เปิด **Long** ในตลาดที่ Rate ต่ำ (จ่ายน้อย หรือได้รับเงิน)
3.  เปิด **Short** ในตลาดที่ Rate สูง (ได้รับเงินเยอะ)
4.  กำไร = (เงินที่ได้รับจาก Short) - (เงินที่จ่ายให้ Long)

**ตัวอย่าง:**
*   **Asterdex:** Funding Rate **+0.10%** (ถ้า Short ได้รับ 0.10%)
*   **Hyperliquid:** Funding Rate **+0.02%** (ถ้า Long จ่าย 0.02%)
*   **Action:** Short Asterdex / Long Hyperliquid
*   **Net Profit:** รับ 0.10% - จ่าย 0.02% = **กำไร 0.08% ต่อรอบ** (ความเสี่ยงต่ำเพราะ Hedging ไว้ 2 ขา)

---

### 7.2 Funding Rate Scalping (ฉกฉวยโอกาสจากรอบเวลา)
กลยุทธ์นี้ใช้ประโยชน์จาก **"รอบการจ่ายเงินที่ไม่พร้อมกัน"** ของแต่ละตลาด (Time Arbitrage)

**ข้อมูลสำคัญ:**
*   **Hyperliquid:** จ่ายทุก **1 ชั่วโมง** (จ่ายถี่)
*   **Asterdex:** จ่ายทุก **8 ชั่วโมง** (07:00, 15:00, 23:00)

**สถานการณ์ทำกำไร (The Golden Scenario):**
สมมติ **Hyperliquid Rate ติดลบหนัก (-1.0%)** แปลว่าฝั่ง **Long ได้เงิน**

1.  **เข้า Order (15:05):** หลังจบรอบ Asterdex ไปแล้ว
2.  **ถือยาว (16:00 - 22:50):**
    *   คุณถือ Long Hyperliquid: **รับเงินฟรีๆ** ทุกชั่วโมง (16:00, 17:00 ... 22:00) รวม 7 รอบ
    *   คุณถือ Short Asterdex: **ไม่ต้องจ่ายเงิน** เพราะยังไม่ถึงรอบ 23:00
3.  **ปิด Order (22:50):** ขายหนีก่อนถึงเวลา 23:00
4.  **ผลลัพธ์:** ได้กำไรจาก HL ฟรีๆ 7 รอบ โดยไม่เสียค่า Funding ให้ Asterdex เลย!

**ข้อควรระวัง:**
*   **Spread Risk:** ต้องระวังว่าส่วนต่างราคา (Price Spread) ระหว่าง 2 ตลาดต้องไม่ถ่างออกจนกินกำไร Funding ที่ทำมาได้
*   **Liquidity:** ต้องชัวร์ว่าตอนจะปิด (22:50) มี Volume ให้ขายออกได้ทันที
