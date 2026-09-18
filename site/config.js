// NANDFLY site configuration. Single source of truth for everything
// environment-specific (contract address, RPC endpoint, progress numbers).
// Plain ES module, no build step -- edit this file directly and redeploy.
//
// LIVE MODE: `contractAddress` points at the deployed, BscScan-verified
// NandFly contract (see contract/DEPLOY.md for the deploy record). If it is
// ever set back to null the site degrades to a clearly-labeled local
// simulation ("pre-deploy simulation" badges) instead of breaking.

export const CONFIG = {
  // --- Layer 1 contract (NandFly.sol) ---
  contractAddress: "0x3AB7b7621dB958c989B4B628D38B2D3d3642980A", // deployed 2026-09-16, bornAt 1789542725
  chainId: 56, // BSC mainnet

  // Public, read-only BSC RPC endpoints (no API key, no wallet, no write
  // access needed for anything this site does -- see the module docstring
  // of site/js/live-layer.js). Polling (HTTPS JSON-RPC) is used rather than
  // a persistent `wss://` subscription so the site has zero server-side
  // component and works from a static host (GitHub Pages) with nothing to
  // keep alive; the list is tried in order with automatic fallback on
  // failure. Swap/add endpoints freely -- this is pure config.
  rpcUrls: [
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.defibit.io",
    "https://bsc-dataseed1.ninicoin.io",
  ],

  // --- Live layer tuning (spec section 9) ---
  live: {
    // How often to poll for a new block head (ms). BSC's real block time is
    // ~3s; polling a bit slower than that avoids hammering a free public
    // endpoint while still feeling "live."
    pollIntervalMs: 4000,
    // A block's biggest single transaction value (in BNB) at/above this is
    // a "looming stimulus" (fly startles proportionally to size); below it,
    // every new block is just ambient micro-stimulus (1-2 low bits flicker).
    whaleThresholdBnb: 50,
    // A transaction value (BNB) at/above this is treated as "full loom"
    // (maximum stimulus intensity) regardless of how much bigger it gets --
    // used to scale the looming stimulus's bit count between
    // whaleThresholdBnb (weakest whale) and this value (strongest).
    maxLoomBnb: 5000,

    // Gates window.__nandflyTestHook (site/js/live-layer.js's synthetic
    // block/whale injection API). Default FALSE -- this must never ship
    // live/reachable by a random site visitor. Two ways to enable it, both
    // read once at boot by live-layer.js (see that file for the exact
    // check):
    //   1. Flip this to `true` for a local/dev build.
    //   2. Load the page with `?testhook=1` in the URL (what
    //      site/scripts/e2e.mjs's Playwright run does) -- no source edit
    //      needed for one-off verification.
    // Either path still renders injected events with the distinct
    // "SYNTHETIC" badge/dashed-border treatment (site/css/style.css's
    // `.feed-item.synthetic` / `.synthetic-badge`) -- that styling is NOT
    // gated by this flag, so an injected event can never be mistaken for a
    // real chain event even when the hook is enabled.
    enableTestHook: false,
  },

  // --- Birth milestone (spec section 10) ---
  birth: {
    // Feeding wallet (live). Policy published on the site BEFORE the first
    // inflow: 80% of every inflow buys components, 20% operations; equal
    // treatment of all inflows. The wallet's small pre-launch balance is the
    // project's own deploy-gas float, not donations.
    feedingWalletAddress: "0x14Ab88CF91376451a24179C41965D1f24269e3a6",
    goalUsd: 30,
    // The wallet's disclosed own-money gas float, in wei. History: launch
    // balance (2026-09-16) was 0.01788 BNB of our own deploy gas; on
    // 2026-09-17/18, before any inflow ever arrived, we withdrew our own
    // surplus in two transactions (tx nonces 1 and 2 on-chain), leaving
    // this exact float. No donation was touched -- the wallet has never
    // received one. Once the first inflow arrives, this constant is frozen
    // and every wallet movement follows the published 80/20 policy.
    // The birth gauge shows max(0, live balance - this float) so the
    // project's own leftover gas can never be displayed as donations.
    // There is deliberately NO manual "raised" number in this config --
    // the gauge reads the chain (see scoreboard.js's renderBirthGauge).
    gasFloatWei: "1368961294832504",
    neuronsOnChain: 16,
    neuronsTotal: 166700,
    // Birth certificate attribution. `claimedBy` stays null until a real
    // wallet's inflow crosses the goal (by on-chain record); then it is set
    // to the name/handle that wallet chooses (or its address) and redeployed.
    // Never pre-filled -- an empty slot is the honest state.
    certificate: {
      claimedBy: null,
    },
  },

  siteUrl: "https://wetware-labs.github.io/nandfly/",
};
