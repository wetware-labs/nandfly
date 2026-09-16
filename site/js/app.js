// Wires the whole page together: loads the netlist once, then boots the
// fly, circuit viewer, swat UI, live layer, and scoreboard/progress widgets.

import { CONFIG } from "../config.js";
import { Fly } from "./fly.js";
import { CircuitViewer } from "./circuit-viewer.js";
import { LiveLayer } from "./live-layer.js";
import { SwatUI } from "./swat.js";
import { renderScoreboard, renderNeuronProgress, renderBirthGauge } from "./scoreboard.js";

const DATA_URL = new URL("../data/full.json", import.meta.url);

function formatTime() {
  const d = new Date();
  return d.toLocaleTimeString("en-US", { hour12: false });
}

function addFeedItem(feedEl, text, cls) {
  const item = document.createElement("div");
  item.className = "feed-item" + (cls ? ` ${cls}` : "");
  item.innerHTML = `<span class="feed-time">${formatTime()}</span>${text}`;
  feedEl.prepend(item);
  while (feedEl.children.length > 60) feedEl.removeChild(feedEl.lastChild);
}

async function main() {
  const netlist = await fetch(DATA_URL).then((r) => r.json());

  // --- Progress lines (spec: "16 / 166,700 neurons on-chain" everywhere) ---
  document.querySelectorAll("[data-neuron-progress]").forEach((el) => renderNeuronProgress(el));

  // --- Fly + live layer ---
  const flyCanvas = document.getElementById("fly-canvas");
  const fly = new Fly(flyCanvas);
  fly.start();

  const circuitContainer = document.getElementById("circuit-viewer");
  let circuitViewer = null;
  if (circuitContainer) {
    circuitViewer = new CircuitViewer(circuitContainer, netlist);
    const detail = document.getElementById("circuit-detail");
    circuitViewer.onSelect = (neuron, gateSet) => {
      if (!detail) return;
      const extra =
        neuron.role === "visual_input"
          ? ""
          : ` &middot; threshold ${neuron.threshold} of max ${neuron.max_possible_sum}`;
      detail.innerHTML = `<strong>body #${neuron.neuron_id}</strong> (${neuron.type}, ${neuron.side}) -- ${neuron.role.replace("_", " ")}${extra}. Signal <code>${neuron.signal}</code> touches <strong>${gateSet.size}</strong> gates.`;
    };
  }

  const feedEl = document.getElementById("live-feed");
  const statusEl = document.getElementById("live-status");

  const liveLayer = new LiveLayer({
    netlist,
    fly,
    circuitViewer,
    onBlock: (info) => {
      if (statusEl) {
        const dotClass = info.synthetic ? "" : "live";
        statusEl.innerHTML = `<span class="status-dot ${dotClass}"></span>block #${info.blockNumber}${
          info.synthetic ? " (test-injected)" : ""
        } &middot; ${info.txCount} tx &middot; largest tx ${info.maxBnb.toFixed(2)} BNB`;
      }
      if (feedEl) {
        addFeedItem(
          feedEl,
          `block #${info.blockNumber}${info.synthetic ? " (synthetic)" : ""} -- ${info.txCount} tx, largest ${info.maxBnb.toFixed(2)} BNB`
        );
      }
    },
    onEvent: (evt) => {
      if (evt.type === "rpc-error") {
        if (statusEl) statusEl.innerHTML = `<span class="status-dot err"></span>RPC unreachable: ${evt.message}`;
        return;
      }
      if (!feedEl) return;
      if (evt.type === "jump") {
        const detail =
          evt.source === "chain" || evt.source === "synthetic"
            ? `reflex fired at block #${evt.blockNumber} -- ${evt.bnb.toFixed(2)} BNB whale`
            : "reflex fired -- ambient stimulus";
        addFeedItem(feedEl, detail, "jump");
      } else if (evt.type === "loom-survived") {
        addFeedItem(feedEl, `looming stimulus at block #${evt.blockNumber} (${evt.bnb.toFixed(2)} BNB) -- it ignored it`);
      }
    },
  });
  liveLayer.start();
  window.__nandflyLiveLayer = liveLayer; // for Playwright / debugging

  // --- Swat UI ---
  const swatContainer = document.getElementById("swat-ui");
  if (swatContainer) {
    new SwatUI(swatContainer, netlist, { fly, circuitViewer });
  }

  // --- Scoreboard ---
  const scoreboardEl = document.getElementById("scoreboard");
  if (scoreboardEl) renderScoreboard(scoreboardEl);

  // --- Birth milestone ---
  const gaugeEl = document.getElementById("birth-gauge");
  if (gaugeEl) renderBirthGauge(gaugeEl);
  const walletEl = document.getElementById("feeding-wallet-address");
  if (walletEl) {
    walletEl.textContent = CONFIG.birth.feedingWalletAddress || "(wallet not published yet -- see METHODS)";
  }
}

main().catch((err) => {
  console.error("NANDFLY site failed to boot:", err);
  const boot = document.getElementById("boot-error");
  if (boot) {
    boot.hidden = false;
    boot.textContent = `Failed to load: ${String((err && err.message) || err)}`;
  }
});
