require("@nomicfoundation/hardhat-toolbox");

/**
 * NANDFLY Layer-1 contract -- Hardhat config.
 *
 * Local-only by default. The `bsc` network entry below is documented for
 * Task 5's use (see contract/DEPLOY.md) and reads its RPC URL / private key
 * from environment variables that are NOT set anywhere in this repo -- there
 * is no way to accidentally deploy to BSC mainnet by running the test suite
 * or any script in this directory without explicitly exporting those vars
 * and explicitly passing `--network bsc`.
 */
module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
  },
  networks: {
    hardhat: {
      allowUnlimitedContractSize: false,
    },
    bsc: {
      url: process.env.BSC_RPC_URL || "",
      accounts: process.env.BSC_DEPLOYER_PRIVATE_KEY
        ? [process.env.BSC_DEPLOYER_PRIVATE_KEY]
        : [],
      chainId: 56,
    },
    bscTestnet: {
      url: process.env.BSC_TESTNET_RPC_URL || "",
      accounts: process.env.BSC_DEPLOYER_PRIVATE_KEY
        ? [process.env.BSC_DEPLOYER_PRIVATE_KEY]
        : [],
      chainId: 97,
    },
  },
  etherscan: {
    // BscScan verification (Task 5). BSCSCAN_API_KEY is NOT set anywhere in
    // this repo; `npx hardhat verify` is a no-op/error without it exported.
    apiKey: {
      bsc: process.env.BSCSCAN_API_KEY || "",
      bscTestnet: process.env.BSCSCAN_API_KEY || "",
    },
  },
  mocha: {
    timeout: 300000,
  },
};
