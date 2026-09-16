const { expect } = require("chai");
const { ethers } = require("hardhat");

// I2b (Task 3 opcode-level audit fix round): NandFlyValidation.validatePackedGates()
// must actually reject a corrupted packed gate list AT CONSTRUCTION TIME, not just
// in a comment claiming it would. NandFlyValidationHarness (test-only contract)
// exposes the exact same library call NandFly's own constructor makes, so we can
// exercise it directly with deliberately-corrupted bytes without needing to alter
// NandFly's real (auto-generated, always in-range) embedded netlist.
describe("NandFlyValidation.validatePackedGates (I2b)", function () {
  function packWord(typeBit, left, right) {
    const word = ((typeBit & 1) << 30) | ((left & 0x7fff) << 15) | (right & 0x7fff);
    const buf = Buffer.alloc(4);
    buf.writeUInt32BE(word >>> 0, 0);
    return buf;
  }

  function packWords(words) {
    return "0x" + Buffer.concat(words).toString("hex");
  }

  async function harness() {
    const Harness = await ethers.getContractFactory("NandFlyValidationHarness");
    return Harness;
  }

  it("rejects a packed gate list with a left-operand index >= numSignals", async function () {
    const Harness = await harness();
    const numSignals = 10;
    // A single NAND gate whose left operand index (10) is out of range for
    // numSignals=10 (valid range is [0, 10)).
    const badPacked = packWords([packWord(0, 10, 0)]);

    await expect(
      Harness.deploy(badPacked, 1, numSignals)
    ).to.be.revertedWith("NandFlyValidation: left operand out of range");
  });

  it("rejects a packed gate list with a right-operand index >= numSignals", async function () {
    const Harness = await harness();
    const numSignals = 10;
    const badPacked = packWords([packWord(0, 0, 10)]);

    await expect(
      Harness.deploy(badPacked, 1, numSignals)
    ).to.be.revertedWith("NandFlyValidation: right operand out of range");
  });

  it("rejects a packed byte length that doesn't match numGates*4", async function () {
    const Harness = await harness();
    const badPacked = packWords([packWord(0, 0, 0)]); // 4 bytes, but claim 2 gates

    await expect(
      Harness.deploy(badPacked, 2, 10)
    ).to.be.revertedWith("NandFlyValidation: packed length mismatch");
  });

  it("accepts a valid, in-range packed gate list", async function () {
    const Harness = await harness();
    const numSignals = 10;
    const goodPacked = packWords([packWord(0, 5, 3), packWord(1, 9, 0)]);

    const deployed = await Harness.deploy(goodPacked, 2, numSignals);
    await expect(deployed.waitForDeployment()).to.not.be.reverted;
  });

  it("NandFly's own real deployment passes this same on-chain check (implicit -- deploy() below must not revert)", async function () {
    const NandFly = await ethers.getContractFactory("NandFly");
    const nandfly = await NandFly.deploy();
    await expect(nandfly.waitForDeployment()).to.not.be.reverted;
    expect(await nandfly.GATE_COUNT()).to.equal(661n);
  });
});
