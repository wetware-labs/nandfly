const { expect } = require("chai");
const { ethers } = require("hardhat");

describe("NandFly.swatTx", function () {
  async function deploy() {
    const NandFly = await ethers.getContractFactory("NandFly");
    const nandfly = await NandFly.deploy();
    await nandfly.waitForDeployment();
    return nandfly;
  }

  it("emits Swatted with the correct swatter/stimulus/jumped and matches swat()'s view answer", async function () {
    const nandfly = await deploy();
    const [swatter] = await ethers.getSigners();

    const stimulus = 0b111111111111; // all 12 visual inputs firing -> strong drive
    const [expectedJumped] = await nandfly.swat(stimulus);

    await expect(nandfly.swatTx(stimulus))
      .to.emit(nandfly, "Swatted")
      .withArgs(swatter.address, stimulus, expectedJumped);
  });

  it("increments totalSwats and exactly one of totalJumps/survivedSwats per call", async function () {
    const nandfly = await deploy();

    expect(await nandfly.totalSwats()).to.equal(0n);
    expect(await nandfly.totalJumps()).to.equal(0n);
    expect(await nandfly.survivedSwats()).to.equal(0n);

    // stimulus 0: no visual input firing at all -> must not jump (see
    // reports/equivalence.md: "none" drive level is 1/1 agreement, no jump).
    const [jumped0] = await nandfly.swat(0);
    expect(jumped0).to.equal(false);
    await nandfly.swatTx(0);

    expect(await nandfly.totalSwats()).to.equal(1n);
    expect(await nandfly.totalJumps()).to.equal(0n);
    expect(await nandfly.survivedSwats()).to.equal(1n);

    const stimulus = 0b111111111111;
    const [jumped1] = await nandfly.swat(stimulus);
    await nandfly.swatTx(stimulus);

    expect(await nandfly.totalSwats()).to.equal(2n);
    if (jumped1) {
      expect(await nandfly.totalJumps()).to.equal(1n);
      expect(await nandfly.survivedSwats()).to.equal(1n);
    } else {
      expect(await nandfly.totalJumps()).to.equal(0n);
      expect(await nandfly.survivedSwats()).to.equal(2n);
    }

    // totalSwats must always equal totalJumps + survivedSwats.
    const total = await nandfly.totalSwats();
    const jumps = await nandfly.totalJumps();
    const survived = await nandfly.survivedSwats();
    expect(total).to.equal(jumps + survived);
  });

  it("C1: rejects any attached value -- swatTx is not payable, contract cannot hold BNB", async function () {
    const nandfly = await deploy();
    const value = ethers.parseEther("0.001");

    // swatTx() has no `payable` modifier, so solc's own generated dispatcher
    // rejects msg.value > 0 before NandFly's code runs at all -- this is not
    // application-level logic, it's the ABI dispatch itself.
    await expect(nandfly.swatTx(0, { value })).to.be.reverted;

    // Same for a plain BNB transfer: no receive()/fallback() exists either.
    const [sender] = await ethers.getSigners();
    const contractAddress = await nandfly.getAddress();
    await expect(
      sender.sendTransaction({ to: contractAddress, value })
    ).to.be.reverted;

    // Contract balance must stay exactly zero -- there is truly nothing to
    // ever hold, lock, or need a withdraw function for.
    expect(await ethers.provider.getBalance(contractAddress)).to.equal(0n);
  });

  it("swat() is a pure view and never touches state (counters stay zero across repeated calls)", async function () {
    const nandfly = await deploy();
    for (let s = 0; s < 20; s++) {
      await nandfly.swat(s);
    }
    expect(await nandfly.totalSwats()).to.equal(0n);
  });
});

describe("NandFly metadata", function () {
  it("exposes SPECIES/PROVENANCE/GATE_COUNT/bornAt with sane values", async function () {
    const NandFly = await ethers.getContractFactory("NandFly");
    const nandfly = await NandFly.deploy();
    await nandfly.waitForDeployment();

    expect(await nandfly.SPECIES()).to.be.a("string").and.not.empty;
    expect(await nandfly.PROVENANCE()).to.be.a("string").and.not.empty;
    expect(await nandfly.GATE_COUNT()).to.equal(661n);

    const bornAt = await nandfly.bornAt();
    const block = await ethers.provider.getBlock("latest");
    expect(bornAt).to.be.a("bigint");
    expect(bornAt).to.be.lte(BigInt(block.timestamp));
  });

  it("has no owner/admin functions (organism belongs to no one)", async function () {
    const NandFly = await ethers.getContractFactory("NandFly");
    const iface = NandFly.interface;
    const fnNames = iface.fragments
      .filter((f) => f.type === "function")
      .map((f) => f.name.toLowerCase());
    const adminish = ["owner", "renounceownership", "transferownership", "pause", "unpause", "withdraw", "setfee", "upgradeto"];
    for (const name of adminish) {
      expect(fnNames, `unexpected admin-like function: ${name}`).to.not.include(name);
    }
  });
});
