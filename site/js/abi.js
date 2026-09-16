// Minimal, hand-picked ABI constants for NandFly.sol (contract/contracts/NandFly.sol).
// Zero deps: no ethers/web3/viem. Function selectors are the first 4 bytes of
// keccak256("<signature>") -- computed OFFLINE with the project's own
// independent keccak-256 implementation (tapeout/_keccak.py, itself
// documented as a from-spec implementation, not third-party-derived) via:
//
//   python -c "from tapeout._keccak import selector; \
//     print(selector('swat(uint16)'))"
//
// ...and hardcoded here rather than reimplemented in the browser, so this
// file carries zero cryptographic risk of its own. If NandFly.sol's function
// signatures ever change, regenerate these with the same command.

export const SELECTORS = {
  "swat(uint16)": "0xc52ff196",
  "swatTx(uint16)": "0x81f2b317",
  "totalSwats()": "0x948d6acf",
  "totalJumps()": "0xfcffe9db",
  "survivedSwats()": "0xead54f1e",
  "bornAt()": "0x08741204",
  "GATE_COUNT()": "0x6a844f26",
  "PROVENANCE()": "0x6373a6b1",
  "SPECIES()": "0x04b7d48f",
};

// Full 32-byte event topic0 for `Swatted(address,uint16,bool)` (events use
// the WHOLE keccak256 hash, unlike the 4-byte function-selector truncation
// above). Computed the same way, once, offline:
//   python -c "from tapeout._keccak import keccak256; \
//     print('0x' + keccak256(b'Swatted(address,uint16,bool)').hex())"
// Not read by any current site code path (pre-deploy, nothing filters
// `Swatted` logs yet) -- kept here, verified, for a future live-feed-over-
// logs upgrade. Per DEPLOY.md section 7: topic0 alone is never proof a log
// came from THIS contract -- any indexer using this MUST also filter by the
// emitting contract's address.
export const SWATTED_TOPIC0 =
  "0x1229956b68c90a28dae8df061be5560051996c072cc849209604a7c8468d453e";

/** ABI-encode a call to a `<name>(uint16)` function with a single uint16 arg,
 * left-padded to 32 bytes per the standard Solidity ABI calling convention. */
export function encodeUint16Call(selectorHex, value) {
  const v = value & 0xffff;
  const argHex = v.toString(16).padStart(64, "0");
  return selectorHex + argHex;
}

/** Decode a `(bool, bool, bool)` ABI return value (3 x 32-byte words, each
 * 0 or 1 in the low byte). Returns [bool, bool, bool]. */
export function decodeBool3(hexData) {
  const data = hexData.startsWith("0x") ? hexData.slice(2) : hexData;
  const words = [data.slice(0, 64), data.slice(64, 128), data.slice(128, 192)];
  return words.map((w) => BigInt("0x" + (w || "0")) === 1n);
}

/** Decode a single uint256 ABI return value as a BigInt. */
export function decodeUint256(hexData) {
  const data = hexData.startsWith("0x") ? hexData.slice(2) : hexData;
  return BigInt("0x" + (data || "0"));
}
