# NANDFLY

**A real fly's escape reflex, rebuilt gate by gate on BNB Chain. It earns nothing. It just refuses to die.**

NANDFLY is the fruit fly's Giant Fiber escape reflex — the circuit that makes a fly nearly impossible to swat — independently derived from a real 166,700-neuron connectome, binarized into NAND/LATCH logic, and deployed as an immutable, ownerless BNB Chain contract. No token. No mining. No yield. The fly cannot pay you back — that's the point.

## Live

- **Contract (verified source):** [`0x3AB7b7621dB958c989B4B628D38B2D3d3642980A`](https://bscscan.com/address/0x3AB7b7621dB958c989B4B628D38B2D3d3642980A#code) — BSC mainnet, born 2026-09-16T07:12:05Z
- **Site (try to swat it):** https://wetware-labs.github.io/nandfly/
- **Methods / derivation walkthrough:** https://wetware-labs.github.io/nandfly/methods.html

Anyone can call `swat(stimulus)` for free (a read-only `eth_call` against the real 661-gate netlist) or `swatTx(stimulus)` on-chain for the public record. The wiring decides: jump, or ignore you.

## The derivation story

This circuit was derived **independently** — no third-party Giant Fiber netlist was read, searched for, or referenced at any point. The process, start to finish:

1. **Extraction** from MaleCNS v1.0's own connectivity data: the Giant Fiber (DNp01), its visual looming inputs (LC4, LPLC2), and its jump motor target (TTMn).
2. **Top-K selection, stated bluntly:** this circuit models **12 of the 311 available LC4/LPLC2 neurons (3.9%)** for this pathway — the top-3 highest-synapse-weight LC4 and top-3 LPLC2 inputs per hemisphere, not the full fan-in.
3. **Quantization + gate compilation:** each kept synapse weight becomes a signed 4-bit magnitude; everything but the two output LATCHes compiles to NAND-only logic (textbook De Morgan identities, a 4-NAND XOR, a 9-NAND full adder, a magnitude comparator), verified by exhaustive truth-table tests. Result: **661 gates (659 NAND + 2 LATCH).**
4. **Equivalence, exhaustive not sampled:** the binarized netlist agrees with an independently-calibrated LIF reference model on **98.9% (4051/4096)** of jump/no-jump decisions, across *all* 4096 possible stimulus patterns the 12 kept inputs can express — every disagreement is a missed jump, zero false jumps. Every threshold rule tried (including ones that score higher) is published, along with why the higher-scoring one was rejected as test-set fitting rather than principled.

Full methods, every rejected design choice, and the honest limitations (including a disclosed sign-map caveat) are in [`circuit/DERIVATION.md`](circuit/DERIVATION.md) and [`reports/equivalence.md`](reports/equivalence.md).

## Trust model

- **Verified source.** The deployed bytecode's source is published and verified on [BscScan](https://bscscan.com/address/0x3AB7b7621dB958c989B4B628D38B2D3d3642980A#code) — read the actual netlist, not just this repo's claims.
- **No admin keys.** No owner, no pausable switch, no upgrade proxy, no constructor argument that changes behavior. This organism belongs to no one.
- **Takes no money.** No `payable` function anywhere, no `receive()`/`fallback()` — a direct BNB transfer is rejected before any application logic runs, and no function exists that can move or use funds. (Like any address, it can still be force-sent dust via `selfdestruct` or airdropped tokens; there is no code path for anyone, including us, to use, move, or recover anything that lands there — it is inert forever.)
- **Constructor-validated netlist.** The full gate netlist is checked on-chain at deployment time (see `NandFlyValidation.sol`) — "the chain checked it," not just "trust the script."
- **Reproducible pipeline.** Every step from raw connectome data to deployed bytecode is scripted and reproducible (see below); three independent implementations — the Python reference, the Solidity contract, and the site's JS evaluator — agree bit-for-bit across all 4096 possible stimulus patterns.

## Birth milestone: alive but unborn

The deployed contract is real, live, and swattable today — but it is not yet **born** in the biological sense this project means it. Birth is a real physical event: a 7-cell fragment of this circuit (6 NAND + 1 LATCH), fabricated as an actual circuit in the [TapeOut](https://tapeout.work) NAND-gate fab, minted publicly once the community funds it.

- **Goal: $30** (the current fab-quoted cost of the 7-cell mint).
- **Feeding wallet:** [`0x14Ab88CF91376451a24179C41965D1f24269e3a6`](https://bscscan.com/address/0x14Ab88CF91376451a24179C41965D1f24269e3a6) — published here, before any inflow.
- **Policy, locked before the first donation ever arrives:** 80% of every inflow buys components (every purchase = an on-chain receipt); 20% keeps the lab running. Equal treatment for all inflows — no per-token deals, no endorsements. Third parties may route their own token taxes to this wallet at their own discretion; we do not solicit or promote any token. If the 80% falls short of the mint cost when prices move, we cover the gap ourselves.
- **Pre-launch balance disclosure:** the wallet's small starting balance is our own deploy-gas float, not donations — the 80/20 policy counts inflows from launch onward.
- Every subsequent addition follows the real anatomy: **16 / 166,700 neurons on-chain today.** The unfinishable goal is the point.

## Parallel work

[BruceLanLan/c3s-reflex-circuits](https://github.com/BruceLanLan/c3s-reflex-circuits) is an independent derivation of the same biological circuit. We never read their netlist, before or during this work — NANDFLY's design choices (top-K selection, quantization, threshold rule, gate decomposition) were all made by inspecting MaleCNS v1.0 directly and the published GF-pathway literature. We're crediting this as genuine convergent, independent effort, not a race to claim "first."

## Credits

- **Connectome data:** MaleCNS v1.0 — FlyEM @ HHMI Janelia, University of Cambridge, MRC LMB, and Google Research.
- **Binarization pipeline lineage:** DOOMFLY-lineage tooling (MIT license) — this repo's Arrow Feather reader and node-retention policy build on that project's public code, reused verbatim/adapted with attribution, not copied blind.

## Reproduce it

```bash
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # Scripts/ on Windows, bin/ elsewhere

# 1. Extract the GF core subgraph from a local copy of MaleCNS v1.0's raw
#    feather files (public download: storage.googleapis.com/flyem-male-cns).
python -m circuit.extract --raw-dir <path-to-malecns_v1> --out circuit/data/subgraph.json

# 2. Binarize into full.json (661-gate deployed netlist) and seed.json (7-cell fragment).
python -m circuit.binarize

# 3. Run the equivalence check and regenerate reports/equivalence.md.
python -m circuit.equivalence

# Unit tests (fast, no MaleCNS data required):
python -m pytest

# Contract: compile, run the full local + 4096-pattern parity test suite.
cd contract && npm install && npx hardhat compile && npx hardhat test

# Site: local static server + Playwright E2E (zero-dep vanilla JS site).
node site/scripts/serve.mjs 8934
node site/scripts/e2e.mjs
```

See [`contract/DEPLOY.md`](contract/DEPLOY.md) for the exact deployment procedure used for the live mainnet contract, and [`site/methods.html`](site/methods.html) for the full derivation walkthrough with every rejected threshold-rule value published.

## License

MIT — see [`LICENSE`](LICENSE).
