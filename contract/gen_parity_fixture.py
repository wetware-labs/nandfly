"""Generate contract/fixtures/parity_4096.json: the reference-correct answer for
all 4096 possible 12-bit stimulus patterns, computed with circuit/gates.py itself
(NOT reimplemented) so it is a genuine oracle, not a second guess.

This is the PARITY fixture referenced by NANDFLY Task 3: test/parity.test.js reads
this file and checks that NandFly.sol's swat() agrees with every single entry --
all 4096, no sampling.

Uses the exact two-tick protocol documented in circuit/SCHEMA.md's "Evaluation
protocol" section (the same protocol circuit/equivalence.py uses):
  1. reset=1, every spike_* pin = 0, prev_state = None (fresh latches) -> clears
     both hemispheres' output LATCHes.
  2. reset=0, this pattern's spike_* pins set, prev_state = tick 1's
     `_latch_state` -> read jump_left / jump_right / jump from this tick's result.

Stimulus bit order matches contract/gen_netlist_sol.py exactly: bit i of the
12-bit stimulus corresponds to the i-th spike_<body_id> pin in full.json's own
input_pins array order (both scripts derive this from full.json directly, so
they cannot drift from each other).

Run from the repo root:  python contract/gen_parity_fixture.py
"""
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from circuit.gates import evaluate_netlist  # noqa: E402

NETLIST_PATH = REPO_ROOT / "circuit" / "netlists" / "full.json"
OUT_PATH = REPO_ROOT / "contract" / "fixtures" / "parity_4096.json"


def load_netlist():
    with open(NETLIST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def spike_pin_order(netlist):
    return [p for p in netlist["input_pins"] if p.startswith("spike_")]


def eval_stimulus(netlist, spike_pins, stimulus: int):
    output_pins = netlist["output_pins"]

    # Tick 1: reset tick.
    tick1_inputs = {"reset": 1}
    for pin in spike_pins:
        tick1_inputs[pin] = 0
    tick1 = evaluate_netlist(netlist, tick1_inputs, prev_state=None)

    # Tick 2: stimulus tick, fed tick 1's latch outputs as previous state.
    tick2_inputs = {"reset": 0}
    for i, pin in enumerate(spike_pins):
        tick2_inputs[pin] = (stimulus >> i) & 1
    tick2 = evaluate_netlist(netlist, tick2_inputs, prev_state=tick1["_latch_state"])

    jump_left = bool(tick2[output_pins["jump_left"]])
    jump_right = bool(tick2[output_pins["jump_right"]])
    jumped = bool(tick2[output_pins["jump"]])
    assert jumped == (jump_left or jump_right), (
        f"jump pin disagrees with OR(jump_left, jump_right) at stimulus={stimulus}"
    )
    return jumped, jump_left, jump_right


def generate():
    netlist = load_netlist()
    spike_pins = spike_pin_order(netlist)
    assert len(spike_pins) == 12, f"expected 12 spike pins, found {len(spike_pins)}"

    results = []
    jump_count = 0
    for stimulus in range(4096):
        jumped, jump_left, jump_right = eval_stimulus(netlist, spike_pins, stimulus)
        if jumped:
            jump_count += 1
        results.append(
            {
                "stimulus": stimulus,
                "jumped": jumped,
                "jumpLeft": jump_left,
                "jumpRight": jump_right,
            }
        )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "source_netlist": "circuit/netlists/full.json",
                "spike_pin_order": spike_pins,
                "num_patterns": len(results),
                "jump_count": jump_count,
                "results": results,
            },
            f,
            indent=0,
        )
    print(f"wrote {OUT_PATH}: {len(results)} patterns, {jump_count} jump")


if __name__ == "__main__":
    generate()
