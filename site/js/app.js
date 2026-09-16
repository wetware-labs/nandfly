// Wires the whole page together: loads the netlist once, then boots the
// fly, circuit viewer, swat UI, live layer, and scoreboard/progress widgets.

import { CONFIG } from "../config.js";
import { Fly } from "./fly.js";
import { CircuitViewer } from "./circuit-viewer.js";
import { LiveLayer } from "./live-layer.js";
import { SwatUI } from "./swat.js";
import { renderScoreboard, renderNeuronProgress, renderBirthGauge } from "./scoreboard.js";
import { BrainViewer } from "./brain.js";

const DATA_URL = new URL("../data/full.json", import.meta.url);

function formatTime() {
  const d = new Date();
  return d.toLocaleTimeString("en-US", { hour12: false });
}

// All dynamic text below is set via textContent / DOM node construction,
// never innerHTML -- some of it (RPC error messages) originates from a
// third-party endpoint (site/config.js's rpcUrls) and must never be treated
// as markup, even from a compromised or malicious RPC response.

/**
 * @param {HTMLElement} feedEl
 * @param {string} text
 * @param {object} [opts]
 * @param {string} [opts.cls] - extra class on the feed item (e.g. "jump")
 * @param {boolean} [opts.synthetic] - true for test-hook-injected events;
 *   gets a distinct dashed-border + "SYNTHETIC" badge treatment so a
 *   cropped screenshot can never be mistaken for a real chain event, even
 *   with the test hook enabled.
 */
function addFeedItem(feedEl, text, opts = {}) {
  const item = document.createElement("div");
  item.className = "feed-item" + (opts.cls ? ` ${opts.cls}` : "") + (opts.synthetic ? " synthetic" : "");

  const timeSpan = document.createElement("span");
  timeSpan.className = "feed-time";
  timeSpan.textContent = formatTime();
  item.appendChild(timeSpan);

  if (opts.synthetic) {
    const badge = document.createElement("span");
    badge.className = "synthetic-badge";
    badge.textContent = "SYNTHETIC";
    item.appendChild(badge);
  }

  item.appendChild(document.createTextNode(text));

  // Newest item goes right below the "observation feed" <h4>, which must
  // stay pinned as the container's first child (eviction below trims from
  // the bottom, so the header is never removed).
  const header = feedEl.querySelector("h4");
  if (header) header.after(item);
  else feedEl.prepend(item);
  while (feedEl.children.length > 60) feedEl.removeChild(feedEl.lastChild);
}

function setStatus(statusEl, dotClass, text) {
  if (!statusEl) return;
  statusEl.textContent = "";
  const dot = document.createElement("span");
  dot.className = "status-dot" + (dotClass ? ` ${dotClass}` : "");
  statusEl.appendChild(dot);
  statusEl.appendChild(document.createTextNode(text));
}

async function main() {
  const netlist = await fetch(DATA_URL).then((r) => r.json());

  // --- Progress lines (spec: "16 / 166,700 neurons on-chain" everywhere) ---
  document.querySelectorAll("[data-neuron-progress]").forEach((el) => renderNeuronProgress(el));

  // --- Fly + live layer ---
  const flyCanvas = document.getElementById("fly-canvas");
  // Read the live accent (BNB gold) from CSS so fly.js's rim glow / firing
  // glow / circuit-trace tint stay a single source of truth with the rest
  // of the page's accent instead of drifting from a hardcoded duplicate.
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim();
  const fly = new Fly(flyCanvas, accent ? { accent } : {});
  fly.start();

  // --- Hero CTA: smooth-scroll to the swat section (CSS already sets
  // `scroll-behavior: smooth`) and move focus there for keyboard/screen
  // reader users, since the anchor jump alone doesn't move focus.
  const heroCta = document.getElementById("hero-cta");
  const swatSection = document.getElementById("swat-section");
  if (heroCta && swatSection) {
    heroCta.addEventListener("click", () => {
      if (!swatSection.hasAttribute("tabindex")) swatSection.setAttribute("tabindex", "-1");
      window.setTimeout(() => swatSection.focus({ preventScroll: true }), 400);
    });
  }

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
      setStatus(
        statusEl,
        info.synthetic ? "" : "live",
        `block #${info.blockNumber}${info.synthetic ? " (test-injected)" : ""} · ${info.txCount} tx · largest tx ${info.maxBnb.toFixed(2)} BNB`
      );
      if (feedEl) {
        // "twitch" language for ordinary blocks (ambient stimulus, at most
        // one spike bit -- see live-layer.js's _ambientStimulus -- can never
        // fire the reflex); a block that crosses the whale threshold gets a
        // distinct dimmer-vs-brighter treatment so the feed's hierarchy
        // previews the loom/jump events that follow it.
        const isWhale = info.maxBnb >= CONFIG.live.whaleThresholdBnb;
        addFeedItem(
          feedEl,
          isWhale
            ? `block #${info.blockNumber} -- ${info.txCount} tx, largest ${info.maxBnb.toFixed(2)} BNB (whale-sized)`
            : `block #${info.blockNumber} -- ${info.txCount} tx, fly twitches`,
          { cls: isWhale ? "whale-block" : "ambient-block", synthetic: info.synthetic }
        );
      }
    },
    onEvent: (evt) => {
      if (evt.type === "rpc-error") {
        // evt.message originates from a third-party RPC endpoint's response
        // -- never trusted as markup. setStatus() uses textContent only.
        setStatus(statusEl, "err", `RPC unreachable: ${evt.message}`);
        return;
      }
      if (!feedEl) return;
      const synthetic = evt.source === "synthetic";
      if (evt.type === "jump") {
        // "reflex fired" language is reserved for real jumps -- and a jump
        // only ever originates from a whale-sized looming stimulus now (see
        // live-layer.js's _loomingStimulus; ambient blocks never reach this
        // branch at all).
        addFeedItem(
          feedEl,
          `reflex fired at block #${evt.blockNumber} -- ${evt.bnb.toFixed(2)} BNB whale`,
          { cls: "jump", synthetic }
        );
      } else if (evt.type === "loom-survived") {
        addFeedItem(
          feedEl,
          `looming stimulus at block #${evt.blockNumber} (${evt.bnb.toFixed(2)} BNB) -- it ignored it`,
          { cls: "loom", synthetic }
        );
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

  // --- The whole brain (soma point cloud) ---
  const brainCanvas = document.getElementById("brain-canvas");
  if (brainCanvas) {
    const viewer = new BrainViewer(
      brainCanvas,
      document.getElementById("brain-caption"),
      document.getElementById("brain-tooltip"),
      accent ? { accent } : {}
    );
    // init() handles its own fetch failure with an honest fallback line; a
    // brain-view problem must never take down the rest of the page.
    viewer.init().catch((e) => console.warn("brain view disabled:", e));
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
