# TapeOut cost quote

Generated: 2026-09-16T05:25:29.277424+00:00 (live re-fetch of BNB/USD, processor registry, and BSC gas price -- see tapeout/quote.py)

**Price-volatility caveat:** every number below is a point-in-time snapshot. BNB/USD and BSC gas price were re-fetched live for this run; NAND/LATCH secondary-market prices were NOT (see snapshot below, dated 2026-09-01) -- component prices on this platform have moved >20%/day on documented occasions (see feasibility spike findings.md section 1). Treat all totals as order-of-magnitude, not a firm quote, until re-run immediately before any real spend (Task 5).

## Live inputs

- BNB/USD: **$714.52** (CoinGecko, live)
- TapeOut fab primary mint price: 0.0005 BNB/unit, minted 1,000,000 / 1,000,000 (SOLD OUT -- primary mint unavailable, secondary market required)
- BSC gas price: 0.05 gwei (live eth_gasPrice)
- NAND secondary best-bid: 0.006 BNB (~$4.29), LATCH: 0.00487 BNB (~$3.48) -- **snapshot dated 2026-09-01, NOT live-refreshed this run** (source: understand-tapeout.netlify.app (community order-book explainer), cross-referenced against market contract 0x6feebbebc07bcb90bd1ac8b0cf9baa4f0ff2b46f)

## Quote table

Gas is a **rough estimate**: calldata cost (16 gas/byte, live gas price) plus an UNCONFIRMED 150,000-gas allowance for mint bookkeeping -- the exact tape-out/mint write function was not identified from bytecode probing (only the read functions netlist()/circuitInfo() were; see tapeout/SUBMISSION.md). Cross-check against the feasibility spike's own $2-10/tx estimate (BSC gas is cheap regardless of the exact function).

| Circuit | Gates (NAND+LATCH) | Netlist bytes (est.) | Component cost | Gas (est.) | **Total** |
|---|---|---|---|---|---|
| seed, naive "2 NAND + 1 LATCH" gate count | 3 | 21 | 0.01687 BNB ($12.05) | 0.000009 BNB ($0.0061) | **0.01688 BNB ($12.06)** |
| **seed, TRUE on-chain cost (8 NAND + 1 LATCH primitives -- see note below)** | 9 | 60 | 0.05287 BNB ($37.78) | 0.000009 BNB ($0.0061) | **0.05288 BNB ($37.78)** |
| hypothetical 10 gates (8 NAND + 2 LATCH, illustrative mix) | 10 | 64 | 0.05774 BNB ($41.26) | 0.000009 BNB ($0.0061) | **0.05775 BNB ($41.26)** |
| hypothetical 50 gates (46 NAND + 4 LATCH, illustrative mix) | 50 | 338 | 0.29548 BNB ($211.13) | 0.000009 BNB ($0.0063) | **0.29549 BNB ($211.13)** |
| hypothetical 100 gates (94 NAND + 6 LATCH, illustrative mix) | 100 | 682 | 0.59322 BNB ($423.87) | 0.000009 BNB ($0.0065) | **0.59323 BNB ($423.87)** |

**Important correction to the project's earlier "~$12, 2N+1L" estimate** (docs/plans/2026-09-16-nandfly-mvp.md progress ledger): our LATCH gate is an SR-latch, and TapeOut's only native stateful primitive is a single-input D-register -- it cannot express SR set/reset semantics as a bare primitive. Reproducing the seed's exact behavior therefore costs 1 native LATCH + 4 extra NAND primitives (tapeout/format.py's module docstring has the derivation), REGARDLESS of submission path: a canvas build would need those same 4 NAND gates hand-wired, not just a direct-bytes one. The naive "2N+1L" row above understates the real cost; use the "TRUE on-chain cost" row for budgeting.

## Notes

- Component prices assume the cheapest liquid fab (TapeOut) best-bid, not ask/depth -- buying in bulk may walk the book higher (see spike findings.md caveats).
- Hypothetical 10/50/100-gate rows use the naive gate count (their NAND/LATCH split is already illustrative/assumed, not a real design), for order-of-magnitude comparison only.
- Re-run `python -m tapeout.quote` immediately before Task 5's real spend for fresh numbers.
