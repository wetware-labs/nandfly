// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {NandFlyValidation} from "../NandFlyValidation.sol";

/// @title NandFlyValidationHarness
/// @notice TEST-ONLY contract (not part of the deployed NandFly organism). Exists
/// solely so test/validation.test.js can prove NandFlyValidation.validatePackedGates()
/// actually rejects a corrupted packed gate list at construction time -- i.e. that
/// "a corrupted netlist constant fails deployment" is a real, exercised property,
/// not just an assertion in a comment. NandFly.sol's own constructor calls the same
/// library function against its real (auto-generated, always in-range) data.
contract NandFlyValidationHarness {
    constructor(bytes memory packed, uint256 numGates, uint256 numSignals) {
        NandFlyValidation.validatePackedGates(packed, numGates, numSignals);
    }
}
