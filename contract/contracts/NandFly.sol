// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {NandFlyNetlist} from "./NandFlyNetlist.sol";

/// @title NandFly
/// @notice The fly's on-chain body: a 661-gate NAND/LATCH netlist derived from a
/// real Drosophila giant-fiber escape-reflex connectome fragment (MaleCNS), swatted
/// by anyone for free (view call) or on-chain (tx call, purely for the public record
/// -- no fees, no rewards, nothing to win or lose).
///
/// NO ADMIN KEYS. There is no owner, no pausable switch, no upgrade proxy, no
/// withdrawable balance, and no constructor argument that changes behavior. Every
/// byte of the netlist is a `bytes constant` compiled into this contract's own code
/// and is provably immutable the moment it is deployed. This organism belongs to no
/// one -- that is a deliberate trust property, not an oversight. (If you are auditing
/// this for the site copy: the ONLY state this contract ever writes is three public
/// counters incremented by swatTx(), nothing else.)
///
/// -----------------------------------------------------------------------------
/// Two-tick LATCH evaluation protocol (mirrors circuit/gates.py exactly)
/// -----------------------------------------------------------------------------
/// The netlist is combinational except for its 2 output LATCHes (jump_left,
/// jump_right), which hold state ACROSS EVALUATOR CALLS in the reference Python
/// implementation (circuit/gates.py::evaluate_netlist, prev_state/_latch_state).
/// This contract does not persist latch state in storage between transactions;
/// instead swat() and swatTx() run BOTH required ticks of the documented protocol
/// (see circuit/SCHEMA.md "Evaluation protocol") in one call, stateless from the
/// caller's point of view every time, which is exactly how circuit/equivalence.py
/// derives the single canonical answer for a given stimulus pattern:
///   1. "reset tick": evaluate once with reset=1 and every spike_* pin at 0, latch
///      previous-Q assumed 0 (a fresh/never-evaluated latch), to clear both
///      hemispheres' latches to a known 0 state.
///   2. "stimulus tick": evaluate again with reset=0 and the requested stimulus
///      pattern's spike_* pins set, feeding tick 1's latch outputs in as
///      previous-Q. jump_left / jump_right / jump are read from THIS tick.
/// This is a faithful, stateless re-simulation of the documented protocol, not an
/// approximation -- see contract/gen_parity_fixture.py + test/parity.test.js, which
/// check all 4096 possible stimulus patterns against circuit/gates.py's own output.
contract NandFly {
    // NandFlyNetlist.PACKED_GATES / spikeSignalIndices() / SIG_* below: see
    // contract/gen_netlist_sol.py's module docstring for the exact packing.

    /// @dev Fixed-size array length for latch previous-Q slots. Solidity does not
    /// accept a library constant (NandFlyNetlist.NUM_LATCHES) as an array-length
    /// expression across a contract boundary, so this is a local literal instead.
    /// It MUST equal NandFlyNetlist.NUM_LATCHES; test/parity.test.js's full
    /// 4096-pattern parity check would fail loudly if the two ever drifted (e.g.
    /// after regenerating NandFlyNetlist.sol from a netlist with a different LATCH
    /// count), and gen_netlist_sol.py itself refuses to generate a netlist file
    /// whose LATCH count isn't exactly 2.
    uint256 private constant NUM_LATCHES = 2;

    // ---------------------------------------------------------------------
    // Metadata
    // ---------------------------------------------------------------------

    function SPECIES() public pure returns (string memory) {
        return "Drosophila melanogaster (giant-fiber escape reflex, DNp01/TTMn pathway)";
    }

    /// @notice Credit + derivation provenance. The connectome data this netlist was
    /// derived from is the MaleCNS dataset (FlyWire/male Drosophila CNS connectome
    /// project); this circuit is an independent derivation -- see the derivation
    /// repo for the full binarization pipeline, threshold rulings, and equivalence
    /// report against a leaky-integrate-and-fire reference model.
    function PROVENANCE() public pure returns (string memory) {
        return
            "Derived from the MaleCNS connectome dataset (male Drosophila melanogaster "
            "CNS, FlyWire consortium). GF/TTMn escape-reflex subgraph (12 kept "
            "LC4/LPLC2 visual-input neurons of 311 available) binarized to a flat "
            "NAND+LATCH netlist by an independent NANDFLY derivation pipeline. Full "
            "derivation repo pointer: PLACEHOLDER -- see project site / GitHub org at "
            "deploy time for the exact commit this contract's netlist was generated "
            "from (contract/gen_netlist_sol.py from circuit/netlists/full.json).";
    }

    function GATE_COUNT() public pure returns (uint256) {
        return NandFlyNetlist.NUM_GATES;
    }

    /// @notice Deploy-time "born at" timestamp. Set once in the constructor and
    /// never changed by anything -- there is no function anywhere in this contract
    /// that writes to it again.
    uint256 public immutable bornAt;

    constructor() {
        // Defense in depth for the NUM_LATCHES duplication noted above.
        require(NUM_LATCHES == NandFlyNetlist.NUM_LATCHES, "NUM_LATCHES drift");
        bornAt = block.timestamp;
    }

    // ---------------------------------------------------------------------
    // Public counters (written ONLY by swatTx; swat() never writes state)
    // ---------------------------------------------------------------------

    /// @notice Total number of on-chain swatTx() calls ever made.
    uint256 public totalSwats;
    /// @notice Total number of on-chain swatTx() calls whose stimulus made it jump.
    uint256 public totalJumps;
    /// @notice Total number of on-chain swatTx() calls whose stimulus did NOT make
    /// it jump -- i.e. it survived the swat.
    uint256 public survivedSwats;

    event Swatted(address indexed swatter, uint16 stimulus, bool jumped);

    // ---------------------------------------------------------------------
    // Evaluation
    // ---------------------------------------------------------------------

    /// @notice Free, read-only evaluation of the netlist against a 12-bit visual
    /// stimulus pattern (bits 12-15 of `stimulus` are ignored). Pure function of
    /// its argument -- calling it twice with the same stimulus always returns the
    /// same answer; it does not depend on, or affect, any on-chain state.
    /// @param stimulus 12-bit stimulus pattern; bit i corresponds to a specific
    /// spike_<body_id> visual-input neuron -- see NandFlyNetlist's spike bit-order
    /// comment for the exact neuron each bit represents.
    function swat(uint16 stimulus)
        public
        pure
        returns (bool jumped, bool jumpLeft, bool jumpRight)
    {
        (jumpLeft, jumpRight) = _evaluate(stimulus);
        jumped = jumpLeft || jumpRight;
    }

    /// @notice Same evaluation as swat(), but as a transaction: emits a Swatted
    /// event and increments the public counters. No fee is required or charged
    /// (call it with msg.value == 0). `payable` exists only so a swatter MAY
    /// voluntarily attach value; the site copy is expected to steer feeding-wallet
    /// donations elsewhere (see the project ledger's feeding-wallet policy) rather
    /// than to this function, because -- consistent with "no admin keys" above --
    /// this contract has NO withdraw function and no owner, so any value attached
    /// here is PERMANENTLY LOCKED in the contract's balance, by design, forever.
    /// That is disclosed here rather than hidden: there is no backdoor for anyone,
    /// including us, to later add a withdraw function and sweep it.
    function swatTx(uint16 stimulus) public payable {
        (bool jumpLeft, bool jumpRight) = _evaluate(stimulus);
        bool jumped = jumpLeft || jumpRight;

        totalSwats += 1;
        if (jumped) {
            totalJumps += 1;
        } else {
            survivedSwats += 1;
        }

        emit Swatted(msg.sender, stimulus, jumped);
    }

    // ---------------------------------------------------------------------
    // Internal: stateless two-tick simulation
    // ---------------------------------------------------------------------

    /// @dev Runs the documented two-tick protocol once, fully in memory, and
    /// returns the final jump_left / jump_right signal values. See this contract's
    /// top-level NatSpec for why this is a faithful (not approximate) stateless
    /// re-simulation of circuit/gates.py's stateful reference protocol.
    function _evaluate(uint16 stimulus) internal pure returns (bool jumpLeft, bool jumpRight) {
        bytes memory packed = NandFlyNetlist.PACKED_GATES;
        uint256[12] memory spikeIdx = NandFlyNetlist.spikeSignalIndices();

        // Tick 1: reset=1, every spike_* = 0, every latch's previous-Q = 0 (a
        // never-yet-evaluated latch). Reset-dominant gating in the netlist itself
        // forces both latches to 0 regardless of previous-Q here (see
        // circuit/SCHEMA.md), but we pass explicit zeros to mirror
        // circuit/gates.py's evaluate_netlist(netlist, ..., prev_state=None) call
        // exactly, rather than relying on that fact.
        uint256[NUM_LATCHES] memory zeroPrevQ;
        (, uint256[NUM_LATCHES] memory tick1LatchQ) =
            _runTick(packed, spikeIdx, 1, 0, zeroPrevQ);

        // Tick 2: reset=0, spike_* = stimulus bits, previous-Q = tick 1's latch
        // outputs.
        (uint256[] memory sig2, ) = _runTick(packed, spikeIdx, 0, stimulus, tick1LatchQ);

        jumpLeft = sig2[NandFlyNetlist.SIG_JUMP_LEFT] == 1;
        jumpRight = sig2[NandFlyNetlist.SIG_JUMP_RIGHT] == 1;
    }

    /// @dev Evaluates every gate once, in the netlist's own topological order,
    /// writing each gate's output into `sig[NUM_INPUT_PINS + k]`. Returns the full
    /// signal array (so the caller can read named outputs) and this tick's latch
    /// outputs, indexed by ENCOUNTER ORDER (see gen_netlist_sol.py's "LATCH slot
    /// order" doc comment) for feeding into the next tick as previous-Q.
    function _runTick(
        bytes memory packed,
        uint256[12] memory spikeIdx,
        uint256 resetVal,
        uint16 stimulus,
        uint256[NUM_LATCHES] memory prevQ
    ) internal pure returns (uint256[] memory sig, uint256[NUM_LATCHES] memory latchQ) {
        sig = new uint256[](NandFlyNetlist.NUM_SIGNALS);

        // Input pins: reset, spike_*, const_0, const_1 (see NandFlyNetlist's
        // SIG_RESET / SIG_CONST_0 / SIG_CONST_1 / spikeSignalIndices()).
        sig[NandFlyNetlist.SIG_RESET] = resetVal;
        sig[NandFlyNetlist.SIG_CONST_0] = 0;
        sig[NandFlyNetlist.SIG_CONST_1] = 1;
        for (uint256 i = 0; i < 12; i++) {
            sig[spikeIdx[i]] = (uint256(stimulus) >> i) & 1;
        }

        // --- gate loop --------------------------------------------------
        // The loop body below is written in inline assembly rather than plain
        // Solidity for gas: profiling showed the checked-arithmetic + bounds-
        // checked dynamic-array-access Solidity would normally emit for this
        // (661 gates x 2 ticks = 1322 iterations) pushed swatTx() over 1.5M gas,
        // comfortably above the < 1M gas target. Every index used below (left,
        // right, outIdx, and the byte offsets into `packed`) is PROVEN in-range
        // by construction: gen_netlist_sol.py only ever emits signal indices <
        // NUM_SIGNALS (checked there -- see that script's pack_gates()), and
        // `packed`/`sig` are sized exactly NUM_GATES*4 / NUM_SIGNALS by this
        // function. Skipping Solidity's redundant runtime bounds checks here is
        // therefore safe, not merely fast; the full 4096-pattern parity test
        // (test/parity.test.js) re-verifies correctness after this optimization,
        // not just gas.
        uint256 latchSlot = 0;
        uint256 numInputPins = NandFlyNetlist.NUM_INPUT_PINS;
        uint256 packedPtr;
        uint256 sigPtr;
        assembly {
            packedPtr := add(packed, 0x20)
            sigPtr := add(sig, 0x20)
        }
        for (uint256 k = 0; k < NandFlyNetlist.NUM_GATES; ) {
            uint256 isLatch;
            uint256 a;
            uint256 b;
            uint256 outIdx;
            assembly {
                // Load the 4-byte big-endian gate word at byte offset k*4 by
                // reading a full word starting there and shifting the top 4
                // bytes down (avoids 4 separate bounds-checked byte reads).
                let word := shr(224, mload(add(packedPtr, mul(k, 4))))
                let left := and(shr(15, word), 0x7FFF)
                let right := and(word, 0x7FFF)
                isLatch := and(shr(30, word), 1)
                a := mload(add(sigPtr, mul(left, 0x20)))
                b := mload(add(sigPtr, mul(right, 0x20)))
                outIdx := add(numInputPins, k)
            }

            if (isLatch == 0) {
                // NAND: output = NOT(a AND b). a/b are always 0 or 1 by
                // construction (every signal is a single bit), so `a & b`
                // doubles as the AND used by circuit/gates.py.
                uint256 outVal = (a & b) == 1 ? 0 : 1;
                assembly {
                    mstore(add(sigPtr, mul(outIdx, 0x20)), outVal)
                }
            } else {
                // LATCH: inputs are (set_n, reset_n) = (a, b), both active-low.
                // See circuit/SCHEMA.md's truth table (reset-dominant convention
                // for the both-asserted state).
                uint256 q;
                if (a == 0 && b == 1) {
                    q = 1;
                } else if (a == 1 && b == 0) {
                    q = 0;
                } else if (a == 1 && b == 1) {
                    q = prevQ[latchSlot];
                } else {
                    q = 0;
                }
                assembly {
                    mstore(add(sigPtr, mul(outIdx, 0x20)), q)
                }
                latchQ[latchSlot] = q;
                latchSlot += 1;
            }

            unchecked {
                k += 1;
            }
        }
    }
}
