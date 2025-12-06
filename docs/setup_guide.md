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

## 3. Example Allocation ($1,000 Total)
1.  **Swap:** Convert $500 to USDC and $500 to USDT.
2.  **Transfer:**
    *   Send $500 **USDC** -> Hyperliquid Account.
    *   Send $500 **USDT** -> Asterdex Futures Account.
3.  **Result:** You are ready to open a $500 Long and $500 Short (1x Leverage) or more if using leverage.

## 4. Rebalancing (The "Rotation" Cost)
*   When you close a position, funds return to the respective exchange.
*   If you need to move funds (e.g., Hyperliquid profit -> Asterdex loss), you will need to:
    1.  Withdraw to Wallet.
    2.  Swap (USDC <-> USDT) on Uniswap/1inch.
    3.  Deposit to the other exchange.
*   *Tip:* Keep a small "Buffer" in your wallet to avoid waiting for withdrawals during urgent rebalancing.
