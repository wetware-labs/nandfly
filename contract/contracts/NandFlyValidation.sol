// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title NandFlyValidation
/// @notice Hand-written (NOT auto-generated -- see NandFlyNetlist.sol, which is pure
/// generated data) one-time validation logic for a packed gate list. Added after
/// Task 3's opcode-level audit (I2b): correctness of NandFly's evaluator previously
/// rested entirely on trusting that contract/gen_netlist_sol.py packed every gate's
/// operand indices correctly. That script now asserts this at generation time (see
/// its pack_gates() docstring), but a deployed contract's bytecode is a separate
/// artifact from the script that produced it -- this library lets the CHAIN ITSELF
/// re-check the one property NandFly's evaluator actually depends on for memory
/// safety (every operand index is in range) at construction time, once, cheaply.
/// This converts "trust the generator" into "the chain checked it before the
/// contract's constructor even finished."
///
/// Deliberately NOT re-checking the topological-order property here (gen_netlist_sol.py's
/// second assertion, operand < gate's own index): that would cost meaningfully more
/// gas (an extra comparison depending on loop position, still cheap, but this
/// library is intentionally the minimum on-chain check that fully protects
/// NandFly._runTick()'s inline-assembly memory accesses, which only ever need
/// `left`/`right` < numSignals to stay within the `sig[]` array's bounds -- a stale
/// (but in-range) operand from a non-topological ordering would produce a WRONG
/// answer, not an out-of-bounds memory access, and would already be caught by
/// test/parity.test.js's exhaustive 4096-pattern check before any real deploy.
library NandFlyValidation {
    /// @notice Reverts unless every gate's left/right operand index in `packed` is
    /// strictly less than `numSignals`. Iterates all `numGates` gates once; pure
    /// Solidity (not the inline-assembly fast path NandFly._runTick() uses), since
    /// this runs exactly once, at construction, and auditability matters more than
    /// gas here.
    /// @param packed Big-endian uint32-per-gate packed gate list (see
    /// gen_netlist_sol.py's "Gate packing" doc comment for the exact bit layout).
    /// @param numGates Number of 4-byte gate words `packed` is expected to contain.
    /// @param numSignals Exclusive upper bound every operand index must satisfy.
    function validatePackedGates(bytes memory packed, uint256 numGates, uint256 numSignals) internal pure {
        require(packed.length == numGates * 4, "NandFlyValidation: packed length mismatch");
        for (uint256 k = 0; k < numGates; k++) {
            uint256 offset = k * 4;
            uint32 word = (uint32(uint8(packed[offset])) << 24) |
                (uint32(uint8(packed[offset + 1])) << 16) |
                (uint32(uint8(packed[offset + 2])) << 8) |
                uint32(uint8(packed[offset + 3]));
            uint256 left = (word >> 15) & 0x7FFF;
            uint256 right = word & 0x7FFF;
            require(left < numSignals, "NandFlyValidation: left operand out of range");
            require(right < numSignals, "NandFlyValidation: right operand out of range");
        }
    }
}
