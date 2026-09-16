# TapeOut submission plan for seed.json

Status: **format decode/encode CERTAIN, mint/write path NOT CERTAIN.** This
document is deliberately honest about that split rather than papering over
it -- see "Format-certainty verdict" at the end, and the recommended Task 5
pre-step.

## 1. What we confirmed, and how

### 1.1 The contract

The "TapeOut" fab/circuit-registry, per the live processor registry
(`https://tapeout-public-monitor.tapeout-labs.workers.dev/api/v1/processors`,
`name == "TapeOut"`, 100% minted, 14,258 circuits as of 2026-09-16):

- Proxy address (what you call): `0xb1024b89886b9a34aa4ff5f31c411d708b20a14c`
- BNB Smart Chain mainnet, chain id `56`
- The proxy is a minimal beacon-clone: it reads `masterCopy()` from a
  hardcoded registry (`0xf8d6d8eb894d6971c8976ad8b4971cbefe028156`), which
  currently resolves to implementation `0x8e1d125def6d3826c278299273a0760d47626068`
  (shared by every processor fab -- confirmed by decompiling the proxy's own
  bytecode, not by trusting any third-party doc).
- **Not verified on BscScan.** No first-party ABI/source is public.

### 1.2 The read-path ABI (CONFIRMED by live on-chain calls)

Since the contract is unverified, its ABI was independently recovered:

1. Fetched the implementation contract's bytecode via `eth_getCode`.
2. Extracted every `PUSH4` operand from the dispatcher (Solidity's standard
   `if selector == 0x... { ... }` pattern compiles to `PUSH4 <selector>`).
3. Hashed ~70 candidate English function signatures with a from-scratch,
   dependency-free Keccak-256 implementation (`tapeout/_keccak.py`, no
   web3.py/pycryptodome in requirements.txt) and matched the first 4 bytes
   against the harvested operands.

This positively matched:

| Function | Selector | Confirmed by |
|---|---|---|
| `netlist(uint256) returns (bytes)` | `0x3fc4be56` | present in bytecode; called live, returned real netlist bytes for 2 different circuits |
| `circuitInfo(uint256) returns (uint256 n_inputs, uint256 n_outputs, uint256 n_state, uint256 n_cells)` | `0x084d60f1` | present in bytecode; its `(n_cells, n_state)` matched our own independent byte-level decode of `netlist()`'s output exactly, for both circuits |
| `ownerOf(uint256) returns (address)` | `0x6352211e` | standard ERC-721 selector, present, returns real owner addresses |
| `eval(uint256,bytes)` | `0x934d06ea` | present in bytecode; **not called** (unknown argument encoding beyond the name match -- see "not confirmed" below) |

Reproducible via `python -m tapeout.verify --discover-abi` (live network).

### 1.3 The byte format (CONFIRMED for OP_NAND and OP_LATCH)

`tapeout/format.py`'s module docstring has the full layout and derivation.
Summary: opcode-tagged cells (`0x00`=NAND, `0x01`=LATCH, `0x02`=REF) over a
flat, append-only signal space (0=const0, 1=const1, then inputs, then one
signal per cell output). This was cross-checked two independent ways:

1. **Documentation**: the third-party project named in the feasibility spike
   (`C:\Users\gmldn\Documents\Codex\_spikes\tapeout-fly-spike\findings.md`
   section 3), `github.com/BruceLanLan/c3s-reflex-circuits` (Apache-2.0),
   documents this exact layout in its generic wire-format module
   `c3s/netlist.py`. We read only that generic module (and its generic
   on-chain-verification script) -- never the project's fly-circuit-specific
   files -- consistent with this project's independent-derivation rule
   (`docs/plans/2026-09-16-nandfly-mvp.md`); a wire protocol is not
   connectome data.
2. **Real on-chain data (this project's own check, 2026-09-16)**: fetched
   and decoded two already-minted circuits from the live TapeOut processor
   via public read-only RPC (`https://bsc-dataseed.binance.org`, no wallet,
   no tx, no gas):
   - Token **#1**: 3 NAND cells, 2 inputs, 1 output, 0 latches. Bytes:
     `0x000000020000030000000400000400000005000005`. Exercises OP_NAND.
   - Token **#5000**: 1 NAND + 9 LATCH cells, 0 inputs, 8 outputs -- a
     9-stage ring counter whose first LATCH's `d` forward-references the
     9th LATCH's output signal, defined 9 cells later. Exercises OP_LATCH
     and the "`d` may point anywhere" rule.

   Both are committed as fixtures (`tapeout/fixtures/onchain_circuit_1.json`,
   `tapeout/fixtures/onchain_circuit_5000.json`, each with full `source`
   provenance: contract, chain id, token id, RPC endpoint, fetch timestamp,
   ABI-recovery method) and covered by `tests/test_tapeout_onchain_fixture.py`
   (no network needed to re-run that test -- it decodes the committed bytes).

**Not confirmed by real data: OP_REF.** No real fixture we found uses a REF
cell; the byte layout for it is transcribed from the documentation source
only. Irrelevant to this project either way -- our encoder never emits REF.

### 1.4 Our LATCH is not TapeOut's LATCH (read this before minting)

circuit/SCHEMA.md's LATCH is a level-triggered SR-latch (2 inputs, combinational
within a tick). TapeOut's native LATCH is a single-input D-register (output
fixed to the previous tick's stored value for the whole current tick).
`encode_netlist` compiles each of our LATCH gates to 1 native LATCH cell + 4
NAND cells implementing `q = NOT(NAND(reset_n, NAND(set_n, NOT(p))))`, proven
(a) structurally correct via round-trip tests, and (b) *semantically* correct
via an exhaustive check over all 8 `(set_n, reset_n, previous_Q)` combinations
against `circuit/gates.py`'s own evaluator
(`tests/test_tapeout_format.py::test_latch_translation_matches_our_sr_latch_truth_table_exhaustively`),
plus a full two-tick protocol check across all 16 input combinations of
seed.json specifically
(`test_seed_two_tick_protocol_matches_our_evaluator_for_every_input_combination`).

