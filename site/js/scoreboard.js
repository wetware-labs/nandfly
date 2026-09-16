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

export function renderBirthGauge(container) {
  const { goalUsd, raisedUsd } = CONFIG.birth;
  const pct = Math.max(0, Math.min(100, (raisedUsd / goalUsd) * 100));
  container.innerHTML = `
    <div class="birth-gauge">
      <div class="birth-gauge-fill" style="width:${pct}%"></div>
    </div>
    <p class="birth-gauge-label">$${raisedUsd.toFixed(2)} / $${goalUsd.toFixed(2)} raised toward birth (7-cell TapeOut mint)</p>
  `;
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
