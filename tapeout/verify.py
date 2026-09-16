"""Round-trip test harness + REAL-DATA validation for tapeout/format.py.

Two things this script does:

1. Round-trip: encode circuit/netlists/seed.json (and a couple of synthetic
   edge-case netlists) through tapeout.format.encode_netlist, decode the
   bytes back with decode_to_schema, and confirm the result matches the
   original. This is also exercised by tests/test_tapeout_format.py; this
   script re-runs it for a human-readable console report.

2. Real-data validation: fetch at least one already-minted circuit from the
   live "TapeOut" processor contract on BNB Smart Chain mainnet via a public
   read-only RPC endpoint (no wallet, no tx, no gas -- eth_call only), decode
   it with tapeout.format.decode_circuit, and sanity-report its structure
   (gate counts, latch count, byte length). Since the contract is not
   verified on BscScan, the ABI (function selectors) used here was
   independently recovered -- see `discover_abi_selectors` below and
   tapeout/SUBMISSION.md for the full method and certainty verdict.

Usage:
    python -m tapeout.verify                      # round-trip + live fetch (token #1, #5000)
    python -m tapeout.verify --no-network          # round-trip + fixture-only real-data check
    python -m tapeout.verify --token-id 14168      # also check an arbitrary token id
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

from tapeout import format as tf

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = REPO_ROOT / "circuit" / "netlists" / "seed.json"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

DEFAULT_RPC = "https://bsc-dataseed.binance.org"
CHAIN_ID_BSC_MAINNET = 56

# The "TapeOut" fab/processor contract: an ERC-721-shaped circuit registry.
# Address confirmed live against
# https://tapeout-public-monitor.tapeout-labs.workers.dev/api/v1/processors
# (name == "TapeOut", 100% minted, circuit_count == its own ownerOf()-backed
# token ids). This is a beacon-proxy; calls are made directly to the proxy,
# which delegates to the shared implementation.
PROCESSOR_ADDRESS = "0xb1024b89886b9a34aa4ff5f31c411d708b20a14c"
PROCESSOR_NAME = "TapeOut"

# Selectors recovered from the (unverified) processor implementation's
# bytecode -- see discover_abi_selectors() for the reproducible method.
SEL_NETLIST = "3fc4be56"          # netlist(uint256) returns (bytes)
SEL_CIRCUIT_INFO = "084d60f1"     # circuitInfo(uint256) returns (uint256 n_inputs, uint256 n_outputs, uint256 n_state, uint256 n_cells)
SEL_OWNER_OF = "6352211e"         # ownerOf(uint256) returns (address)  -- standard ERC-721, used only to sanity-check the token exists


def _rpc(url: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, data=body, headers={"content-type": "application/json", "user-agent": "nandfly-tapeout-verify/0.1"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(f"RPC error from {url}: {out['error']}")
    return out["result"]


def _eth_call(rpc_url: str, to: str, data_hex: str) -> str:
    return _rpc(rpc_url, "eth_call", [{"to": to, "data": data_hex}, "latest"])[2:]


def _call_with_token_id(rpc_url: str, to: str, selector: str, token_id: int) -> str:
    return _eth_call(rpc_url, to, "0x" + selector + format(token_id, "064x"))


def _decode_bytes_return(raw_hex: str) -> bytes:
    offset = int(raw_hex[0:64], 16)
    length = int(raw_hex[offset * 2 : offset * 2 + 64], 16)
    start = offset * 2 + 64
    return bytes.fromhex(raw_hex[start : start + length * 2])


def _decode_words(raw_hex: str) -> list:
    return [int(raw_hex[i : i + 64], 16) for i in range(0, len(raw_hex), 64)]


def discover_abi_selectors(rpc_url: str, implementation_address: str) -> dict:
    """Reproduce how SEL_NETLIST / SEL_CIRCUIT_INFO above were found, for
    anyone who wants to re-derive them independently rather than trust the
    hardcoded constants. Not called by default (network + a small pure-Python
    keccak256 pass over the whole implementation bytecode); pass
    --discover-abi to run it.
    """
    from tapeout._keccak import selector as sel

    code = _rpc(rpc_url, "eth_getCode", [implementation_address, "latest"])[2:]
    push4_operands = set()
    i = 0
    while i < len(code) - 10:
        if code[i : i + 2] == "63":  # PUSH4 opcode
            push4_operands.add(code[i + 2 : i + 10])
        i += 2

    candidates = [
        "netlist(uint256)",
        "circuitInfo(uint256)",
        "eval(uint256,bytes)",
        "ownerOf(uint256)",
        "tokenURI(uint256)",
        "name()",
        "symbol()",
    ]
    found = {}
    for sig in candidates:
        s = sel(sig)
        if s in push4_operands:
            found[sig] = s
    return found


def fetch_onchain_circuit(rpc_url: str, processor: str, token_id: int) -> dict:
    """Fetch one circuit's netlist bytes + declared port counts from a live
    TapeOut processor contract via read-only eth_call. Returns a dict with
    the same shape as the committed fixtures under tapeout/fixtures/."""
    owner_raw = _call_with_token_id(rpc_url, processor, SEL_OWNER_OF, token_id)
    owner = "0x" + owner_raw[-40:]

    info_raw = _call_with_token_id(rpc_url, processor, SEL_CIRCUIT_INFO, token_id)
    n_inputs, n_outputs, n_state, n_cells = _decode_words(info_raw)

    netlist_raw = _call_with_token_id(rpc_url, processor, SEL_NETLIST, token_id)
    netlist_bytes = _decode_bytes_return(netlist_raw)

    return {
        "token_id": token_id,
        "owner": owner,
        "circuit_info": {"n_inputs": n_inputs, "n_outputs": n_outputs, "n_state": n_state, "n_cells": n_cells},
        "netlist_hex": tf.to_hex(netlist_bytes),
    }


def sanity_report(circuit_info: dict, netlist_hex: str, label: str) -> None:
    data = tf.from_hex(netlist_hex)
    circuit = tf.decode_circuit(data, circuit_info["n_inputs"], circuit_info["n_outputs"])
    desc = circuit.describe()
    print(f"[{label}] decoded OK: {desc}")
    ok = desc["n_cells"] == circuit_info["n_cells"] and desc["latch"] == circuit_info["n_state"]
    print(f"[{label}] cross-check vs on-chain circuitInfo() (n_cells, n_state): {'OK' if ok else 'MISMATCH'}")
    if not ok:
        raise SystemExit(f"[{label}] decoded structure does not match circuitInfo()")


# ---------------------------------------------------------------------------
# Round-trip harness
# ---------------------------------------------------------------------------

SYNTHETIC_NETLISTS = {
    "single_nand": {
        "schema_version": 1,
        "gates": [{"id": "g1", "type": "NAND", "inputs": ["a", "b"]}],
        "input_pins": ["a", "b"],
        "output_pins": {"out": "g1"},
    },
    "latch_only": {
        "schema_version": 1,
        "gates": [{"id": "q", "type": "LATCH", "inputs": ["s", "r"]}],
        "input_pins": ["s", "r"],
        "output_pins": {"q": "q"},
    },
}


def run_roundtrip_report() -> bool:
    all_ok = True
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    cases = {"seed.json": {"gates": seed["gates"], "input_pins": seed["input_pins"], "output_pins": seed["output_pins"], "schema_version": seed["schema_version"]}}
    cases.update(SYNTHETIC_NETLISTS)

    for name, netlist in cases.items():
        data, meta = tf.encode_netlist(netlist)
        decoded = tf.decode_to_schema(data, meta)
        expected = {
            "schema_version": netlist["schema_version"],
            "gates": netlist["gates"],
            "input_pins": netlist["input_pins"],
            "output_pins": netlist["output_pins"],
        }
        ok = decoded == expected
        all_ok &= ok
        print(f"[roundtrip:{name}] {len(data)} bytes, {'OK' if ok else 'MISMATCH'}")
    return all_ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rpc", default=DEFAULT_RPC, help=f"JSON-RPC endpoint (default {DEFAULT_RPC})")
    ap.add_argument("--token-id", type=int, action="append", default=None, help="extra token id(s) to fetch live (repeatable)")
    ap.add_argument("--no-network", action="store_true", help="skip live RPC calls; validate committed fixtures instead")
    ap.add_argument("--discover-abi", action="store_true", help="re-derive the ABI selectors from bytecode instead of trusting the hardcoded ones")
    args = ap.parse_args()

    print("=== round-trip: our encoder/decoder on seed.json + synthetic netlists ===")
    roundtrip_ok = run_roundtrip_report()

    print()
    print("=== real-data validation ===")
    if args.no_network:
        for path in sorted(FIXTURES_DIR.glob("onchain_circuit_*.json")):
            fixture = json.loads(path.read_text(encoding="utf-8"))
            sanity_report(fixture["circuit_info"], fixture["netlist_hex"], path.stem)
    else:
        chain_id = int(_rpc(args.rpc, "eth_chainId", []), 16)
        print(f"RPC {args.rpc}: chain id {chain_id} ({'BSC mainnet' if chain_id == CHAIN_ID_BSC_MAINNET else 'UNEXPECTED CHAIN'})")
        if chain_id != CHAIN_ID_BSC_MAINNET:
            raise SystemExit("refusing to treat a non-BSC-mainnet response as ground truth")

        if args.discover_abi:
            impl = "0x8e1d125def6d3826c278299273a0760d47626068"
            found = discover_abi_selectors(args.rpc, impl)
            print("re-derived selectors present in implementation bytecode:", found)

        token_ids = [1, 5000] + (args.token_id or [])
        for token_id in token_ids:
            fetched = fetch_onchain_circuit(args.rpc, PROCESSOR_ADDRESS, token_id)
            label = f"{PROCESSOR_NAME}#{token_id} (owner {fetched['owner']})"
            sanity_report(fetched["circuit_info"], fetched["netlist_hex"], label)

    print()
    if not roundtrip_ok:
        raise SystemExit("round-trip FAILED")
    print("All checks passed.")


if __name__ == "__main__":
    main()
