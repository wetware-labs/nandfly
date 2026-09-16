// Scoreboard: totalSwats / totalJumps / survivedSwats from the deployed
// contract (post-deploy), or "--" pre-deploy (never a fabricated number).
// Also renders the "16 / 166,700 neurons on-chain" progress line used
// everywhere per spec section 10, and the birth-milestone progress gauge.

import { CONFIG } from "../config.js";
import { decodeUint256, SELECTORS } from "./abi.js";

async function rpcCall(method, params) {
  // Try each configured endpoint in order (same fallback pattern as
  // live-layer.js) so a single flaky public RPC can't blank the scoreboard.
  const urls = CONFIG.rpcUrls;
  let lastErr;
  for (const url of urls) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      if (json.error) throw new Error(json.error.message || "RPC error");
      return json.result;
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("all RPC endpoints failed");
}

async function readUint(selectorHex) {
  const data = await rpcCall("eth_call", [
    { to: CONFIG.contractAddress, data: selectorHex },
    "latest",
  ]);
  return decodeUint256(data);
}

export function renderNeuronProgress(el) {
  const { neuronsOnChain, neuronsTotal } = CONFIG.birth;
  el.textContent = `${neuronsOnChain.toLocaleString("en-US")} / ${neuronsTotal.toLocaleString("en-US")} neurons on-chain`;
}

// Chainlink BNB/USD aggregator proxy on BSC mainnet. Address from
// docs.chain.link's BNB Chain feed registry, then independently verified
// on-chain before hardcoding (2026-09-16, via eth_call against BSC):
//   description() -> "BNB / USD", decimals() -> 8, latestRoundData() ->
//   a fresh answer (~$711 at check time). Selectors below computed offline
//   with the project's own keccak (tapeout/_keccak.py), same as abi.js:
//     latestRoundData() -> 0xfeaf968c
const CHAINLINK_BNB_USD = "0x0567F2323251f0Aab15c8dFb1967E4e8A7D42aeE";
const LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c";

/** Decode latestRoundData()'s `answer` (2nd of 5 words, int256 with 8
 * decimals). Returns a BigInt; throws on a non-positive answer rather than
 * ever rendering a bogus price. */
function decodeRoundAnswer(hexData) {
  const data = hexData.startsWith("0x") ? hexData.slice(2) : hexData;
  const word = data.slice(64, 128);
  if (word.length !== 64) throw new Error("malformed latestRoundData response");
  const answer = BigInt("0x" + word);
  // int256: any value with the sign bit set (or zero) is not a usable price.
  if (answer === 0n || answer >= 1n << 255n) throw new Error("price feed returned a non-positive answer");
  return answer;
}

export async function renderBirthGauge(container) {
  const { goalUsd, feedingWalletAddress, gasFloatWei } = CONFIG.birth;

  const renderBar = (raisedUsdText, pct, noteText) => {
    container.innerHTML = `
      <div class="birth-gauge">
        <div class="birth-gauge-fill" style="width:${pct}%"></div>
      </div>
      <p class="birth-gauge-label"></p>
      <p class="hint birth-gauge-note"></p>
    `;
    container.querySelector(".birth-gauge-label").textContent =
      `${raisedUsdText} / $${goalUsd.toFixed(2)} raised toward birth (7-cell TapeOut mint)`;
    container.querySelector(".birth-gauge-note").textContent = noteText;
  };

  renderBar("$--", 0, "Reading the feeding wallet from BSC...");
  try {
    const [balHex, roundHex] = await Promise.all([
      rpcCall("eth_getBalance", [feedingWalletAddress, "latest"]),
      rpcCall("eth_call", [{ to: CHAINLINK_BNB_USD, data: LATEST_ROUND_DATA_SELECTOR }, "latest"]),
    ]);
    const balanceWei = BigInt(balHex);
    const floatWei = BigInt(gasFloatWei);
    const answer = decodeRoundAnswer(roundHex); // USD per BNB, 8 decimals
    const raisedWei = balanceWei > floatWei ? balanceWei - floatWei : 0n;
    // wei (1e18) * price (1e8) -> USD cents (1e2): divide by 1e24.
    const usdCents = (raisedWei * answer) / 10n ** 24n;
    const raisedUsd = Number(usdCents) / 100;
    const pct = Math.max(0, Math.min(100, (raisedUsd / goalUsd) * 100));
    renderBar(
      `$${raisedUsd.toFixed(2)}`,
      pct,
      "Live from BSC: the feeding wallet's balance minus the disclosed pre-launch gas float (~0.0179 BNB, our own deploy gas, not donations), converted at Chainlink's on-chain BNB/USD feed. No manual number anywhere."
    );
  } catch (e) {
    // Never fabricate a number: on any RPC/feed failure the gauge says so.
    renderBar(
      "$--",
      0,
      `Could not read the wallet or price feed right now (${String((e && e.message) || e)}). The gauge only ever shows live on-chain values.`
    );
  }
}

export async function renderScoreboard(container) {
  if (!CONFIG.contractAddress) {
    container.innerHTML = `
      <div class="scoreboard">
        <div class="stat"><div class="stat-value">--</div><div class="stat-label">total swats</div></div>
        <div class="stat"><div class="stat-value">--</div><div class="stat-label">jumps</div></div>
        <div class="stat"><div class="stat-value">--</div><div class="stat-label">survived</div></div>
      </div>
      <p class="hint">Contract not deployed yet -- counters will read live from BSC the moment it is.</p>
    `;
    return;
  }

  container.innerHTML = `<p class="hint">Loading on-chain counters...</p>`;
  try {
    const [totalSwats, totalJumps, survivedSwats] = await Promise.all([
      readUint(SELECTORS["totalSwats()"]),
      readUint(SELECTORS["totalJumps()"]),
      readUint(SELECTORS["survivedSwats()"]),
    ]);
    container.innerHTML = `
      <div class="scoreboard">
        <div class="stat"><div class="stat-value">${totalSwats}</div><div class="stat-label">total swats</div></div>
        <div class="stat"><div class="stat-value">${totalJumps}</div><div class="stat-label">jumps</div></div>
        <div class="stat"><div class="stat-value">${survivedSwats}</div><div class="stat-label">survived</div></div>
      </div>
    `;
  } catch (e) {
    // e.message may originate from a third-party RPC endpoint's response --
    // build via textContent, never innerHTML, so it can never be treated as
    // markup.
    container.textContent = "";
    const p = document.createElement("p");
    p.className = "hint";
    p.textContent = `Could not reach the contract right now (${String((e && e.message) || e)}).`;
    container.appendChild(p);
  }
}
