// Playwright E2E verification for the NANDFLY site (Task 4's "Verify" step).
//
// NOT a repo dependency: this project stays zero-deps in production and
// Playwright is not installed here. This script borrows an already-installed
// Playwright from a sibling project checkout (see PLAYWRIGHT_PATH below) --
// purely a local verification convenience, never shipped, never imported by
// any site code. If that sibling checkout isn't present, install Playwright
// wherever is convenient and point PLAYWRIGHT_PATH at its index.mjs.
//
// Prerequisites: `node site/scripts/serve.mjs 8934` running in another
// terminal (or this script will fail to connect).
//
// Run from the repo root: node site/scripts/e2e.mjs

import path from "node:path";
import { mkdirSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const SCREENSHOT_DIR = path.join(REPO_ROOT, ".superpowers", "sdd", "nandfly-mvp");
mkdirSync(SCREENSHOT_DIR, { recursive: true });

const PLAYWRIGHT_PATH =
  process.env.PLAYWRIGHT_PATH ||
  "C:/Users/gmldn/Documents/Codex/outguess/node_modules/playwright/index.mjs";
const BASE_URL = process.env.NANDFLY_BASE_URL || "http://localhost:8934";

const { chromium } = await import(pathToFileURL(PLAYWRIGHT_PATH).href);

let failures = 0;
function ok(cond, label) {
  if (cond) {
    console.log(`PASS: ${label}`);
  } else {
    console.error(`FAIL: ${label}`);
    failures += 1;
  }
}

async function main() {
  const browser = await chromium.launch();

  // --- Desktop: live layer + circuit viewer + console errors ---
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  // ?testhook=1 enables window.__nandflyTestHook for THIS page load only
  // (site/config.js's `live.enableTestHook` is the source-level default,
  // false; the query param is the documented no-source-edit opt-in this
  // script uses -- see live-layer.js's testHookAllowed()).
  await page.goto(`${BASE_URL}/index.html?testhook=1`, { waitUntil: "networkidle" });

  // Netlist loaded + fly canvas present.
  const canvas = await page.$("#fly-canvas");
  ok(!!canvas, "fly canvas present");

  // Wait for at least one real block to be observed (live status updates
  // away from "connecting...").
  let liveObserved = false;
  try {
    await page.waitForFunction(
      () => {
        const el = document.getElementById("live-status");
        return el && !el.textContent.includes("connecting");
      },
      { timeout: 20000 }
    );
    liveObserved = true;
  } catch {
    liveObserved = false;
  }
  ok(liveObserved, "live layer observed at least one block from real BSC RPC");

  const statusText = await page.$eval("#live-status", (el) => el.textContent);
  console.log(`  live status: ${statusText}`);

  // Inject a synthetic whale block via the test hook to force a jump
  // deterministically (spec: "if no whale appears during test, inject a
  // synthetic block via a test hook to show the jump"), then screenshot the
  // fly + live feed together while framed nicely (element screenshot, not
  // full-page, so later scrolling from other interactions can't affect it).
  await page.evaluate(() => {
    window.__nandflyTestHook.injectWhale(4200);
  });
  await page.waitForTimeout(800);
  const feedTextEarly = await page.$eval("#live-feed", (el) => el.textContent);
  ok(feedTextEarly.includes("4200.00 BNB") || feedTextEarly.includes("whale"), "synthetic whale event appears in the feed");
  console.log(`  feed snippet: ${feedTextEarly.slice(0, 160)}`);

  // The injected events must be visually distinguishable from real ones,
  // even with the hook enabled (finding 2's "keep this styling even when
  // the hook is enabled").
  const syntheticCount = await page.$$eval(".feed-item.synthetic", (els) => els.length);
  ok(syntheticCount >= 1, `synthetic feed items get the .synthetic dashed-border treatment (found ${syntheticCount})`);
  const badgeText = await page.$eval(".feed-item.synthetic .synthetic-badge", (el) => el.textContent);
  ok(badgeText === "SYNTHETIC", `synthetic feed items show a SYNTHETIC badge (found "${badgeText}")`);

  const liveGrid = await page.$(".live-layer-grid");
  if (liveGrid) {
    await liveGrid.scrollIntoViewIfNeeded();
    await page.waitForTimeout(300); // let the jump animation settle into frame
    await liveGrid.screenshot({ path: path.join(SCREENSHOT_DIR, "site-live.png") });
    console.log("  screenshot: site-live.png");
  }

  // Circuit viewer: click a neuron card, expect detail text to update.
  const firstCard = await page.$(".circuit-card");
  ok(!!firstCard, "circuit viewer rendered at least one neuron card");
  if (firstCard) {
    await firstCard.click();
    const detailText = await page.$eval("#circuit-detail", (el) => el.textContent);
    ok(detailText.includes("body #"), "clicking a neuron shows its real body ID");
  }
  const cardCount = await page.$$eval(".circuit-card", (els) => els.length);
  ok(cardCount === 16, `circuit viewer shows all 16 neurons (found ${cardCount})`);

  // --- Swat demo mode E2E ---
  const presetBtn = await page.$('button:has-text("full loom")');
  ok(!!presetBtn, "swat preset buttons rendered");
  if (presetBtn) await presetBtn.click();

  const swatBtn = await page.$(".swat-btn");
  ok(!!swatBtn, "SWAT button rendered");
  if (swatBtn) {
    await swatBtn.click();
    await page.waitForTimeout(500);
    const verdictText = await page.$eval(".swat-verdict", (el) => el.textContent);
    ok(/IT JUMPED\.|it ignored you\./.test(verdictText), `swat verdict rendered ("${verdictText.trim().slice(0, 60)}")`);
    // Mode-aware honesty label: live deployment shows "on-chain"; a null
    // contractAddress config must show the "pre-deploy simulation" badge.
    const hasContract = await page.evaluate(async () => {
      const { CONFIG } = await import("./config.js");
      return Boolean(CONFIG.contractAddress);
    });
    if (hasContract) {
      ok(verdictText.includes("on-chain"), "swat verdict labeled on-chain (live contract mode)");
    } else {
      ok(verdictText.includes("pre-deploy simulation"), "swat verdict honestly labeled pre-deploy simulation");
    }
  }

  const swatSection = await page.$(".swat-section");
  if (swatSection) {
    await swatSection.scrollIntoViewIfNeeded();
    await swatSection.screenshot({ path: path.join(SCREENSHOT_DIR, "site-swat.png") });
    console.log("  screenshot: site-swat.png");
  }

  // Official tx panel: calldata visible.
  const txSummary = await page.$(".swat-tx-panel summary");
  if (txSummary) {
    await txSummary.click();
    const calldata = await page.$eval(".calldata", (el) => el.textContent.trim());
    ok(/^0xc52ff196/.test(calldata) === false && calldata.startsWith("0x81f2b317"), "swatTx calldata shown with correct selector");
  }

  // --- Mobile viewport smoke test ---
  const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobilePage = await mobileContext.newPage();
  const mobileErrors = [];
  mobilePage.on("console", (msg) => {
    if (msg.type() === "error") mobileErrors.push(msg.text());
  });
  await mobilePage.goto(`${BASE_URL}/index.html`, { waitUntil: "networkidle" });
  await mobilePage.waitForTimeout(1500);
  const heroVisible = await mobilePage.$eval("h1", (el) => el.getBoundingClientRect().width > 0);
  ok(heroVisible, "mobile viewport: hero renders");
  ok(mobileErrors.length === 0, `mobile viewport: zero console errors (found ${mobileErrors.length})`);
  await mobileContext.close();

  // --- METHODS page ---
  const methodsPage = await context.newPage();
  await methodsPage.goto(`${BASE_URL}/methods.html`, { waitUntil: "networkidle" });
  const methodsHeading = await methodsPage.$eval("h1", (el) => el.textContent.trim());
  ok(methodsHeading === "METHODS", "METHODS page loads");
  const sweepRows = await methodsPage.$$eval(".methods table tr", (els) => els.length);
  ok(sweepRows > 5, "METHODS page renders the threshold sweep table");

  ok(consoleErrors.length === 0, `zero console errors on index.html (found ${consoleErrors.length}: ${consoleErrors.slice(0, 3).join(" | ")})`);

  // --- Test-hook gating: must be ABSENT on a normal page load (no query
  // param, config.js default false) ---
  const gatingPage = await context.newPage();
  await gatingPage.goto(`${BASE_URL}/index.html`, { waitUntil: "networkidle" });
  await gatingPage.waitForTimeout(500);
  const hookPresent = await gatingPage.evaluate(() => typeof window.__nandflyTestHook !== "undefined");
  ok(!hookPresent, "window.__nandflyTestHook is NOT present on a normal page load (gated by default)");
  await gatingPage.close();

  await browser.close();

  console.log(`\n${failures === 0 ? "ALL CHECKS PASSED" : `${failures} CHECK(S) FAILED`}`);
  process.exit(failures === 0 ? 0 : 1);
}

main().catch((err) => {
  console.error("E2E script crashed:", err);
  process.exit(1);
});
