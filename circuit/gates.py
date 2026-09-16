"""NAND/LATCH gate-level primitives: a builder to compile Boolean/arithmetic
logic down to a flat NAND+LATCH netlist, and a pure-Python evaluator to run
that netlist against concrete input values.

Design (documented here because circuit/binarize.py and circuit/SCHEMA.md
both depend on it):

- The netlist has exactly two primitive gate types: NAND (2-input) and LATCH
  (a level-triggered SR-latch primitive, kept as an atomic gate type rather
  than decomposed into NAND, per the project brief: "LATCH for any state you
  need"). LATCH takes two inputs, (set_n, reset_n), both active-LOW, and
  behaves like the classic two-cross-coupled-NAND SR latch:
    set_n=0, reset_n=1  -> Q := 1
    set_n=1, reset_n=0  -> Q := 0
    set_n=1, reset_n=1  -> Q := previous Q (hold)
    set_n=0, reset_n=0  -> Q := 0 (RESET-DOMINANT convention for the
                                    otherwise "invalid" both-asserted state
                                    of a real cross-coupled NAND latch, since
                                    we do not model the complementary Q-bar
                                    output: if reset is asserted, the latch
                                    clears, even if set is asserted too).
  This primitive-level convention is a documented fallback only.
  circuit/binarize.py additionally makes the both-asserted state
  STRUCTURALLY unreachable at its one call site (its `set_n` signal is
  itself gated through NOT(reset), so `set_n` can never be 0 while
  `reset_n` is 0 -- see build_full_netlist()'s reset-dominant conditioning
  and test_binarize.py::test_latch_set_is_structurally_gated_by_reset).
  All other logic (NOT/AND/OR/XOR, adders, comparators) is compiled down to
  NAND gates only, using standard, generic digital-logic identities (none of
  this is specific to any GF netlist -- it is textbook Boolean algebra):

    NOT(a)      = NAND(a, a)                                    [1 NAND]
    AND(a, b)   = NOT(NAND(a, b))                                [2 NAND]
    OR(a, b)    = NAND(NOT(a), NOT(b))            (De Morgan)     [3 NAND]
    XOR(a, b): the classic 4-NAND XOR:
        n1 = NAND(a, b)
        n2 = NAND(a, n1)
        n3 = NAND(b, n1)
        n4 = NAND(n2, n3)   = a XOR b                              [4 NAND]

  Half adder HA(a, b) -> (sum, carry), reusing n1 from the XOR above:
        n1..n4 as above -> sum = n4
        n5 = NAND(n1, n1) = NOT(n1) = AND(a, b) = carry            [+1 NAND]
    Total: 5 NAND gates.

  Full adder FA(a, b, cin) -> (sum, carry_out), the standard 9-NAND-gate
  full adder (verified by truth table in test_gates.py):
        g1 = NAND(a, b)
        g2 = NAND(a, g1)
        g3 = NAND(b, g1)
        g4 = NAND(g2, g3)      = a XOR b
        g5 = NAND(g4, cin)
        g6 = NAND(g4, g5)
        g7 = NAND(cin, g5)
        g8 = NAND(g6, g7)      = sum = (a XOR b) XOR cin
        g9 = NAND(g5, g1)      = carry_out = (a AND b) OR (cin AND (a XOR b))
    Total: 9 NAND gates.

  Ripple-carry adder over two same-or-different-width bit vectors (LSB
  first): 1 half adder for bit 0, then one full adder per remaining bit,
  carrying into the next. Narrower operand is treated as zero-extended
  (missing high bits are the constant-0 pin).

  Magnitude comparator GE(a_bits, b_bits) (is A >= B): per-bit `gt_i =
  AND(a_i, NOT b_i)`, `eq_i = XNOR(a_i, b_i) = NOT(XOR(a_i, b_i))`, folded
  bit by bit as `ge := gt_i OR (eq_i AND ge_so_far)`, seeded with `ge = 1`
  (true) below bit 0. The fold MUST run from the least significant bit up
  to the most significant bit (i.e. iterate the LSB-first bit-vectors in
  their natural order, do not reverse them), so that a decision made by a
  more-significant bit is computed LAST and can never be overridden by a
  less-significant one. (An earlier MSB-first version of this fold had
  exactly that bug -- fixed, see test_compare_ge_matches_integer_comparison
  in test_gates.py.)
"""
from dataclasses import dataclass, field


