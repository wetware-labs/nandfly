# NANDFLY netlist JSON schema

This document describes the JSON schema emitted by `circuit/binarize.py`
(`circuit/netlists/full.json` and `circuit/netlists/seed.json`), and the
subgraph schema emitted by `circuit/extract.py`
(`circuit/data/subgraph.json`). It is the reference used by
`tests/test_netlist_schema.py` and is meant to be the reference for a future
site-side circuit viewer.

## Subgraph JSON (`circuit/data/subgraph.json`)

```jsonc
{
  "meta": {
    "gf_type": "DNp01",
    "visual_types": ["LC4", "LPLC2"],
    "motor_candidate_types": ["TTMn", "DLMn a, b", "DLMn c-f"],
    "top_k": 3,
    "selection": "top-3 by ipsilateral synapse weight onto DNp01, per visual type per side"
  },
  "candidate_population_counts": { "<type>": { "L": int, "R": int }, ... },
  "excluded_motor_types": {
    "<type>": { "found_in_annotations": int, "direct_synapse_from_DNp01": bool, "reason_excluded": str }
  },
  "neurons": [
    { "id": int, "type": str, "side": "L"|"R", "role": "gf"|"visual_input"|"jump_motor",
      "transmitter": str|null, "sign": 1|-1,
      "synapse_weight_onto_gf": int  // visual_input neurons only
    }
  ],
  "edges": [ { "pre": int, "post": int, "weight": int, "sign": 1|-1 } ]
}
```

`id` is the MaleCNS body ID (a stable identifier from the published
dataset). `weight` is a raw synapse contact count (not yet quantized).
`sign` is the transmitter-derived sign of the PRE-synaptic neuron (+1
acetylcholine or ambiguous, -1 GABA/glutamate/histamine), applied to that
neuron's outgoing edges.

## Netlist JSON (`circuit/netlists/full.json`, `circuit/netlists/seed.json`)

```jsonc
{
  "schema_version": 1,
  "gates": [
    { "id": str, "type": "NAND", "inputs": [str, str] },
    { "id": str, "type": "LATCH", "inputs": [set_n: str, reset_n: str] }
  ],
  "input_pins": [str, ...],
  "output_pins": { "<name>": str /* a gate id */, ... },
  "neuron_gate_map": [   // full.json only
    { "neuron_id": int, "type": str, "side": "L"|"R",
      "role": "visual_input"|"gf"|"jump_motor",
      "signal": str,                // input pin name OR gate id
      "signal_kind": "input_pin"|"gate_output",
      "threshold": int,             // gf / jump_motor rows only
      "max_possible_sum": int       // gf / jump_motor rows only
    }
  ],
  "params": { "bit_width": int, "scale": int, "max_magnitude": int, "threshold_rule": str }
}
```

### Gate types

Exactly two primitive gate types exist, and every gate's `id` is unique and
referenced only by gates defined *after* it (construction order is a valid
topological/evaluation order -- see `circuit/gates.py`):

- **`NAND`**: 2-input NAND. `inputs = [a, b]`. Output = `NOT(a AND b)`.
- **`LATCH`**: a level-triggered SR-latch primitive (NOT decomposed into
  NAND -- see `circuit/gates.py`'s module docstring for why). `inputs =
  [set_n, reset_n]`, both active-LOW. Truth table:
  | set_n | reset_n | Q |
  |---|---|---|
  | 0 | 1 | 1 |
  | 1 | 0 | 0 |
  | 1 | 1 | hold (previous Q) |
  | 0 | 0 | 1 (documented convention; see `circuit/gates.py`) |

### Signals

Every `inputs` entry and every `output_pins` value refers to a *signal id*,
which is either:
- a name in `input_pins` (a leaf -- includes the constants `const_0` /
  `const_1`, driven to 0/1 by every evaluator caller, and the shared
  `reset` pin), or
- the `id` of a gate in `gates` (that gate's evaluated output).

### Input pins

- `const_0`, `const_1`: compile-time constants, wired in wherever
  `circuit/gates.py`'s builder needs a fixed bit (e.g. zero-extension,
  threshold constants).
- `reset`: shared, active-high. Driving `reset=1` (with all `spike_*` pins
  at 0) clears both hemispheres' output LATCHes to 0. See "Evaluation
  protocol" below.
- `spike_<body_id>`: one per visual-input neuron kept in the subgraph (the
  MaleCNS body ID is embedded in the pin name for traceability). 1 = that
  neuron is firing in this stimulus pattern.

### Output pins

- `jump_left`, `jump_right`: each hemisphere's own LATCH gate id (the
  persistent "jump commanded" state for that side).
- `jump`: `OR(jump_left, jump_right)` -- the single combined jump-command
  signal (the "named output pin" the project brief asks for).

### Evaluation protocol

The netlist is combinational except for the two output LATCHes, which hold
state across evaluator calls (see `circuit/gates.py::evaluate_netlist`'s
`prev_state` / `_latch_state` parameters). The documented usage protocol
(followed by `circuit/equivalence.py` and `tests/test_binarize.py`) is:
1. Evaluate once with `reset=1` and every `spike_*` pin at 0, to clear both
   latches to a known 0 state.
2. Evaluate again with `reset=0` and the stimulus pattern's `spike_*` pins
   set, feeding the previous call's `_latch_state` in as `prev_state`.
   Read `output_pins["jump"]` (or the per-hemisphere pins) from the result.

### `neuron_gate_map`

Maps every neuron kept in the subgraph to the signal that represents it in
the netlist, for a future circuit viewer to highlight neuron<->gate
correspondence:
- `visual_input` neurons map to their own `spike_<id>` input pin.
- `gf` (DNp01) neurons map to their threshold unit's comparator output gate
  (the `compare_ge` result -- "is GF's weighted visual input above
  threshold").
- `jump_motor` (TTMn) neurons map to their hemisphere's output LATCH gate id.

### seed.json

`seed.json` omits `neuron_gate_map` and `params` (it is a fragment, not a
full derivation) and instead adds:
```jsonc
{
  "description": str,          // which real piece of full.json this is, and why
  "source": { "netlist": "full.json", "hemisphere": "L"|"R", "gate_ids": [str, str, str] }
}
```
Its `gates` list is a byte-identical copy of exactly those 3 gate entries
from `full.json` (2 `NAND` + 1 `LATCH`) -- see
`tests/test_seed_fragment.py`.
