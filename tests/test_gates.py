"""Truth-table tests for circuit/gates.py's NAND/LATCH primitives and the
NAND-only compiled Boolean/arithmetic helpers built on top of them."""
import itertools

import pytest

from circuit.gates import GateBuilder, evaluate_netlist, to_int


def _run(builder: GateBuilder, output, pin_values: dict):
    netlist = {"gates": builder.gates, "input_pins": builder.input_pins}
    result = evaluate_netlist(netlist, pin_values)
    if isinstance(output, list):
        return [result[o] for o in output]
    return result[output]


def test_nand_truth_table():
    b = GateBuilder()
    x, y = b.input_pin("x"), b.input_pin("y")
    g = b.nand(x, y)
    for a, c in itertools.product([0, 1], repeat=2):
        expected = 0 if (a and c) else 1
        assert _run(b, g, {"x": a, "y": c}) == expected


def test_not_truth_table():
    b = GateBuilder()
    x = b.input_pin("x")
    g = b.not_(x)
    assert _run(b, g, {"x": 0}) == 1
    assert _run(b, g, {"x": 1}) == 0


def test_and_or_truth_tables():
    b = GateBuilder()
    x, y = b.input_pin("x"), b.input_pin("y")
    g_and = b.and_(x, y)
    g_or = b.or_(x, y)
    for a, c in itertools.product([0, 1], repeat=2):
        assert _run(b, g_and, {"x": a, "y": c}) == (a & c)
        assert _run(b, g_or, {"x": a, "y": c}) == (a | c)


def test_xor_xnor_truth_tables():
    b = GateBuilder()
    x, y = b.input_pin("x"), b.input_pin("y")
    g_xor, _ = b.xor_(x, y)
    g_xnor = b.xnor_(x, y)
    for a, c in itertools.product([0, 1], repeat=2):
        assert _run(b, g_xor, {"x": a, "y": c}) == (a ^ c)
        assert _run(b, g_xnor, {"x": a, "y": c}) == (1 - (a ^ c))


def test_half_adder_truth_table():
    b = GateBuilder()
    x, y = b.input_pin("x"), b.input_pin("y")
    s, c = b.half_adder(x, y)
    for a, bb in itertools.product([0, 1], repeat=2):
        total = a + bb
        assert _run(b, [s, c], {"x": a, "y": bb}) == [total & 1, (total >> 1) & 1]


def test_full_adder_truth_table():
    b = GateBuilder()
    x, y, cin = b.input_pin("x"), b.input_pin("y"), b.input_pin("cin")
    s, cout = b.full_adder(x, y, cin)
    for a, bb, ci in itertools.product([0, 1], repeat=3):
        total = a + bb + ci
        assert _run(b, [s, cout], {"x": a, "y": bb, "cin": ci}) == [total & 1, (total >> 1) & 1]


def test_ripple_add_matches_integer_addition():
    b = GateBuilder()
    a_bits = [b.input_pin(f"a{i}") for i in range(4)]
    b_bits = [b.input_pin(f"b{i}") for i in range(3)]
    out = b.ripple_add(a_bits, b_bits)
    for av in range(16):
        for bv in range(8):
            pins = {f"a{i}": (av >> i) & 1 for i in range(4)}
            pins.update({f"b{i}": (bv >> i) & 1 for i in range(3)})
            netlist = {"gates": b.gates, "input_pins": b.input_pins}
            result = evaluate_netlist(netlist, pins)
            assert to_int(out, result) == av + bv


def test_add_many_sums_all_operands():
    b = GateBuilder()
    numbers = [b.const_bits(v, 4) for v in (3, 5, 2, 7, 1)]
    total = b.add_many(numbers)
    netlist = {"gates": b.gates, "input_pins": b.input_pins}
    result = evaluate_netlist(netlist, {})
    assert to_int(total, result) == 3 + 5 + 2 + 7 + 1


def test_add_many_single_operand_is_identity():
    b = GateBuilder()
    numbers = [b.const_bits(9, 4)]
    total = b.add_many(numbers)
    netlist = {"gates": b.gates, "input_pins": b.input_pins}
    result = evaluate_netlist(netlist, {})
    assert to_int(total, result) == 9


def test_mask_gates_spike_bit_against_weight():
    b = GateBuilder()
    spike = b.input_pin("spike")
    weight_bits = b.const_bits(11, 4)  # 1011
    masked = b.mask(spike, weight_bits)
    netlist = {"gates": b.gates, "input_pins": b.input_pins}
    on = evaluate_netlist(netlist, {"spike": 1})
    off = evaluate_netlist(netlist, {"spike": 0})
    assert to_int(masked, on) == 11
    assert to_int(masked, off) == 0


def test_compare_ge_matches_integer_comparison():
    b = GateBuilder()
    a_bits = [b.input_pin(f"a{i}") for i in range(4)]
    b_bits = b.const_bits(6, 4)
    ge = b.compare_ge(a_bits, b_bits)
    netlist = {"gates": b.gates, "input_pins": b.input_pins}
    for av in range(16):
        pins = {f"a{i}": (av >> i) & 1 for i in range(4)}
        result = evaluate_netlist(netlist, pins)
        assert result[ge] == (1 if av >= 6 else 0)


def test_compare_ge_handles_different_widths():
    b = GateBuilder()
    a_bits = b.const_bits(3, 3)   # 3-bit operand
    b_bits = b.const_bits(3, 5)   # 5-bit operand, same value
    ge = b.compare_ge(a_bits, b_bits)
    netlist = {"gates": b.gates, "input_pins": b.input_pins}
    result = evaluate_netlist(netlist, {})
    assert result[ge] == 1  # equal counts as >=


@pytest.mark.parametrize(
    "set_n, reset_n, prev, expected",
    [
        (0, 1, 0, 1),
        (0, 1, 1, 1),
        (1, 0, 0, 0),
        (1, 0, 1, 0),
        (1, 1, 0, 0),  # hold
        (1, 1, 1, 1),  # hold
        (0, 0, 0, 1),  # documented both-asserted convention
        (0, 0, 1, 1),
    ],
)
def test_latch_truth_table(set_n, reset_n, prev, expected):
    netlist = {"gates": [{"id": "L1", "type": "LATCH", "inputs": ["set_n", "reset_n"]}],
               "input_pins": ["set_n", "reset_n"]}
    result = evaluate_netlist(netlist, {"set_n": set_n, "reset_n": reset_n}, prev_state={"L1": prev})
    assert result["L1"] == expected
    assert result["_latch_state"]["L1"] == expected


def test_gate_ids_are_unique_and_referenced_inputs_precede_definition():
    b = GateBuilder()
    x, y = b.input_pin("x"), b.input_pin("y")
    b.add_many([b.const_bits(4, 3), b.const_bits(5, 3)])
    b.compare_ge([x, y], b.const_bits(1, 2))
    ids = [g["id"] for g in b.gates]
    assert len(ids) == len(set(ids))
    defined = set(b.input_pins)
    for g in b.gates:
        for inp in g["inputs"]:
            assert inp in defined, f"{g['id']} references {inp} before it is defined"
        defined.add(g["id"])


def test_evaluate_netlist_rejects_unknown_gate_type():
    netlist = {"gates": [{"id": "x", "type": "XOR", "inputs": ["a", "b"]}],
               "input_pins": ["a", "b"]}
    with pytest.raises(ValueError):
        evaluate_netlist(netlist, {"a": 0, "b": 0})


def test_evaluate_netlist_missing_pin_raises():
    netlist = {"gates": [], "input_pins": ["a"]}
    with pytest.raises(KeyError):
        evaluate_netlist(netlist, {})
