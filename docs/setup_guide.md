# Setup Guide: Wallets & Funding

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

## 4. Example Allocation ($1,000 Total)
1.  **Swap:** Convert $500 to USDC and $500 to USDT.
2.  **Transfer:**
    *   Send $500 **USDC** -> Hyperliquid Account.
    *   Send $500 **USDT** -> Asterdex Futures Account.
3.  **Result:** You are ready to open a $500 Long and $500 Short (1x Leverage) or more if using leverage.

## 5. Rebalancing (The "Rotation" Cost)
*   When you close a position, funds return to the respective exchange.
*   If you need to move funds (e.g., Hyperliquid profit -> Asterdex loss), you will need to:
    1.  Withdraw to Wallet.
    2.  Swap (USDC <-> USDT) on Uniswap/1inch.
    3.  Deposit to the other exchange.
*   *Tip:* Keep a small "Buffer" in your wallet to avoid waiting for withdrawals during urgent rebalancing.
