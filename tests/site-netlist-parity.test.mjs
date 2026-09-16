// Parity test: site/js/netlist.js (the browser evaluator) vs
// contract/fixtures/parity_4096.json (the Python-generated oracle, itself
// produced by circuit/gates.py -- see contract/gen_parity_fixture.py). Checks
// ALL 4096 possible 12-bit stimulus patterns, not a sample, matching the
// rigor of contract/test/parity.test.js (which checks the same fixture
// against the Solidity contract). Three independent implementations
// (Python reference, Solidity contract, this JS evaluator) must all agree.
//
// Run from the repo root:  node tests/site-netlist-parity.test.mjs
// Regenerate the fixture (if circuit/netlists/full.json changes):
//   python contract/gen_parity_fixture.py
// Regenerate site/data/full.json (the vendored copy this test also uses)
// from the same source after any netlist change:
//   node site/scripts/sync-data.mjs

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { evaluateStimulus } from "../site/js/netlist.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

const netlistPath = path.join(REPO_ROOT, "site", "data", "full.json");
const fixturePath = path.join(REPO_ROOT, "contract", "fixtures", "parity_4096.json");

const netlist = JSON.parse(readFileSync(netlistPath, "utf-8"));
const fixture = JSON.parse(readFileSync(fixturePath, "utf-8"));

if (fixture.num_patterns !== 4096) {
  console.error(`FAIL: fixture claims ${fixture.num_patterns} patterns, expected 4096`);
  process.exit(1);
}

let pass = 0;
let fail = 0;
const failures = [];

for (const expected of fixture.results) {
  const { stimulus, jumped, jumpLeft, jumpRight } = expected;
  const actual = evaluateStimulus(netlist, stimulus);
  const ok =
    actual.jumped === jumped &&
    actual.jumpLeft === jumpLeft &&
    actual.jumpRight === jumpRight;
  if (ok) {
    pass += 1;
  } else {
    fail += 1;
    if (failures.length < 10) {
      failures.push({ stimulus, expected, actual: { jumped: actual.jumped, jumpLeft: actual.jumpLeft, jumpRight: actual.jumpRight } });
    }
  }
}

console.log(`site-netlist-parity: ${pass}/${fixture.num_patterns} patterns match the Python oracle`);
if (fail > 0) {
  console.error(`FAIL: ${fail} mismatches. First ${failures.length}:`);
  for (const f of failures) {
    console.error(JSON.stringify(f));
  }
  process.exit(1);
}
console.log("PASS: JS evaluator is bit-for-bit parity with circuit/gates.py across all 4096 stimulus patterns.");
