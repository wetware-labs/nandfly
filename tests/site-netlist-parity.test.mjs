// Parity test: site/js/netlist.js (the browser evaluator) vs
// contract/fixtures/parity_4096.json (the Python-generated oracle, itself
// produced by circuit/gates.py -- see contract/gen_parity_fixture.py). Checks
// ALL 4096 possible 12-bit stimulus patterns, not a sample, matching the
// rigor of contract/test/parity.test.js (which checks the same fixture
// against the Solidity contract). Three independent implementations
// (Python reference, Solidity contract, this JS evaluator) must all agree.
//
// Uses node:test (consistent with the repo's test style) with 8 subtests of
// 512 patterns each, so a mismatch reports which 512-pattern chunk it fell
// in instead of a single opaque 4096-pattern pass/fail.
//
// Run from the repo root:  node --test tests/site-netlist-parity.test.mjs
// Regenerate the fixture (if circuit/netlists/full.json changes):
//   python contract/gen_parity_fixture.py
// Regenerate site/data/full.json (the vendored copy this test also uses)
// from the same source after any netlist change:
//   node site/scripts/sync-data.mjs

import { test } from "node:test";
import assert from "node:assert/strict";
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

const CHUNK_SIZE = 512;
const CHUNK_COUNT = 8;

test("parity fixture covers all 4096 stimulus patterns", () => {
  assert.equal(fixture.num_patterns, 4096);
  assert.equal(fixture.results.length, 4096);
  assert.equal(CHUNK_SIZE * CHUNK_COUNT, 4096);
});

test("site/js/netlist.js matches circuit/gates.py across all 4096 patterns", async (t) => {
  for (let chunk = 0; chunk < CHUNK_COUNT; chunk++) {
    const start = chunk * CHUNK_SIZE;
    const end = start + CHUNK_SIZE;
    await t.test(`stimulus patterns ${start}-${end - 1}`, () => {
      const failures = [];
      for (let i = start; i < end; i++) {
        const expected = fixture.results[i];
        const { stimulus, jumped, jumpLeft, jumpRight } = expected;
        assert.equal(stimulus, i, `fixture entry ${i} has stimulus ${stimulus}, expected ${i}`);

        const actual = evaluateStimulus(netlist, stimulus);
        const ok = actual.jumped === jumped && actual.jumpLeft === jumpLeft && actual.jumpRight === jumpRight;
        if (!ok) {
          failures.push({
            stimulus,
            expected: { jumped, jumpLeft, jumpRight },
            actual: { jumped: actual.jumped, jumpLeft: actual.jumpLeft, jumpRight: actual.jumpRight },
          });
        }
      }
      assert.deepEqual(failures, [], `${failures.length}/${CHUNK_SIZE} mismatches in this chunk`);
    });
  }
});
