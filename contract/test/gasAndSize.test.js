const { expect } = require("chai");
const { ethers, artifacts } = require("hardhat");

const MAX_RUNTIME_CODE_SIZE = 24576; // EIP-170
const MAX_SWATTX_GAS = 1_000_000; // Task 3 requirement: "comfortably < 1M gas"

describe("NandFly gas + code size", function () {
  it("runtime bytecode is under the EIP-170 24KB contract size limit", async function () {
    const artifact = await artifacts.readArtifact("NandFly");
    const runtimeBytes = (artifact.deployedBytecode.length - 2) / 2;
    console.log(`    runtime code size: ${runtimeBytes} bytes (limit ${MAX_RUNTIME_CODE_SIZE})`);
    expect(runtimeBytes).to.be.lessThan(MAX_RUNTIME_CODE_SIZE);
  });

  it("reports gas for swat() (view/eth_call) and swatTx(), and swatTx is comfortably under 1M gas", async function () {
    const NandFly = await ethers.getContractFactory("NandFly");
    const nandfly = await NandFly.deploy();
    await nandfly.waitForDeployment();

    const stimulusPatterns = [0, 0b101010101010, 0b111111111111];

    for (const stimulus of stimulusPatterns) {
      // swat() gas: estimateGas on the view function shows the cost of running
      // the full 661-gate x 2-tick evaluation as a state-changing call, i.e. the
      // realistic upper bound of what it would cost if it WEREN'T free -- swat()
      // itself remains a free eth_call in normal use.
      const gasEstimate = await nandfly.swat.estimateGas(stimulus);
      console.log(`    swat(${stimulus}) estimateGas (as if a tx): ${gasEstimate.toString()}`);

      const tx = await nandfly.swatTx(stimulus);
      const receipt = await tx.wait();
      console.log(`    swatTx(${stimulus}) actual gasUsed: ${receipt.gasUsed.toString()}`);
      expect(receipt.gasUsed).to.be.lessThan(MAX_SWATTX_GAS);
    }
  });
});