NAND = "NAND"
LATCH = "LATCH"


@dataclass
class GateBuilder:
    """Incrementally builds a flat NAND/LATCH gate list plus named pins.

    Every constructive method returns a *signal id*: either the name of an
    input pin (a leaf, not present in `gates`) or the id of a gate in
    `gates` (whose evaluated output is the signal's value). Gate ids are
    assigned in construction order, which is guaranteed to be a valid
    topological (dependency-respecting) order because every builder method
    only ever references signals that already exist.
    """

    prefix: str = "g"
    gates: list = field(default_factory=list)
    input_pins: list = field(default_factory=list)
    _counter: int = 0
    _pin_set: set = field(default_factory=set)

    # -- leaves -----------------------------------------------------------
    def input_pin(self, name: str) -> str:
        """Register (or reuse) a named external input pin."""
        if name not in self._pin_set:
            self.input_pins.append(name)
            self._pin_set.add(name)
        return name

    def const(self, value: int) -> str:
        """A named constant pin ('const_0' / 'const_1'), driven to a fixed
        value by every caller of the evaluator (see gates.evaluate_netlist
        and circuit/equivalence.py). Using pins rather than a special gate
        type keeps the gate list to exactly {NAND, LATCH}."""
        assert value in (0, 1)
        return self.input_pin(f"const_{value}")

    # -- primitive ----------------------------------------------------------
    def nand(self, a: str, b: str) -> str:
        self._counter += 1
        gid = f"{self.prefix}{self._counter}"
        self.gates.append({"id": gid, "type": NAND, "inputs": [a, b]})
        return gid

    def latch(self, set_n: str, reset_n: str, label: str = None) -> str:
        self._counter += 1
        gid = f"{self.prefix}{self._counter}" if label is None else label
        self.gates.append({"id": gid, "type": LATCH, "inputs": [set_n, reset_n]})
        return gid

    # -- derived Boolean ops (all compiled to NAND only) --------------------
    def not_(self, a: str) -> str:
        return self.nand(a, a)

    def and_(self, a: str, b: str) -> str:
        return self.not_(self.nand(a, b))

    def or_(self, a: str, b: str) -> str:
        return self.nand(self.not_(a), self.not_(b))

    def xor_(self, a: str, b: str):
        """Returns (xor_signal, shared_nand_ab) -- the shared NAND(a,b) is
        exposed so half_adder() can reuse it for the carry bit without
        recomputing it."""
        n1 = self.nand(a, b)
        n2 = self.nand(a, n1)
        n3 = self.nand(b, n1)
        n4 = self.nand(n2, n3)
        return n4, n1

    def xnor_(self, a: str, b: str) -> str:
        x, _ = self.xor_(a, b)
        return self.not_(x)

    # -- arithmetic -----------------------------------------------------
    def half_adder(self, a: str, b: str):
        """Returns (sum, carry). 5 NAND gates total."""
        s, n1 = self.xor_(a, b)
        c = self.not_(n1)
        return s, c

    def full_adder(self, a: str, b: str, cin: str):
        """Returns (sum, carry_out). 9 NAND gates total (see module docstring)."""
        g1 = self.nand(a, b)
        g2 = self.nand(a, g1)
        g3 = self.nand(b, g1)
        g4 = self.nand(g2, g3)          # a XOR b
        g5 = self.nand(g4, cin)
        g6 = self.nand(g4, g5)
        g7 = self.nand(cin, g5)
        g8 = self.nand(g6, g7)          # sum
        g9 = self.nand(g5, g1)          # carry_out
        return g8, g9

    def ripple_add(self, bits_a, bits_b):
        """Add two LSB-first bit-vectors of (possibly different) width.
        Returns an LSB-first bit-vector one bit wider than the wider input
        (to hold the final carry-out)."""
        width = max(len(bits_a), len(bits_b))
        zero = self.const(0)
        a = list(bits_a) + [zero] * (width - len(bits_a))
        b = list(bits_b) + [zero] * (width - len(bits_b))
        out = []
        carry = None
        for i in range(width):
            if i == 0:
                s, carry = self.half_adder(a[0], b[0])
            else:
                s, carry = self.full_adder(a[i], b[i], carry)
            out.append(s)
        out.append(carry)
        return out

    def add_many(self, numbers):
        """Pairwise-tree-reduce a list of LSB-first bit-vectors into one sum
        bit-vector. `numbers` must be non-empty."""
        numbers = list(numbers)
        assert numbers, "add_many requires at least one operand"
        while len(numbers) > 1:
            nxt = []
            for i in range(0, len(numbers) - 1, 2):
                nxt.append(self.ripple_add(numbers[i], numbers[i + 1]))
            if len(numbers) % 2 == 1:
                nxt.append(numbers[-1])
            numbers = nxt
        return numbers[0]

    def mask(self, spike_bit: str, weight_bits):
        """AND a single spike bit against every bit of a constant weight
        magnitude, LSB-first. This is how a quantized synaptic weight is
        "delivered" only when its presynaptic neuron's stimulus bit is
        active -- equivalent to spike_bit * weight, computed without a
        multiplier, since weight_bits are compile-time constants (0/1
        pins) and only the AND gates are runtime logic."""
        return [self.and_(spike_bit, wb) for wb in weight_bits]

    def compare_ge(self, bits_a, bits_b) -> str:
        """Magnitude comparator: is A >= B? bits_a/bits_b are LSB-first (as
        produced by ripple_add/add_many). The recurrence
        `ge_i = gt_i OR (eq_i AND ge_{i-1})` must fold starting from the
        LEAST significant bit up to the MOST significant bit, so that a
        decision made by a more-significant bit can never be overridden by a
        less-significant one; this method therefore iterates the bit-vectors
        in their natural LSB-first order (do not reverse them)."""
        width = max(len(bits_a), len(bits_b))
        zero = self.const(0)
        a = list(bits_a) + [zero] * (width - len(bits_a))
        b = list(bits_b) + [zero] * (width - len(bits_b))
        ge = self.const(1)  # base case below bit 0: "equal so far" is true
        for ai, bi in zip(a, b):
            not_bi = self.not_(bi)
            gt_i = self.and_(ai, not_bi)
            eq_i = self.xnor_(ai, bi)
            ge = self.or_(gt_i, self.and_(eq_i, ge))
        return ge

    def const_bits(self, value: int, width: int):
        """LSB-first constant bit-vector of the given width."""
        return [self.const((value >> i) & 1) for i in range(width)]


