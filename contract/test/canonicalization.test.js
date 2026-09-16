const { expect } = require("chai");
const { ethers } = require("hardhat");

// I1 (Task 3 opcode-level audit fix round): stimulus is canonicalized (masked to
// its meaningful 12 bits) at the top of BOTH swat() and swatTx(), rather than
// reverting on a high-bit-set argument. This test proves two things: (1) the
// Swatted event always logs exactly the masked value that was actually
// evaluated, never the raw uint16 argument, and (2) swat() is now provably alias
// -- any two stimulus values that agree on bits 0-11 evaluate identically.
describe("NandFly stimulus canonicalization (I1)", function () {
  async function deploy() {
    const NandFly = await ethers.getContractFactory("NandFly");
    const nandfly = await NandFly.deploy();
    await nandfly.waitForDeployment();
    return nandfly;
  }

  it("swatTx(65535) emits stimulus 4095 (masked), matching swat()'s evaluated answer", async function () {
    const nandfly = await deploy();
    const [swatter] = await ethers.getSigners();

    const raw = 65535; // 0xFFFF -- all 16 bits set
    const masked = raw & 0x0fff; // 4095 -- only the meaningful 12 bits
    expect(masked).to.equal(4095);

    const [expectedJumped] = await nandfly.swat(raw);
    const [expectedJumpedFromMasked] = await nandfly.swat(masked);
    expect(expectedJumped).to.equal(expectedJumpedFromMasked);

    await expect(nandfly.swatTx(raw))
      .to.emit(nandfly, "Swatted")
      .withArgs(swatter.address, masked, expectedJumped);
  });

  it("aliasing: swat(x | 0xF000) === swat(x) for several x (high nibble is fully ignored)", async function () {
    const nandfly = await deploy();
    const samples = [0, 1, 5, 273, 2730, 4095, 0b101010101010, 0b010101010101];

    for (const x of samples) {
      const aliased = x | 0xf000;
      expect(aliased).to.be.at.most(0xffff);

      const resultX = await nandfly.swat(x);
      const resultAliased = await nandfly.swat(aliased);

      expect(resultAliased.jumped).to.equal(resultX.jumped, `jumped mismatch for x=${x}`);
      expect(resultAliased.jumpLeft).to.equal(resultX.jumpLeft, `jumpLeft mismatch for x=${x}`);
      expect(resultAliased.jumpRight).to.equal(resultX.jumpRight, `jumpRight mismatch for x=${x}`);
    }
  });

  it("swatTx aliasing: swatTx(x) and swatTx(x | 0xF000) emit the same masked stimulus and jumped value", async function () {
    const nandfly = await deploy();
    const [swatter] = await ethers.getSigners();
    const x = 0b110011001100;
    const aliased = x | 0xf000;

    const [jumped] = await nandfly.swat(x);

    await expect(nandfly.swatTx(x))
      .to.emit(nandfly, "Swatted")
      .withArgs(swatter.address, x, jumped);

    await expect(nandfly.swatTx(aliased))
      .to.emit(nandfly, "Swatted")
      .withArgs(swatter.address, x, jumped); // masked value, not `aliased`
  });
});
