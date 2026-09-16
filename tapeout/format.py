"""TapeOut Protocol on-chain netlist byte format: a generic codec, plus an
encoder/decoder that round-trips our netlist JSON schema (circuit/SCHEMA.md)
through it.

Format provenance and independent verification
------------------------------------------------
The wire format implemented here (opcode-tagged cells over a flat, growing
signal space) is not first-party documented by tapeout.net (no verified
source on BscScan as of 2026-09-16 -- see tapeout/SUBMISSION.md). The layout
below was cross-checked two ways before being relied on:

1. Documentation: the third-party project named in the project's feasibility
   spike (C:\\Users\\gmldn\\Documents\\Codex\\_spikes\\tapeout-fly-spike\\findings.md
   section 3), github.com/BruceLanLan/c3s-reflex-circuits (Apache-2.0),
   documents this exact layout in its generic circuit-IR module
   `c3s/netlist.py` (NOT its fly-circuit-specific files, which this project
   deliberately never reads or copies -- see docs/plans/2026-09-16-nandfly-mvp.md's
   "independent derivation" constraint. `c3s/netlist.py` is general-purpose
   TapeOut wire-protocol infrastructure, not connectome data, so reading its
   public, openly-licensed format documentation does not touch that
   constraint). That project states it cross-checked the same layout against
   "the public tapeout.net decoder and evaluator" with 0 mismatches over
   4,800 random ticks.
2. REAL ON-CHAIN DATA (this project's own independent check, 2026-09-16):
   the exact opcode/operand layout below was confirmed by fetching two real,
   already-minted circuits from the live "TapeOut" processor contract on BSC
   mainnet (0xb1024b89886b9a34aa4ff5f31c411d708b20a14c) via public read-only
   RPC and decoding them byte-for-byte with THIS module's `decode_cells`:
     - token #1:    3 NAND cells, 2 inputs, 1 output, 0 latches -- exercises OP_NAND.
     - token #5000: 1 NAND + 9 LATCH cells, 0 inputs, 8 outputs, a 9-stage
                    ring counter with a forward-referencing LATCH.d (latch 0's
                    d points at latch 8's output, defined 9 cells later) --
                    exercises OP_LATCH and the "d may point anywhere" rule.
   Both fixtures are committed under tapeout/fixtures/ (see their embedded
   `source` metadata for the exact RPC calls and how the contract's ABI --
   unverified on BscScan -- was independently recovered: by keccak256-hashing
   candidate Solidity signatures and matching the first 4 bytes against PUSH4
   operands harvested from the processor implementation's bytecode). See
   tapeout/verify.py for the fetch+decode harness and tapeout/SUBMISSION.md
   for the full certainty verdict, including what is NOT confirmed by real
   data (OP_REF, and the exact mint/tape-out write-function signature).

Byte layout (confirmed for OP_NAND and OP_LATCH; OP_REF is transcribed from
the documentation source only, unconfirmed by real on-chain data since no
fixture found so far uses it -- our own seed.json never needs it either):

    signal space (all big-endian, 24-bit "u24" signal indices unless noted):
        0            constant 0
        1            constant 1
        2 .. 2+n-1   primary inputs (n = n_inputs, supplied out-of-band --
                     the byte stream itself does not encode n_inputs/n_outputs)
        then one signal per cell output, in cell order (a REF cell yields
        n_out consecutive signals; every other cell yields exactly 1)
    primary outputs = the LAST n_outputs signals (also supplied out-of-band)

    cell     bytes                                                total
    ----     -----                                                -----
    NAND     0x00 | u24 a | u24 b                                 7
    LATCH    0x01 | u24 d                                         4
             (output = value stored at the end of the PREVIOUS tick;
              stores signal d, evaluated at the end of THIS tick, for
              next tick -- d may reference a signal defined later in
              the same cell list, since it is only read after the
              whole tick's combinational network has settled)
    REF      0x02 | 20-byte cpu address | u64 circuit_id
             | u8 n_in | u8 n_out | u24 in_0 .. u24 in_{n_in-1}     31 + 3*n_in
             (calls another deployed circuit; UNCONFIRMED by real data)

Our LATCH primitive is NOT the same gate as TapeOut's native LATCH
------------------------------------------------------------------
circuit/SCHEMA.md's LATCH is a level-triggered SR-latch: two inputs
(set_n, reset_n, active-low), and its output is a COMBINATIONAL function of
those inputs and the previous tick's Q (see circuit/gates.py's
evaluate_netlist: `set_n=0 -> Q:=1`, `reset_n=0 -> Q:=0` (reset-dominant),
`both 1 -> hold`, computed and visible to OTHER gates within the SAME
evaluator call).

TapeOut's native LATCH is a single-input D-register: its output signal, for
the whole current tick, is fixed to whatever was stored at the end of the
PREVIOUS tick; only the (separately specified) `d` input -- which may be any
combinational function of this tick's signals, including the latch's own
output -- gets captured for the NEXT tick.

These are different primitives (one is level-sensitive/transparent within a
tick, the other is a genuine one-tick-delayed register), so `encode_netlist`
below does not map our LATCH gate to a bare TapeOut LATCH cell. Instead each
of our LATCH gates compiles to a small NAND network wrapped around one native
LATCH cell, chosen so that the resulting TapeOut circuit's tick-by-tick
behaviour is bit-for-bit identical to our SR-latch semantics under our own
two-call (reset tick, then stimulus tick) evaluation protocol (see
circuit/SCHEMA.md "Evaluation protocol"). The derivation:

    Let s = set_n, r = reset_n, p = the native LATCH cell's own output
    signal (which -- by TapeOut's semantics above -- equals exactly the
    previous tick's stored value, i.e. our "previous Q").

    Our truth table, written as a single Boolean function q(s, r, p):
        s=0, r=1            -> q = 1
        s=1, r=0            -> q = 0
        s=1, r=1            -> q = p           (hold)
        s=0, r=0            -> q = 0           (reset-dominant)
    is exactly  q = r AND (NOT(s) OR p) = NOT(NAND(r, NAND(s, NOT(p))))

    which compiles to 4 NAND gates (verified exhaustively over all 8
    combinations of (s, r, p) against circuit/gates.py's own evaluate_netlist
    LATCH branch -- see tests/test_tapeout_format.py::test_latch_translation_
    matches_our_sr_latch_truth_table_exhaustively):
        g1 = NAND(p, p)            # NOT(p)
        g2 = NAND(s, g1)           # NAND(s, NOT(p)) = NOT(s) OR p
        g3 = NAND(r, g2)
        g4 = NAND(g3, g3)          # NOT(g3) = q

    The native LATCH cell's `d` is then wired to g4 (a forward reference,
    which the format allows), and every OTHER gate that referenced our
    LATCH gate's id is rewired to read g4 (the computed q), not the raw
    native LATCH cell's signal.

    "One of our evaluate_netlist() calls" therefore corresponds to exactly
    "one TapeOut tick": our two-call (reset, then stimulus) protocol maps to
    ticks 1 and 2, with tick 1 establishing state=0 in every native LATCH
    cell (nothing has been stored yet) exactly as our own `prev_state={}`
    default does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

# ---------------------------------------------------------------------------
# Generic TapeOut byte codec (opcodes + cell shapes; see module docstring)
# ---------------------------------------------------------------------------

OP_NAND = 0x00
OP_LATCH = 0x01
OP_REF = 0x02

U24_MAX = (1 << 24) - 1
U64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class Nand:
    a: int
    b: int


@dataclass(frozen=True)
class Latch:
    d: int


@dataclass(frozen=True)
class Ref:
    cpu: str  # "0x" + 40 hex chars (20-byte address)
    circuit_id: int
    ins: tuple
    n_out: int


Cell = Union[Nand, Latch, Ref]


def _cell_width(cell: Cell) -> int:
    """How many consecutive output signals this cell produces."""
    return cell.n_out if isinstance(cell, Ref) else 1


def _u24(value: int) -> bytes:
    if not 0 <= value <= U24_MAX:
        raise ValueError(f"signal index {value} does not fit in u24 (max {U24_MAX})")
    return value.to_bytes(3, "big")


def encode_cells(cells) -> bytes:
    """Serialise a list of Nand/Latch/Ref cells to TapeOut netlist bytes."""
    out = bytearray()
    for cell in cells:
        if isinstance(cell, Nand):
            out += bytes([OP_NAND]) + _u24(cell.a) + _u24(cell.b)
        elif isinstance(cell, Latch):
            out += bytes([OP_LATCH]) + _u24(cell.d)
        elif isinstance(cell, Ref):
            addr = bytes.fromhex(cell.cpu.removeprefix("0x"))
            if len(addr) != 20:
                raise ValueError("Ref.cpu must be a 20-byte (40 hex char) address")
            if not (0 <= cell.circuit_id <= U64_MAX):
                raise ValueError(f"Ref.circuit_id {cell.circuit_id} does not fit in u64")
            if not (0 <= len(cell.ins) <= 255 and 0 <= cell.n_out <= 255):
                raise ValueError("Ref port counts must fit in u8")
            out += bytes([OP_REF]) + addr + cell.circuit_id.to_bytes(8, "big")
            out += bytes([len(cell.ins), cell.n_out])
            out += b"".join(_u24(x) for x in cell.ins)
        else:
            raise TypeError(f"unknown cell type: {cell!r}")
    return bytes(out)


def decode_cells(data: bytes, n_inputs: int = 0):
    """Parse raw TapeOut netlist bytes into a list of Nand/Latch/Ref cells.

    `n_inputs` seeds the running signal counter (default 0, i.e. caller does
    not know/care about primary-input count -- used by verify.py's generic
    real-chain sanity reporting, where structural forward-reference checks on
    NAND/REF operands are still meaningful without it as long as n_inputs is
    supplied when known, which tightens validation). Mirrors the semantics
    documented in this module's docstring: NAND/REF may only reference
    already-defined signals; LATCH.d is checked only after the full cell
    list has been parsed (it may reference a signal defined later).
    """
    cells: list = []
    latch_d_checks: list = []
    p = 0
    s = 2 + n_inputs

    def take(k: int) -> bytes:
        nonlocal p
        if p + k > len(data):
            raise ValueError(f"truncated TapeOut netlist at byte {p} (need {k} more, have {len(data) - p})")
        chunk = data[p : p + k]
        p += k
        return chunk

    while p < len(data):
        op = take(1)[0]
        if op == OP_NAND:
            a = int.from_bytes(take(3), "big")
            b = int.from_bytes(take(3), "big")
            if a >= s or b >= s:
                raise ValueError(f"NAND cell at signal {s} reads a not-yet-defined signal (a={a}, b={b})")
            cells.append(Nand(a, b))
            s += 1
        elif op == OP_LATCH:
            d = int.from_bytes(take(3), "big")
            latch_d_checks.append((len(cells), d))
            cells.append(Latch(d))
            s += 1
        elif op == OP_REF:
            cpu = "0x" + take(20).hex()
            circuit_id = int.from_bytes(take(8), "big")
            n_in, n_out = take(2)
            ins = tuple(int.from_bytes(take(3), "big") for _ in range(n_in))
            if any(x >= s for x in ins):
                raise ValueError(f"REF cell at signal {s} reads a not-yet-defined signal (ins={ins})")
            cells.append(Ref(cpu, circuit_id, ins, n_out))
            s += n_out
        else:
            raise ValueError(f"unknown TapeOut opcode 0x{op:02x} at byte {p - 1}")

    for cell_index, d in latch_d_checks:
        if not (0 <= d < s):
            raise ValueError(f"LATCH cell #{cell_index} has d={d}, outside the final signal space [0, {s})")

    return cells


@dataclass
class Circuit:
    """A fully-specified, decoded TapeOut circuit: cells plus the
    out-of-band port counts the byte format itself never encodes."""

    n_inputs: int
    n_outputs: int
    cells: list = field(default_factory=list)

    @property
    def first_cell_signal(self) -> int:
        return 2 + self.n_inputs

    @property
    def n_signals(self) -> int:
        return self.first_cell_signal + sum(_cell_width(c) for c in self.cells)

    def output_signals(self):
        n = self.n_signals
        return list(range(n - self.n_outputs, n))

    def describe(self) -> dict:
        """Sanity-report counts, used by verify.py for real on-chain circuits."""
        return {
            "n_inputs": self.n_inputs,
            "n_outputs": self.n_outputs,
            "n_cells": len(self.cells),
            "nand": sum(isinstance(c, Nand) for c in self.cells),
            "latch": sum(isinstance(c, Latch) for c in self.cells),
            "ref": sum(isinstance(c, Ref) for c in self.cells),
            "n_signals": self.n_signals,
            "bytes": len(encode_cells(self.cells)),
        }


def decode_circuit(data: bytes, n_inputs: int, n_outputs: int) -> Circuit:
    cells = decode_cells(data, n_inputs=n_inputs)
    circuit = Circuit(n_inputs, n_outputs, cells)
    if circuit.n_outputs > circuit.n_signals - circuit.first_cell_signal:
        raise ValueError(
            f"n_outputs={n_outputs} exceeds the {circuit.n_signals - circuit.first_cell_signal} "
            "signals this circuit's cells actually produce"
        )
    return circuit


def tick(circuit: Circuit, inputs, state=None):
    """Evaluate one TapeOut tick (generic: NAND + LATCH; REF unsupported --
    this project's own circuits never emit REF, and no real on-chain fixture
    we have exercises it either -- see module docstring).

    Returns (outputs, next_state), where `state` / `next_state` are
    {latch_cell_index_within_this_circuit: bit} for THIS circuit's own LATCH
    cells only, in the order they appear among `circuit.cells`.
    """
    latch_positions = [i for i, c in enumerate(circuit.cells) if isinstance(c, Latch)]
    n_state = len(latch_positions)
    old = list(state) if state is not None else [0] * n_state
    if len(old) != n_state:
        raise ValueError(f"state has {len(old)} bits, circuit has {n_state} LATCH cells")
    if len(inputs) != circuit.n_inputs:
        raise ValueError(f"expected {circuit.n_inputs} inputs, got {len(inputs)}")

    sig = [0] * circuit.n_signals
    sig[1] = 1
    for i, v in enumerate(inputs):
        sig[2 + i] = 1 if v else 0

    s = circuit.first_cell_signal
    old_by_pos = dict(zip(latch_positions, old))
    for i, cell in enumerate(circuit.cells):
        if isinstance(cell, Nand):
            sig[s] = 0 if (sig[cell.a] and sig[cell.b]) else 1
            s += 1
        elif isinstance(cell, Latch):
            sig[s] = old_by_pos[i]
            s += 1
        else:
            raise NotImplementedError("REF cells are not supported by this evaluator (unused by this project)")

    new_state = []
    for i in latch_positions:
        new_state.append(sig[circuit.cells[i].d])

    outputs = sig[circuit.n_signals - circuit.n_outputs :]
    return outputs, new_state


def to_hex(data: bytes) -> str:
    return "0x" + data.hex()


def from_hex(text: str) -> bytes:
    return bytes.fromhex(text.removeprefix("0x"))


# ---------------------------------------------------------------------------
# Our netlist JSON schema (circuit/SCHEMA.md) <-> TapeOut bytes
# ---------------------------------------------------------------------------

CONST_PINS = {"const_0": 0, "const_1": 1}


@dataclass
class GateBlock:
    kind: str  # "NAND" | "LATCH"
    start_sig: int  # first cell's signal (== the raw LATCH cell's signal, for LATCH)
    final_sig: int  # the signal external readers should use (== start_sig for NAND;
    #                 == start_sig + 4, the computed q, for LATCH)


@dataclass
class EncodeMeta:
    """Everything the TapeOut byte format itself does not encode, but which
    is needed to reconstruct our schema from it -- analogous to the
    n_inputs/n_outputs every real TapeOut consumer must already track
    out-of-band (see this module's `decode_circuit`)."""

    input_pins: list          # netlist["input_pins"], verbatim and in order
    gate_order: list          # our gate ids, in original netlist["gates"] order
    gate_blocks: dict         # gate id -> GateBlock
    output_order: list        # netlist["output_pins"] keys, in order
    n_inputs: int
    n_outputs: int
    buffered_outputs: bool = True  # False iff optimize_output_buffer dropped the tail buffer (see encode_netlist)


def _non_const_input_pins(input_pins) -> list:
    return [p for p in input_pins if p not in CONST_PINS]


def encode_netlist(netlist: dict, optimize_output_buffer: bool = False):
    """Encode our netlist JSON (circuit/SCHEMA.md) into TapeOut bytes.

    Returns (bytes, EncodeMeta). The EncodeMeta is required to decode back to
    our schema (see decode_to_schema) -- it plays the same out-of-band-manifest
    role any real TapeOut netlist needs (n_inputs, n_outputs, pin names): the
    wire bytes alone never carry names or port counts for ANY TapeOut circuit,
    ours included.

    By default (`optimize_output_buffer=False`), every named output gets its
    own 2-cell NAND identity buffer (see the loop below), even when its
    source gate already happens to sit at the exact tail position TapeOut's
    format requires (the last n_outputs signals, in output_pins order) --
    this keeps the encoder simple and correct for the fully general case
    (arbitrary output ordering/aliasing), at the cost of 2 redundant NAND
    cells per output that didn't actually need moving.

    `optimize_output_buffer=True` is an OPTIONAL, narrowly-scoped
    optimization used only for cost/documentation purposes (e.g.
    tapeout/quote.py's "true minimal cost" row, tapeout/SUBMISSION.md's
    7-cell canvas layout): it drops the buffer entirely, but ONLY in the
    all-or-nothing case where every output's resolved source signal is
    ALREADY exactly the trailing n_outputs signals, in the exact order
    output_pins declares them (i.e. no cells need to move at all). This is
    semantics-preserving by construction: it emits strictly fewer cells and
    changes no wiring, so it cannot change what any signal computes -- it
    only skips writing 2 dead identity-buffer cells nothing depended on.
    For seed.json specifically, jump_left's LATCH-translation final NAND
    (`q = NOT(NAND(reset_n, NAND(set_n, NOT(prev_Q))))` -- reset-dominance is
    unaffected, since that identity is proved purely from the 4-NAND network
    itself and never touches the buffer) already IS the last cell emitted,
    so the whole 2-cell buffer is redundant and gets dropped: 9 cells (8
    NAND + 1 LATCH) become 7 cells (6 NAND + 1 LATCH). If the all-or-nothing
    condition does NOT hold (e.g. multiple outputs whose sources are not
    already contiguous/in-order), this option has no effect and the encoder
    falls back to the default buffered behavior for every output.
    """
    raw_input_pins = list(netlist.get("input_pins", []))
    ordered_inputs = _non_const_input_pins(raw_input_pins)

    sig_of = dict(CONST_PINS)
    for i, pin in enumerate(ordered_inputs):
        sig_of[pin] = 2 + i

    cells: list = []
    next_sig = 2 + len(ordered_inputs)
    gate_blocks: dict = {}
    gate_order: list = []

    def resolve(name: str) -> int:
        if name in sig_of:
            return sig_of[name]
        if name in gate_blocks:
            return gate_blocks[name].final_sig
        raise KeyError(f"signal {name!r} referenced before it is defined")

    for gate in netlist["gates"]:
        gid, gtype, gins = gate["id"], gate["type"], gate["inputs"]
        gate_order.append(gid)
        if gtype == "NAND":
            a, b = resolve(gins[0]), resolve(gins[1])
            start = next_sig
            cells.append(Nand(a, b))
            next_sig += 1
            gate_blocks[gid] = GateBlock("NAND", start, start)
        elif gtype == "LATCH":
            set_n, reset_n = resolve(gins[0]), resolve(gins[1])
            latch_sig = next_sig
            cells.append(Latch(0))  # placeholder; backpatched to g4 below
            next_sig += 1
            g1 = next_sig
            cells.append(Nand(latch_sig, latch_sig))  # NOT(p)
            next_sig += 1
            g2 = next_sig
            cells.append(Nand(set_n, g1))  # NOT(s) OR p
            next_sig += 1
            g3 = next_sig
            cells.append(Nand(reset_n, g2))
            next_sig += 1
            g4 = next_sig
            cells.append(Nand(g3, g3))  # q
            next_sig += 1
            cells[latch_sig - (2 + len(ordered_inputs))] = Latch(g4)
            gate_blocks[gid] = GateBlock("LATCH", latch_sig, g4)
        else:
            raise ValueError(f"unknown gate type {gtype!r} for gate {gid!r}")

    output_order = list(netlist["output_pins"].keys())
    n_outputs = len(output_order)
    output_srcs = [resolve(netlist["output_pins"][name]) for name in output_order]

    already_trailing = output_srcs == list(range(next_sig - n_outputs, next_sig)) and n_outputs > 0
    buffered_outputs = not (optimize_output_buffer and already_trailing)

    if buffered_outputs:
        for src in output_srcs:
            buf1 = next_sig
            cells.append(Nand(src, src))
            next_sig += 1
            buf2 = next_sig
            cells.append(Nand(buf1, buf1))
            next_sig += 1
    # else: outputs are already exactly the trailing n_outputs signals in
    # order (checked above) -- nothing to emit, see optimize_output_buffer's
    # docstring above.

    n_inputs = len(ordered_inputs)
    meta = EncodeMeta(raw_input_pins, gate_order, gate_blocks, output_order, n_inputs, n_outputs, buffered_outputs)
    return encode_cells(cells), meta


def decode_to_schema(data: bytes, meta: EncodeMeta, schema_version: int = 1) -> dict:
    """Decode TapeOut bytes back into our netlist JSON schema.

    This is a round-trip decoder for bytes PRODUCED BY `encode_netlist`
    (recognisable by the fixed 1-NAND-cell / 5-cell-LATCH-group structural
    signature it emits -- see module docstring), not a general decoder for
    arbitrary third-party TapeOut circuits: an arbitrary on-chain LATCH usage
    cannot in general be uniquely un-translated into an SR-latch (many
    different source primitives could compile to the same D-register-plus-NAND
    pattern). For arbitrary real on-chain circuits, see `decode_circuit` /
    `Circuit.describe` above, which is fully general and is what
    tapeout/verify.py uses against real chain data.

    Every operand below is read FRESH from `data` via `decode_cells` (not
    echoed from `meta`); `meta` supplies only the out-of-band legend (which
    signal is which named pin/gate) that any TapeOut consumer -- including a
    real one -- needs regardless of source, exactly as `decode_circuit`
    needs external n_inputs/n_outputs.
    """
    cells = decode_cells(data, n_inputs=meta.n_inputs)

    name_of_signal: dict = {}
    if "const_0" in meta.input_pins:
        name_of_signal[0] = "const_0"
    if "const_1" in meta.input_pins:
        name_of_signal[1] = "const_1"
    for i, pin in enumerate(_non_const_input_pins(meta.input_pins)):
        name_of_signal[2 + i] = pin
    for gid, block in meta.gate_blocks.items():
        name_of_signal[block.final_sig] = gid

    def name_of(sig: int) -> str:
        if sig not in name_of_signal:
            raise ValueError(f"decoded signal {sig} does not correspond to any known pin or gate output")
        return name_of_signal[sig]

    gates = []
    for gid in meta.gate_order:
        block = meta.gate_blocks[gid]
        if block.kind == "NAND":
            cell = cells[block.final_sig - meta.n_inputs - 2]
            if not isinstance(cell, Nand):
                raise ValueError(f"gate {gid!r}: expected a NAND cell at signal {block.final_sig}, got {cell!r}")
            gates.append({"id": gid, "type": "NAND", "inputs": [name_of(cell.a), name_of(cell.b)]})
        elif block.kind == "LATCH":
            base = block.start_sig - meta.n_inputs - 2
            latch_cell, g1_cell, g2_cell, g3_cell, g4_cell = cells[base : base + 5]
            if not isinstance(latch_cell, Latch) or latch_cell.d != block.final_sig:
                raise ValueError(f"gate {gid!r}: LATCH cell at signal {block.start_sig} has unexpected d={getattr(latch_cell, 'd', None)}")
            if not isinstance(g1_cell, Nand) or (g1_cell.a, g1_cell.b) != (block.start_sig, block.start_sig):
                raise ValueError(f"gate {gid!r}: does not match the expected LATCH-translation NAND pattern (g1)")
            if not isinstance(g2_cell, Nand) or g2_cell.b != block.start_sig + 1:
                raise ValueError(f"gate {gid!r}: does not match the expected LATCH-translation NAND pattern (g2)")
            if not isinstance(g3_cell, Nand) or g3_cell.b != block.start_sig + 2:
                raise ValueError(f"gate {gid!r}: does not match the expected LATCH-translation NAND pattern (g3)")
            if not isinstance(g4_cell, Nand) or g4_cell.a != g4_cell.b or g4_cell.a != block.start_sig + 3:
                raise ValueError(f"gate {gid!r}: does not match the expected LATCH-translation NAND pattern (g4)")
            set_n_sig, reset_n_sig = g2_cell.a, g3_cell.a
            gates.append({"id": gid, "type": "LATCH", "inputs": [name_of(set_n_sig), name_of(reset_n_sig)]})
        else:
            raise ValueError(f"unknown recorded gate kind {block.kind!r} for {gid!r}")

    output_signals_by_pos = decode_circuit(data, meta.n_inputs, meta.n_outputs).output_signals()
    output_pins = {}
    for name, out_sig in zip(meta.output_order, output_signals_by_pos):
        if meta.buffered_outputs:
            buf2 = cells[out_sig - meta.n_inputs - 2]
            if not isinstance(buf2, Nand) or buf2.a != buf2.b:
                raise ValueError(f"output {name!r}: does not match the expected identity-buffer pattern")
            buf1 = cells[buf2.a - meta.n_inputs - 2]
            if not isinstance(buf1, Nand) or buf1.a != buf1.b:
                raise ValueError(f"output {name!r}: does not match the expected identity-buffer pattern")
            output_pins[name] = name_of(buf1.a)
        else:
            # optimize_output_buffer dropped the buffer: the output signal
            # IS directly the underlying gate/pin's own final signal.
            output_pins[name] = name_of(out_sig)

    return {
        "schema_version": schema_version,
        "gates": gates,
        "input_pins": list(meta.input_pins),
        "output_pins": output_pins,
    }
