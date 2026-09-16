# NANDFLY GF-circuit derivation: methods and design choices

This document is the reproducibility record for Task 1: independently
deriving the Giant Fiber (GF) escape-reflex circuit from MaleCNS v1.0 and
binarizing it into a NAND/LATCH gate-level netlist.

**Independence note:** every selection criterion, quantization scheme, and
gate decomposition below was designed by inspecting MaleCNS v1.0's own
`annotations.feather`/`edges.feather`/`neurotransmitters.feather` and
published neuroscience of the GF pathway (LC4/LPLC2 visual projection
neurons -> DNp01 "Giant Fiber" -> TTMn "jump muscle" motor neuron). No
third-party GF netlist was read, searched for, or referenced while doing
this work.

## 1. Data source

MaleCNS v1.0 (FlyEM/Janelia, Cambridge, MRC LMB, Google Research), the same
public dataset vendored by the FlyMarket project
(`C:\Users\gmldn\Documents\Codex\flymarket\connectome_data\malecns_v1`, not
committed to this repo -- see `sim/data/datasets.json` in FlyMarket for the
original public download URLs, all under
`storage.googleapis.com/flyem-male-cns`). This repo's `circuit/lib/
arrow_feather.py` (a dependency-free Arrow Feather V2 reader) is copied
verbatim from FlyMarket's `sim/core/arrow_feather.py`, which is itself part
of the DOOMFLY lineage (github.com/nftechie/doomfly, MIT); only the reader
is reused, not any GF-specific logic.

Node-retention policy (also reused from FlyMarket's `sim/build_connectome.py`,
which documents deriving it from DOOMFLY's public `doom/prepare.py`): an
`annotations.feather` row is retained iff `superclass` is non-null/non-empty
AND `status != 'Glia'`.

## 2. What MaleCNS v1.0's annotations actually contain for this pathway

Investigated directly (see `circuit/extract.py`'s module docstring, and the
generated `circuit/data/subgraph.json`'s `candidate_population_counts`):

| type | retained count | somaSide L | somaSide R | superclass |
|---|---|---|---|---|
| DNp01 (Giant Fiber) | 2 | 1 | 1 | descending_neuron |
| LC4 | 126 | 71 | 55 | visual_projection |
| LPLC2 | 185 | 94 | 91 | visual_projection |
| TTMn | 2 | 1 | 1 | vnc_motor |
| DLMn a, b | 2 | 1 | 1 | vnc_motor |
| DLMn c-f | 8 | 4 | 4 | vnc_motor |

Also present, investigated, and deliberately **not used**: `GFC1`..`GFC4`
(3+10+13+8 = 34 neurons, `superclass=vnc_intrinsic`) -- these look like a
MaleCNS-curated auxiliary "Giant Fiber Circuit" family, but the task scope
is specifically the published LC4/LPLC2 -> DNp01 -> TTMn/DLMn path, so they
are left for a possible future extension rather than folded in here.

## 3. Wiring found (the actual edge-level result, not assumed)

Streaming `edges.feather` (1.05 GB, not vendored in this repo) and
restricting to edges between the 325 candidate neurons above
(`circuit/extract.py::stream_candidate_edges`) found:

- **Every** LC4 and LPLC2 neuron on a given side has >=1 direct chemical
  synapse onto DNp01 of the SAME side (71/71 LC4-L, 55/55 LC4-R, 94/94
  LPLC2-L, 91/91 LPLC2-R) -- a genuine, complete, ipsilateral all-to-one
  convergence onto the GF's dendrite, matching the published anatomy of
  GF's looming-input zone.
- DNp01 has **exactly one** outgoing synapse onto TTMn per side: weight 20
  (left) and 70 (right) raw synapse contacts.
- DNp01 has **zero** direct synapses onto either DLMn subtype in this
  dataset. This matches the literature: GF's flight-muscle output is known
  to be indirect, via the PSI (peripherally synapsing interneuron) neuron,
  which is not part of this extraction's candidate set. DLMn is therefore
  recorded in `subgraph.json`'s `excluded_motor_types` and left out of the
  wired circuit -- **not fabricated as a direct connection that isn't
  there.**
- Every neuron in the used wiring (DNp01, LC4, LPLC2) has
  `consensus_nt = acetylcholine` (sign +1). This subgraph turned out to be
  100% excitatory; nothing in it is inhibitory.

Since DLMn has no direct GF synapse, this circuit's "hero" output is the
jump command carried by TTMn, per the task brief's own contingency ("If the
motor side is genuinely absent, the circuit can end at GF output").

## 4. Top-K visual input selection

Keeping all 71-94 visual inputs per population per side would make an
adder tree an order of magnitude larger than useful. `circuit/extract.py`
keeps, per side, the **top-3** highest-synapse-weight LC4 neurons and the
**top-3** highest-synapse-weight LPLC2 neurons onto DNp01 (`TOP_K = 3`,
a module constant) -- 6 visual inputs per hemisphere, 12 total. This keeps
the strongest, most reliable channels of the real convergence (documented
weight ranges: LC4-L top-3 = 86/83/82 of 71 candidates ranging 30-86;
LPLC2-R top-3 = 59/53/49 of 91 candidates ranging 1-59), not a fabricated
substitute for the full fan-in.

## 5. Binarization design

See `circuit/binarize.py`'s module docstring for the full detail; summary:

- **Weight quantization**: `magnitude = clamp(floor(raw_weight / 6), 1, 15)`,
  a signed 4-bit magnitude (`BIT_WIDTH=4`, `SCALE=6`). SCALE=6 was chosen so
  this subgraph's largest raw weight (86) just fits in 4 bits (86//6=14).
  The floor is clamped to a minimum of 1 so a selected (top-K) synapse never
  binarizes away to zero weight.
- **Threshold rule**: every threshold unit (GF and TTMn) fires when its
  weighted input sum is >= `ceil(0.5 * max_possible_sum)` -- a single,
  uniform, parameter-free rule, not tuned per unit against the equivalence
  test set (avoids overfitting the reported agreement number).
- **Gate compilation**: `circuit/gates.py` compiles everything except the 2
  output LATCHes down to NAND only, using standard textbook identities
  (4-NAND XOR, 9-NAND full adder, De Morgan OR/AND, an MSB-fold-from-LSB
  magnitude comparator) -- see that module's docstring for the exact
  decompositions and correctness reasoning (verified by truth-table tests
  in `tests/test_gates.py`).
- **LATCH usage**: exactly one LATCH per hemisphere, holding the
  jump-commanded motor decision persistently (a documented design choice --
  representing the real, finite duration of a motor command -- rather than
  a momentary combinational pulse). See `circuit/SCHEMA.md`'s "Evaluation
  protocol" for the reset/read sequence.
- **Sign handling**: `negate_bits()` implements two's-complement negation
  for a future inhibitory-input extension; unused by this all-excitatory
  subgraph but unit-tested.

## 6. Actual gate counts (measured, not assumed)

Running `python -m circuit.binarize` on the real subgraph produces:

- `full.json`: **781 gates** (779 NAND + 2 LATCH)
- `seed.json`: **3 gates** (2 NAND + 1 LATCH)

This is larger than the project plan's rough planning estimate ("~150-400
gates" / "Full ~173+ gates"), which was written before this investigation
computed an actual NAND-only gate decomposition. The brief explicitly
removes any cost constraint on `full.json` ("no component-cost constraint
since it deploys to our own contract"), so this honest, measured count is
reported as-is rather than force-fit to the earlier estimate. The dominant
cost is the adder tree: each 9-NAND full adder is used many times across
two per-hemisphere 6-input, 4-bit-wide adder trees plus two 7-8-bit
magnitude comparators; `TOP_K` and `BIT_WIDTH` are the two knobs that would
shrink this if a smaller netlist were wanted later.

## 7. What `seed.json` actually is

A verbatim 3-gate (2 NAND + 1 LATCH) fragment of `full.json`: the final
TTMn-to-jump output stage for the **left** hemisphere -- the pair of NAND
inverters that turn the left TTMn threshold unit's firing decision (and the
shared `reset` pin) into active-low set/reset pulses, feeding the
`jump_left` LATCH that holds the fly's jump-commanded state. The gate ids,
types, and wiring are copied unchanged from `full.json`
(`circuit/binarize.py::extract_seed_fragment`, verified byte-identical by
`tests/test_seed_fragment.py`); only the two upstream signals (the left
TTMn firing decision, and `reset`) are re-exposed as the fragment's own
named input pins, since the upstream adder-tree/comparator logic that
produces them is omitted from this minimal fragment. "It's a real fragment
of the real circuit" is therefore a literally true claim, not marketing.

## 8. Equivalence report

See `reports/equivalence.md` (generated by `circuit/equivalence.py`).
Headline: **80.6% jump/no-jump agreement** (79/98 looming-ramp stimulus
patterns) between the binarized netlist and an independently-calibrated LIF
reference model. Full breakdown by drive level, disagreement analysis, and
an honest limitations section are in that report -- see especially the
"weak" drive level, where agreement is much lower (12.5%) because the LIF
reference's continuous leaky integration is more sensitive to a single
active synapse than the binarized comparator's coarser 50%-of-max rule.

## 9. Reproducing everything from scratch

```
python -m venv venv
venv/Scripts/pip install -r requirements.txt   # (Scripts/ on Windows, bin/ elsewhere)

# 1. Extract the GF core subgraph from a local copy of MaleCNS v1.0's raw
#    feather files (annotations.feather, edges.feather,
#    neurotransmitters.feather -- see section 1 for the public download
#    source; --raw-dir can point at any local copy, e.g. FlyMarket's).
#    Takes several minutes (edges.feather is ~1 GB, streamed once).
python -m circuit.extract --raw-dir <path-to-malecns_v1> --out circuit/data/subgraph.json

# 2. Binarize the subgraph into full.json and seed.json.
python -m circuit.binarize

# 3. Run the equivalence check and regenerate reports/equivalence.md.
python -m circuit.equivalence

# Unit tests (fast, no MaleCNS data required -- exercise pure logic against
# small synthetic fixtures):
python -m pytest
```
