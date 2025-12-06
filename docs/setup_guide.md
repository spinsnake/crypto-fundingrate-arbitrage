# Setup Guide: Wallets & Funding

## 0. Fiat On-Ramp (Bank -> Crypto)
**Step 1: Convert THB to USDT**
You cannot transfer directly from a Thai Bank to Hyperliquid/Asterdex. You need a "Bridge".
*   **Option A: Thai Exchange (Bitkub / Binance TH / Orbix)**
    1.  Deposit THB via QR Code.
    2.  Buy **USDT**.
    3.  Withdraw USDT to your **Metamask Wallet** (Select Network: **Arbitrum One**).
*   **Option B: P2P (Binance Global / OKX)**
    1.  Go to P2P Trading.
    2.  Buy USDT from a merchant using Bank Transfer.
    3.  Withdraw USDT to your **Metamask Wallet** (Select Network: **Arbitrum One**).

**⚠️ Important:** Always select **Arbitrum One** network when withdrawing. If you choose Ethereum (ERC20), fees will be very expensive ($10+). Arbitrum fees are cheap ($0.1 - $1).

## 1. Wallet Setup (One Key for All)
You only need **1 EVM Wallet** (MetaMask, Rabby, or Trust Wallet).
*   **Network:** Arbitrum One (Recommended for low fees & speed).
*   **Address:** Use the *same address* for both Hyperliquid and Asterdex.
*   **Gas:** Keep ~$10-20 worth of **ETH (Arbitrum)** in the wallet for transaction fees.

## 2. Funding Requirements (The Split)
Since we are doing Delta Neutral (Long + Short), you must split your capital **50/50**.

### Exchange A: Hyperliquid
*   **Currency:** **USDC (Bridged USDC)** on Arbitrum.
*   **Deposit:** Connect wallet to [Hyperliquid.xyz](https://hyperliquid.xyz) and deposit USDC.
*   **Note:** Hyperliquid uses a "Sub-account" model. You deposit into the smart contract.

### Exchange B: Asterdex
*   **Currency:** **USDT** on Arbitrum (Standard for Futures).
*   **Deposit:** Connect wallet to Asterdex and deposit USDT into the Futures wallet.

## 3. Minimum Capital Analysis
**Question:** How much money do I need to start?

### A. Technical Minimum (For Testing Only) -> ~$50
*   **Hyperliquid Min Order:** ~$10 USDC
*   **Asterdex Min Order:** ~$5-10 USDT
*   **Total:** $25 + $25 = **$50**
*   **Result:** You can run the bot, but **Gas Fees + Trading Fees will likely eat all your profit.** Do this just to test the system.

### B. Profitable Minimum (Recommended) -> ~$500
*   **Why?** You need enough volume so that the **Profit ($)** is larger than the **Gas Fee ($0.50 - $1.00)**.
*   **Math:**
    *   Capital: $500 ($250 Long / $250 Short)
    *   Spread Profit (0.2%): +$1.00
    *   Trading Fees (0.1%): -$0.50
    *   Gas Fees: -$0.30
    *   **Net Profit:** **+$0.20** (Green)
*   **Conclusion:** Start with **$500** if you want to see actual green numbers.

## 4. Leverage Explained (User Question)
**"Can I trade without leverage?"**
*   **YES.** This is called **1x Leverage**.
*   **Example:** You have $500 total ($250 on Asterdex, $250 on Hyperliquid).
*   **Action:** You buy $250 worth of coin on Asterdex and sell $250 worth on Hyperliquid.
*   **Risk:** Lowest possible. You only get liquidated if the price moves ~90-100% against you (which is nearly impossible with Delta Neutral hedging).

## 5. Rebalancing (The "Rotation" Cost)
*   When you close a position, funds return to the respective exchange.
*   If you need to move funds (e.g., Hyperliquid profit -> Asterdex loss), you will need to:
    1.  Withdraw to Wallet.
    2.  Swap (USDC <-> USDT) on Uniswap/1inch.
    3.  Deposit to the other exchange.
*   *Tip:* Keep a small "Buffer" in your wallet to avoid waiting for withdrawals during urgent rebalancing.

## 6. Daily Schedule (When to Work)
You don't need to watch 24/7. Just focus on these **3 Critical Times** (UTC+7 / Thailand Time):

1.  **☀️ 07:00 AM** (Morning) -> Start checking at **06:30 AM**
2.  **🕑 15:00 PM** (Afternoon) -> Start checking at **14:30 PM**
3.  **🌙 23:00 PM** (Night) -> Start checking at **22:30 PM**

**Why?**
*   Asterdex pays Funding Fees exactly at these times.
*   **Strategy:** Enter 30 mins before -> Get Paid -> Exit (Sniper Mode).