def to_int(bits_lsb_first, values: dict) -> int:
    total = 0
    for i, b in enumerate(bits_lsb_first):
        total |= (values[b] & 1) << i
    return total


def evaluate_netlist(netlist: dict, input_values: dict, prev_state: dict = None) -> dict:
    """Evaluate every gate in `netlist['gates']` once, in list order (which
    is a valid topological order by construction -- see GateBuilder's
    docstring). Returns a dict {signal_id: 0/1} covering every input pin and
    every gate output. `prev_state` supplies previous-tick LATCH outputs
    (defaults to 0 for any LATCH not present); the returned dict includes an
    additional '_latch_state' sub-dict of {latch_id: value} for the caller to
    feed into the next tick.
    """
    prev_state = prev_state or {}
    values = dict(input_values)
    for pin in netlist.get("input_pins", []):
        if pin not in values:
            if pin == "const_0":
                values[pin] = 0
            elif pin == "const_1":
                values[pin] = 1
            else:
                raise KeyError(f"missing value for input pin {pin!r}")
    latch_state = {}
    for gate in netlist["gates"]:
        gid, gtype, inputs = gate["id"], gate["type"], gate["inputs"]
        if gtype == NAND:
            a, b = (values[i] for i in inputs)
            values[gid] = 0 if (a and b) else 1
        elif gtype == LATCH:
            set_n, reset_n = (values[i] for i in inputs)
            prev_q = prev_state.get(gid, 0)
            if set_n == 0 and reset_n == 1:
                q = 1
            elif set_n == 1 and reset_n == 0:
                q = 0
            elif set_n == 1 and reset_n == 1:
                q = prev_q
            else:  # set_n == 0 and reset_n == 0 -- reset-dominant convention
                q = 0
            values[gid] = q
            latch_state[gid] = q
        else:
            raise ValueError(f"unknown gate type {gtype!r}")
    values["_latch_state"] = latch_state
    return values
