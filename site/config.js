// NANDFLY site configuration. Single source of truth for everything
// environment-specific (contract address, RPC endpoint, progress numbers).
// Plain ES module, no build step -- edit this file directly and redeploy.
//
// PRE-DEPLOY MODE: `contractAddress` is null because NandFly.sol has not
// been deployed yet (see contract/DEPLOY.md -- deployment is Task 5's job,
// gated on explicit user go-ahead). Every part of the site that would
// normally read on-chain state (scoreboard counters, swat's official tx
// mode) falls back to "pre-deploy simulation" / "--" when this is null.
// Fill in the deployed address here (and nothing else needs to change) the
// moment Task 5 completes.

export const CONFIG = {
  // --- Layer 1 contract (NandFly.sol) ---
  contractAddress: null, // e.g. "0x1234...abcd" once deployed (Task 5)
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
  },

  // --- Birth milestone (spec section 10) ---
  birth: {
    // Feeding wallet address: not created yet (published BEFORE first
    // inflow per the locked wallet policy -- see METHODS page and
    // docs/specs section 3). Placeholder until the wallet exists.
    feedingWalletAddress: null,
    goalUsd: 30,
    // Manual value until the feeding wallet exists and can be read live;
    // update by hand as real inflows happen (see progress.md ledger).
    raisedUsd: 0,
    neuronsOnChain: 16,
    neuronsTotal: 166700,
  },

  siteUrl: "https://wetware-labs.github.io/nandfly/",
};