**Cost consequence** (see `reports/tapeout-quote.md`, regenerate with
`python -m tapeout.quote`): the seed's TRUE on-chain primitive cost is
**8 NAND + 1 LATCH (9 primitives)**, not the "2 NAND + 1 LATCH (3
primitives)" framing used in the project's earlier budget ruling
(`docs/plans/2026-09-16-nandfly-mvp.md`'s progress ledger, "~$12"). This is
not a direct-bytes-submission artifact -- a canvas build would need the same
4 extra NAND gates hand-wired to reproduce the exact SR-latch behavior,
since the canvas's own LATCH primitive is the same native D-register. At
current secondary-market prices this is closer to **~$38**, not ~$12 (see
the quote report's "TRUE on-chain cost" row).

## 2. What we could NOT confirm: the mint/write function

Extracting the read-path ABI (section 1.2) from the bytecode dispatcher did
**not** turn up a plausible mint/tape-out write-function selector. We tried
~70 candidate signatures across common verb/argument-shape combinations
(`tapeOut(bytes,uint256,uint256)`, `mint(bytes,uint256,uint256,uint256)`,
`createCircuit(...)`, etc. -- see the brute-force list in the research
transcript for this task) against the ~44 still-unidentified `PUSH4`
operands in the dispatcher; none matched. Plausible explanations: the write
path lives on a different contract (a separate "canvas submission"/factory
contract we have not identified), takes a parameter shape/name we did not
guess, or is gated behind logic we cannot see from a static dispatcher scan
alone (e.g. only reachable via a proxy-specific entry point).

**We did not attempt to call any write function** -- this task is
read-only-RPC by explicit constraint, and blind-guessing a write call
against a real contract holding real value is exactly the kind of
irreversible mistake that constraint exists to prevent.

## 3. Submission path

### 3.1 Recommended: manual canvas (primary route)

Given section 2, the safe, confirmed-working path for Task 5 is the
`tapeout.net` "Processor Canvas System" (drag NAND/LATCH primitives, wire
them, free to build/test, gas spent only on the final Tape Out tx -- see
spike findings.md section 3). Concretely, for seed.json:

1. Place 2 input pins (`g326`, `reset`) and 1 output pin (`jump_left`).
2. Place 2 NAND primitives: `g327 = NAND(reset, reset)`, `g328 = NAND(g326, g327)`.
3. Reproduce the SR-latch: place 1 native LATCH primitive plus the 4-NAND
   translation network from section 1.4, using this fragment's own `g327`
   (reset_n) and `g328` (set_n) as the two logical inputs, and wire the
   translation's final NAND (`q`) to the `jump_left` output pin. (Concretely,
   with `p` = the LATCH primitive's own output: `g1=NAND(p,p)`,
   `g2=NAND(g328,g1)`, `g3=NAND(g327,g2)`, `g4=NAND(g3,g3)`; wire the LATCH's
   `d` input to `g4`, and `jump_left` output to `g4`.)
4. Submit the Tape Out transaction (small BNB gas, ~$2-10 per spike
   findings.md; component cost per section 1.4/reports/tapeout-quote.md).

### 3.2 Direct contract call (documented, marked NOT CERTAIN)

If/when the write function is identified (or the canvas's own submitted
transaction is inspected on BscScan to recover it empirically -- the
cleanest way to close this gap, see "Task 5 pre-step" below), the encoded
bytes to submit for seed.json are:

- **Contract**: `0xb1024b89886b9a34aa4ff5f31c411d708b20a14c` ("TapeOut" fab, BSC mainnet, chain id 56)
- **n_inputs**: 2, **n_outputs**: 1, **n_state** (latches): 1, **n_cells**: 9
- **Netlist bytes** (60 bytes), produced by `tapeout.format.encode_netlist(seed_json)`:

```
0x00000003000003000000020000040100000a000000060000060000000500000700000004000008000000090000090000000a00000a0000000b00000b
```

Hex dump (7-byte NAND cells / 4-byte LATCH cell, annotated):

```
00 000003 000003   NAND  sig4  = NAND(3, 3)          # g327 = NAND(reset, reset)   [reset is input signal 3]
00 000002 000004   NAND  sig5  = NAND(2, 4)          # g328 = NAND(g326, g327)     [g326 is input signal 2]
01 00000a           LATCH sig6  = LATCH(d=10)         # jump_left's native LATCH cell (d backpatched to g4 below)
00 000006 000006   NAND  sig7  = NAND(6, 6)          # g1 = NOT(p)
00 000005 000007   NAND  sig8  = NAND(5, 7)          # g2 = NAND(set_n=g328, g1)
00 000004 000008   NAND  sig9  = NAND(4, 8)          # g3 = NAND(reset_n=g327, g2)
00 000009 000009   NAND  sig10 = NAND(9, 9)          # g4 = NOT(g3) = q  (jump_left's real value)
00 00000a 00000a   NAND  sig11 = NAND(10, 10)        # output buffer 1/2
00 00000b 00000b   NAND  sig12 = NAND(11, 11)        # output buffer 2/2 -- the actual output signal
```

(Regenerate at any time: `python -c "import json; from tapeout import format as tf; print(tf.to_hex(tf.encode_netlist(json.load(open('circuit/netlists/seed.json')))[0]))"`.)

**We do NOT have a confirmed mint function signature or argument order to
submit this with.** Do not attempt a direct write call against the real
contract without first closing that gap (see below).

## 4. Recommended Task 5 pre-step: a tiny canvas-made test circuit

Before the real seed mint, per this task's own instruction to flag format
uncertainty rather than paper over it:

1. On `tapeout.net`'s canvas, build and tape out a **tiny throwaway test
   circuit** that exercises the same structural pattern as our seed's
   trickiest part (1 native LATCH + a short NAND feedback network, e.g. just
   the 4-NAND SR-translation above with 2 dummy inputs) -- cheap (a handful
   of primitives, sub-$10 all in).
2. Fetch it back with `tapeout.verify.fetch_onchain_circuit` (now-confirmed
   read path) and decode it with `tapeout.format.decode_circuit`. Confirm
   the decoded structure exactly matches what the canvas UI reported before
   submission (gate counts, wiring).
3. Inspect that mint transaction on BscScan (now that we know a real
   token id / tx hash to look at) to read its `input` calldata: the first 4
   bytes are the real mint-function selector, and the ABI-encoded argument
   layout is directly visible from there -- closing the section 2 gap
   empirically, without guessing against a live contract.
4. Only then attempt the direct-contract-call path (3.2) for future gates,
   if desired; the actual seed mint can proceed via canvas either way.

## 5. Independent re-verification after minting

Once seed.json (or the pre-step test circuit) is minted, re-verify it is
really on-chain and really what we intended, using nothing but our own code:

1. `tapeout.verify.fetch_onchain_circuit(rpc, PROCESSOR_ADDRESS, our_token_id)`
   -- fetches `netlist()` + `circuitInfo()` for the real minted token id.
2. `tapeout.format.decode_circuit(bytes, n_inputs, n_outputs).describe()`
   -- structural sanity report (gate/latch counts must be 9 cells, 8 NAND +
   1 LATCH, matching section 1.4).
3. Byte-for-byte: the fetched `netlist_hex` must equal the exact hex dump in
   section 3.2 above (this is the strongest check -- if the canvas UI
   produced different wiring for logically-equivalent gates, this would
   catch it, even though `describe()`'s counts alone would not).
4. Semantic replay: feed the same two-tick reset+stimulus test vectors used
   in `tests/test_tapeout_format.py` through `tapeout.format.tick()` against
   the freshly-decoded on-chain `Circuit`, and confirm they still match
   `circuit/gates.py::evaluate_netlist`'s output for seed.json -- proving the
   MINTED circuit, not just our local encoding of it, behaves as intended.

## 6. Format-certainty verdict

**CERTAIN**: the TapeOut netlist byte format's OP_NAND and OP_LATCH opcodes,
our encoder/decoder's correctness for netlists built from those two
primitives (structural round-trip + exhaustive semantic equivalence, all
locally testable, no network needed --
`tests/test_tapeout_format.py`), and the `netlist()`/`circuitInfo()`
read-path ABI (confirmed against 2 independent real on-chain circuits,
`tests/test_tapeout_onchain_fixture.py`).

**NOT CERTAIN / NEEDS-CANVAS-TEST**:
- OP_REF's byte layout (unused by this project; no real fixture found).
- The mint/tape-out write function's signature and argument encoding --
  **this is the actual gap for Task 5**, not the byte format. Close it via
  section 4's pre-step (a cheap canvas-built test circuit + reading its real
  mint tx's calldata on BscScan) before attempting any direct contract call,
  or simply use the canvas path (3.1) throughout and skip 3.2 entirely.
- Whether the mint function's component accounting is per-raw-cell (8 NAND +
  1 LATCH held, per section 1.4) or some other scheme -- also closed by the
  section 4 pre-step.
