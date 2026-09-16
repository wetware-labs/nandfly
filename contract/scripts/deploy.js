/**
 * NandFly deploy script -- prepared for Task 5's user-gated real deployment.
 *
 * This script deploys NandFly with NO constructor arguments (there are none --
 * see contract/contracts/NandFly.sol's "no admin keys" design). It works
 * identically on the local Hardhat network (the default; safe, no real funds,
 * used by this repo's own tests/CI) and on BSC mainnet/testnet, which are only
 * reachable if you explicitly:
 *   1. export BSC_RPC_URL and BSC_DEPLOYER_PRIVATE_KEY (see contract/DEPLOY.md),
 *   2. pass --network bsc (or --network bscTestnet) on the command line.
 *
 * Running `npx hardhat run scripts/deploy.js` with NO --network flag (or
 * `--network hardhat`/`--network localhost`) NEVER touches a real chain --
 * this is what Task 3's own test suite and CI effectively exercise. Task 3
 * does NOT execute this script against bsc/bscTestnet; that step is Task 5's
 * explicit user-gated action (see contract/DEPLOY.md).
 *
 * Usage (local, safe):
 *   npx hardhat run scripts/deploy.js
 *
 * Usage (REAL DEPLOY -- Task 5 only, after explicit user go-ahead):
 *   npx hardhat run scripts/deploy.js --network bsc
 */
const hre = require("hardhat");

async function main() {
  const network = hre.network.name;
  console.log(`Deploying NandFly to network: ${network}`);

  const NandFly = await hre.ethers.getContractFactory("NandFly");
  const nandfly = await NandFly.deploy();
  await nandfly.waitForDeployment();

  const address = await nandfly.getAddress();
  const deployTx = nandfly.deploymentTransaction();
  const receipt = deployTx ? await deployTx.wait() : null;

  console.log("NandFly deployed to:", address);
  if (receipt) {
    console.log("Deployment gas used:", receipt.gasUsed.toString());
    console.log("Deployment tx hash:", receipt.hash);
  }

  const gateCount = await nandfly.GATE_COUNT();
  const bornAt = await nandfly.bornAt();
  console.log("GATE_COUNT():", gateCount.toString());
  console.log("bornAt():", bornAt.toString(), new Date(Number(bornAt) * 1000).toISOString());

  if (network === "bsc" || network === "bscTestnet") {
    console.log("");
    console.log("Next steps (see contract/DEPLOY.md):");
    console.log(`  1. Verify on BscScan: npx hardhat verify --network ${network} ${address}`);
    console.log(`  2. Parity spot-check: NANDFLY_ADDRESS=${address} npx hardhat run scripts/parity_check.js --network ${network}`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
