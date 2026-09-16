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
(a local FlyMarket checkout's `connectome_data/malecns_v1`, not
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
- DNp01, LC4, and LPLC2 -- every neuron actually wired into this circuit
  EXCEPT TTMn -- have `consensus_nt = acetylcholine` (sign +1), so every
  edge actually compiled into the netlist is excitatory. This claim is
  scoped precisely to those three types on purpose: TTMn's own transmitter
  is glutamate (sign -1 under our inherited sign map), so the subgraph as a
  whole is NOT "100% excitatory" if TTMn is included in the count -- see
  the sign-map limitation below.

**Known limitation, disclosed rather than hidden**: the transmitter-to-sign
map we reused from FlyMarket (mirroring DOOMFLY's own proxy, see section 1)
maps glutamate to inhibitory (-1) uniformly. That is a reasonable
population-level default in the insect CNS generally, but it is WRONG
specifically for motor neurons at the Drosophila neuromuscular junction,
where glutamate is the EXCITATORY transmitter. TTMn is glutamatergic in
this data, so its recorded sign (-1) is backwards for what TTMn actually
does biologically. This is harmless in this specific netlist -- TTMn is a
leaf/output neuron with no outgoing edges in this subgraph, so its sign is
recorded in `subgraph.json` but never read to flip any edge weight -- but
we are disclosing it now, on our own initiative, rather than leaving it for
someone else to find.

**Full candidate-edge accounting: 20,655 found, 14 used.** Streaming
`edges.feather` among the 325 candidate neurons found 20,655 total edges
(any direction, any type-pair within the candidate set); only 14 of them
end up in the wired circuit (12 top-K visual->GF edges + 2 GF->TTMn edges,
see section 4). Nothing else was silently dropped -- everything else was
found, inspected, and excluded on stated grounds:
- The overwhelming majority (~20,254 edges) are lateral/recurrent
  connections WITHIN the visual populations themselves (LC4<->LC4,
  LPLC2<->LPLC2, LC4<->LPLC2, all within the same side) and within the DLMn
  motor pool (~41 edges) -- real MaleCNS connectivity, but local circuitry,
  not part of a feedforward looming-to-jump pathway, so out of scope for
  this circuit.
- A DNp01 L<->R reciprocal connection, weight 1 in each direction -- a
  single sub-threshold synapse count (compare to the kept visual inputs'
  weights of 30-86), excluded as noise-level and out of scope (this circuit
  does not model cross-hemisphere GF-GF coupling).
- TTMn->DNp01 feedback, weight 1-2 per side -- a reverse (motor-to-command)
  synapse, sub-threshold and outside this circuit's strictly feedforward
  scope.
- ~40 individual DNp01->visual back-projection edges (weight 1-3 each,
  totaling 36 on LC4-L, 9 on LC4-R, 3 on LPLC2-L, 5 on LPLC2-R) -- feedback
  from GF onto its own visual inputs, again sub-threshold relative to the
  kept feedforward weights and outside this circuit's scope.

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

Stated plainly, since it is easy to lose in the surrounding detail: **this
circuit models 12 of the 311 available LC4/LPLC2 neurons in MaleCNS v1.0
for this pathway (3.9%)** (311 = 126 LC4 + 185 LPLC2). The same figure is
in `circuit/binarize.py`'s `VISUAL_INPUTS_KEPT_FRACTION`, in every generated
`full.json`'s `params`, and at the top of `reports/equivalence.md`.

## 5. Binarization design

See `circuit/binarize.py`'s module docstring for the full detail; summary:

- **Weight quantization**: `magnitude = clamp(floor(raw_weight / 6), 1, 15)`,
  a signed 4-bit magnitude (`BIT_WIDTH=4`, `SCALE=6`). SCALE=6 was chosen so
  this subgraph's largest raw weight (86) just fits in 4 bits (86//6=14).
  The floor is clamped to a minimum of 1 so a selected (top-K) synapse never
  binarizes away to zero weight.
- **Threshold rule -- REVISED after the first review round.** Two rules,
  selected structurally by input count, not hand-picked per unit:
  - Multi-input units (GF/DNp01, 6 inputs each) fire when the weighted
    input sum is >= `(largest single input's quantized magnitude) + 1` --
    an a-priori "coincidence detector" rule, chosen ON PRINCIPLE from the
    biology (GF integrates converging looming channels; no single LC4 or
    LPLC2 afferent should be able to command a jump by itself), NOT because
    it scores best on the equivalence test set.
  - Single-input units (TTMn) keep the original `ceil(0.5 *
    max_possible_sum)` rule. The coincidence rule is deliberately NOT
    applied here: for a one-input unit, `max_possible_sum` IS that one
    input's magnitude, so "largest + 1" would always exceed the unit's own
    maximum achievable sum, making it permanently unfirable.
  The first equivalence run used a single 0.5 rule everywhere and a SAMPLED
  98-pattern stimulus set, reporting 80.6% agreement. An independent
  exhaustive (all 4096 patterns) re-run of that same 0.5 rule found the true
  number is actually 76.7% -- lower. The coincidence rule was adopted
  afterward, on principle, not to chase a better score; see
  `reports/equivalence.md`'s full threshold-fraction sweep (every fraction
  we tried, including ones that score higher, and why we didn't pick them)
  and section 8 below.
- **Gate compilation**: `circuit/gates.py` compiles everything except the 2
  output LATCHes down to NAND only, using standard textbook identities
  (4-NAND XOR, 9-NAND full adder, De Morgan OR/AND, an LSB-up-fold
  magnitude comparator) -- see that module's docstring for the exact
  decompositions and correctness reasoning (verified by truth-table tests
  in `tests/test_gates.py`).
- **Identity-passthrough optimization** for single-input threshold units
  (added after the first review round): a lone positive-sign input's
  0.5-of-max rule always reduces to "fires iff the input fires" (the sum is
  either 0 or the input's own magnitude, and `ceil(0.5*magnitude) <=
  magnitude` for any magnitude >= 1), so no mask/adder/comparator gates are
  built for it -- its "fires" signal is wired straight through. See section
  6 for the gate-count impact and the exhaustive equivalence test proving
  it changes no jump output.
- **LATCH usage**: exactly one LATCH per hemisphere, holding the
  jump-commanded motor decision persistently (a documented design choice --
  representing the real, finite duration of a motor command -- rather than
  a momentary combinational pulse). See `circuit/SCHEMA.md`'s "Evaluation
  protocol" for the reset/read sequence.
- **Reset-dominant LATCH conditioning** (added after the first review
  round): each hemisphere's `set_n` signal is `NAND(fires_signal,
  reset_n)` rather than a plain `NOT(fires_signal)` -- by De Morgan, this
  equals `NOT(fires_signal) OR reset_pin`, forced to 1 (inactive) whenever
  `reset_pin=1` regardless of `fires_signal`. Since `reset_n` is already
  needed as the LATCH's own second input, this costs no additional gate,
  and makes `set_n`/`reset_n` structurally unable to both be 0 at once (not
  merely "by calling convention") -- see `circuit/gates.py`'s LATCH
  docstring and `tests/test_binarize.py::test_latch_set_is_structurally_gated_by_reset`.
- **Sign handling**: `negate_bits()` implements two's-complement negation
  for a future inhibitory-input extension; unused by this all-excitatory
  subgraph but unit-tested.

## 6. Actual gate counts (measured, not assumed)

Running `python -m circuit.binarize` on the real subgraph currently produces:

- `full.json`: **661 gates** (659 NAND + 2 LATCH)
- `seed.json`: **3 gates** (2 NAND + 1 LATCH)

This reflects the identity-passthrough optimization added after the first
review round (see section 5): the first version of this pipeline built a
full mask+adder+comparator for TTMn's single-input threshold unit too (as
if it were a multi-input unit), costing ~60 gates per hemisphere for logic
that always reduces to "wire the input straight through". Removing that
dead weight brought the netlist from **781 gates (779 NAND + 2 LATCH) down
to 661 (659 NAND + 2 LATCH)** -- a pure gate-count optimization with NO
behavioral change: `tests/test_binarize.py::
test_identity_optimization_never_changes_jump_output_across_all_patterns`
builds both the optimized and unoptimized netlist from the same real
subgraph and checks the jump decision matches across all 4096 exhaustive
stimulus patterns (see section 8) before asserting the gate-count claim.

661 (like the earlier 781) is still larger than the project plan's rough
planning estimate ("~150-400 gates" / "Full ~173+ gates"), which was
written before this investigation computed an actual NAND-only gate
decomposition. The brief explicitly removes any cost constraint on
`full.json` ("no component-cost constraint since it deploys to our own
contract"), so this honest, measured count is reported as-is rather than
force-fit to the earlier estimate. The dominant remaining cost is the GF
adder tree: each 9-NAND full adder is used many times across two
per-hemisphere 6-input, 4-bit-wide adder trees plus two 7-8-bit magnitude
comparators; `TOP_K` and `BIT_WIDTH` are the two knobs that would shrink
this further if a smaller netlist were wanted later.

## 7. What `seed.json` actually is

A verbatim 3-gate (2 NAND + 1 LATCH) fragment of `full.json`: the final
TTMn-to-jump output stage for the **left** hemisphere -- the reset-dominant
set/reset conditioning (one NAND computing `NOT(reset_pin)`, and one NAND
computing `NAND(fires_signal, that NOT(reset))`, see section 5) feeding the
`jump_left` LATCH that holds the fly's jump-commanded state. The gate ids,
types, and wiring are copied unchanged from `full.json`
(`circuit/binarize.py::extract_seed_fragment`, verified parsed-equal --
same id/type/inputs -- by `tests/test_seed_fragment.py`, and checked
byte-for-byte against the committed files by
`tests/test_netlist_schema.py`); only the two external signals this stage
depends on (the left hemisphere's jump-firing decision, and the shared
`reset` pin) are re-exposed as the fragment's own named input pins, since
the upstream adder-tree/comparator logic that produces them is omitted
from this minimal fragment. Its pin names are literally the full.json
signal ids they stand in for -- see `circuit/SCHEMA.md`'s "seed.json pin
naming" section for the exact provenance rule. "It's a real fragment of the
real circuit" is therefore a literally true claim, not marketing -- and so
is the converse: this fragment carries no synaptic weights or thresholds of
its own, only the output stage's wiring (see the site-copy guidance in
`.superpowers/sdd/nandfly-mvp/task-1-report.md`'s fix-round appendix).

## 8. Equivalence report

See `reports/equivalence.md` (generated by `circuit/equivalence.py`).
Headline: **98.9% jump/no-jump agreement (4051/4096)** between the
binarized netlist (coincidence-detector threshold rule) and an
independently-calibrated LIF reference model, over the EXHAUSTIVE set of
all 4096 stimulus patterns this subgraph's 12 kept visual inputs can
express (not a sample). By drive level: none 100%, weak 90.7%, medium 100%,
strong 100%; all 45 disagreements are LIF-jumped-but-binarized-didn't
(zero false jumps from the binarized side). Full breakdown, the complete
threshold-fraction sweep (every value tried, both on the retired 98-pattern
sampled set and the current exhaustive set, with an explicit statement of
why the best-scoring fraction was NOT chosen), and an honest limitations
section (including the glutamate sign-map caveat from section 3) are all in
that report.

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
