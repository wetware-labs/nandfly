/**
 * Parity spot-check against a LIVE deployed NandFly contract (Task 5 post-deploy
 * verification step -- see contract/DEPLOY.md). Reads the same
 * contract/fixtures/parity_4096.json fixture the local test suite checks all
 * 4096 patterns against (generated from circuit/gates.py -- the reference
 * evaluator, independent of the Solidity implementation), calls swat() on the
 * live address for a sample of patterns, and reports any mismatch.
 *
 * By default this checks a curated sample (fast, cheap in RPC calls: edge
 * cases + a deterministic-but-spread pseudo-random sample) rather than all
 * 4096 -- a full re-verification of all 4096 already happened locally in
 * test/parity.test.js before deployment; this script's job is to confirm the
 * bytecode that actually got deployed and verified on BscScan behaves
 * identically to what was tested, not to re-derive that fact from scratch
 * against a real RPC endpoint (slow, and costs the RPC provider's rate limit).
 * Pass NANDFLY_FULL=1 to check all 4096 patterns instead.
 *
 * Usage:
 *   NANDFLY_ADDRESS=0xYourDeployedAddress npx hardhat run scripts/parity_check.js --network bsc
 *   NANDFLY_ADDRESS=0x... NANDFLY_SAMPLE=500 npx hardhat run scripts/parity_check.js --network bsc
 *   NANDFLY_ADDRESS=0x... NANDFLY_FULL=1 npx hardhat run scripts/parity_check.js --network bsc
 *
 * Also runs fine against the local Hardhat/localhost network for a dry run:
 *   npx hardhat run scripts/deploy.js
 *   NANDFLY_ADDRESS=<address printed above> npx hardhat run scripts/parity_check.js
 */
const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

const DEFAULT_SAMPLE_SIZE = 200;

function pickSample(results, sampleSize) {
  const edgeCases = [0, 4095];
  const picked = new Map();
  for (const s of edgeCases) {
    picked.set(s, results[s]);
  }
  // Deterministic, spread-out pseudo-random sample (not cryptographic; just
  // wants even coverage across the 4096-pattern space without re-checking all
  // of it on a metered RPC endpoint).
  const step = Math.max(1, Math.floor(results.length / sampleSize));
  for (let i = 0; i < results.length && picked.size < sampleSize; i += step) {
    picked.set(results[i].stimulus, results[i]);
  }
  return Array.from(picked.values());
}

async function main() {
  const address = process.env.NANDFLY_ADDRESS;
  if (!address) {
    throw new Error(
      "Set NANDFLY_ADDRESS to the deployed NandFly contract address, e.g.\n" +
        "  NANDFLY_ADDRESS=0x... npx hardhat run scripts/parity_check.js --network bsc"
    );
  }

  const fixturePath = path.join(__dirname, "..", "fixtures", "parity_4096.json");
  const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf-8"));

  const full = process.env.NANDFLY_FULL === "1";
  const sampleSize = process.env.NANDFLY_SAMPLE
    ? parseInt(process.env.NANDFLY_SAMPLE, 10)
    : DEFAULT_SAMPLE_SIZE;
  const patterns = full ? fixture.results : pickSample(fixture.results, sampleSize);

  console.log(`Network: ${hre.network.name}`);
  console.log(`Contract: ${address}`);
  console.log(`Checking ${patterns.length} of ${fixture.results.length} stimulus patterns...`);

  const nandfly = await hre.ethers.getContractAt("NandFly", address);

  // Sanity: metadata should exist and GATE_COUNT should be 661 before spending
  // any more RPC calls on the actual parity sample.
  const gateCount = await nandfly.GATE_COUNT();
  if (gateCount.toString() !== "661") {
    throw new Error(
      `GATE_COUNT() returned ${gateCount.toString()}, expected 661 -- is this address really a NandFly deployment?`
    );
  }
  console.log(`GATE_COUNT() = ${gateCount.toString()} (ok)`);
  console.log(`SPECIES() = ${await nandfly.SPECIES()}`);
  console.log(`bornAt() = ${await nandfly.bornAt()}`);

  let mismatches = [];
  let checked = 0;
  const BATCH = 25;
  for (let start = 0; start < patterns.length; start += BATCH) {
    const batch = patterns.slice(start, start + BATCH);
    const outcomes = await Promise.all(batch.map((row) => nandfly.swat(row.stimulus)));
    for (let i = 0; i < batch.length; i++) {
      const row = batch[i];
      const [jumped, jumpLeft, jumpRight] = outcomes[i];
      checked += 1;
      if (jumped !== row.jumped || jumpLeft !== row.jumpLeft || jumpRight !== row.jumpRight) {
        mismatches.push({ stimulus: row.stimulus, expected: row, got: { jumped, jumpLeft, jumpRight } });
      }
    }
    process.stdout.write(`\r  checked ${checked}/${patterns.length}`);
  }
  console.log("");

  if (mismatches.length > 0) {
    console.error(`FAIL: ${mismatches.length}/${checked} mismatches:`);
    console.error(mismatches.slice(0, 20));
    process.exitCode = 1;
    return;
  }

  console.log(`PASS: ${checked}/${checked} patterns matched circuit/gates.py's reference output.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
