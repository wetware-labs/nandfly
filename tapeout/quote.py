"""Live TapeOut cost quote: current component (NAND/LATCH) prices, current
BNB/USD, current BSC gas price, a tape-out (mint) gas estimate, and a quote
table for the seed (2 NAND + 1 LATCH) plus hypothetical 10/50/100-gate
extensions. Writes reports/tapeout-quote.md.

Data sources, each timestamped in the output:
    - Processor registry (mint price, sold-out status):
      https://tapeout-public-monitor.tapeout-labs.workers.dev/api/v1/processors
      (live re-fetch every run)
    - BNB/USD: CoinGecko public API (live re-fetch every run)
    - BSC gas price: eth_gasPrice via public RPC (live re-fetch every run)
    - Secondary-market NAND/LATCH best-bid prices: the "TapeOut" fab is
      100%-minted (see the live registry re-fetch below), so components can
      only be acquired on the secondary order-book market
      (tapeout.market, contract 0x6feebbebc07bcb90bd1ac8b0cf9baa4f0ff2b46f,
      1% fee). This script does NOT re-derive live order-book depth (that
      contract's ABI has not been probed -- out of scope for this task); it
      reuses the same-day snapshot from the project's feasibility spike
      (C:\\Users\\gmldn\\Documents\\Codex\\_spikes\\tapeout-fly-spike\\findings.md
      section 1, source: understand-tapeout.netlify.app, 2026-09-01 snapshot)
      and flags this explicitly as NOT live-refreshed, with a volatility
      caveat, in the output report.

Run: python -m tapeout.quote
"""
from __future__ import annotations

import datetime
import json
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = REPO_ROOT / "reports" / "tapeout-quote.md"

DEFAULT_RPC = "https://bsc-dataseed.binance.org"
PROCESSOR_REGISTRY_URL = "https://tapeout-public-monitor.tapeout-labs.workers.dev/api/v1/processors"
COINGECKO_BNB_URL = "https://api.coingecko.com/api/v3/simple/price?ids=binancecoin&vs_currencies=usd"

# Secondary-market snapshot, NOT re-fetched live by this script -- see module
# docstring. Source: spike findings.md section 1, understand-tapeout.netlify.app,
# snapshot 2026-09-01, matched against the on-chain order-book market contract
# 0x6feebbebc07bcb90bd1ac8b0cf9baa4f0ff2b46f.
SECONDARY_MARKET_SNAPSHOT = {
    "snapshot_date": "2026-09-01",
    "source": "understand-tapeout.netlify.app (community order-book explainer), cross-referenced against market contract 0x6feebbebc07bcb90bd1ac8b0cf9baa4f0ff2b46f",
    "fab": "TapeOut",
    "nand_bnb": 0.006,
    "latch_bnb": 0.00487,
}

# Illustrative gate-mix assumptions for the hypothetical extensions, mirroring
# the spike's own methodology ("circuits are almost all-NAND with a handful
# of LATCHes for state"). These are NOT a proposed circuit design -- just a
# pricing assumption, stated explicitly so the table is auditable.
HYPOTHETICAL_SIZES = [
    (10, 8, 2),
    (50, 46, 4),
    (100, 94, 6),
]

# Rough gas-usage assumption for a tape-out (mint) transaction. UNCONFIRMED:
# see tapeout/SUBMISSION.md -- the write/mint function signature was not
# identified from bytecode probing (only the read functions netlist()/
# circuitInfo() were). This uses the spike's own $2-10 estimate range,
# cross-checked here against a live gas price for the calldata-only floor
# (actual execution gas -- SSTORE-heavy ERC-721 mint + ERC-1155 burns -- is
# not modeled and could dominate; see caveat in the report).
ASSUMED_EXECUTION_GAS = 150_000  # order-of-magnitude guess for mint bookkeeping (unconfirmed)


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"user-agent": "nandfly-tapeout-quote/0.1"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _rpc(url: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        out = json.loads(resp.read())
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def fetch_live_data(rpc_url: str = DEFAULT_RPC) -> dict:
    bnb_usd = _get_json(COINGECKO_BNB_URL)["binancecoin"]["usd"]

    registry = _get_json(PROCESSOR_REGISTRY_URL)
    tapeout_fab = next(p for p in registry["items"] if p["name"] == "TapeOut")
    mint_price_bnb = int(tapeout_fab["mint_price"]) / 1e18
    sold_out = int(tapeout_fab["minted"]) >= int(tapeout_fab["supply_cap"])

    gas_price_wei = int(_rpc(rpc_url, "eth_gasPrice", []), 16)

    return {
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "bnb_usd": bnb_usd,
        "tapeout_fab": {
            "mint_price_bnb": mint_price_bnb,
            "minted": int(tapeout_fab["minted"]),
            "supply_cap": int(tapeout_fab["supply_cap"]),
            "sold_out": sold_out,
            "circuit_count": tapeout_fab["circuit_count"],
            "registry_observed_at": tapeout_fab.get("observed_at"),
        },
        "gas_price_wei": gas_price_wei,
    }


def gas_cost_bnb(gas_price_wei: int, netlist_byte_len: int) -> float:
    """Calldata gas (EIP-2028: 16 gas/nonzero byte, 4 gas/zero byte -- here
    upper-bounded at 16/byte since we don't know the real byte distribution
    ahead of time) + a base 21000 + ASSUMED_EXECUTION_GAS bookkeeping
    estimate. See ASSUMED_EXECUTION_GAS docstring above for the caveat."""
    calldata_gas = netlist_byte_len * 16
    total_gas = 21_000 + calldata_gas + ASSUMED_EXECUTION_GAS
    return total_gas * gas_price_wei / 1e18


def quote_row(n_nand: int, n_latch: int, live: dict, netlist_byte_len_estimate: int) -> dict:
    component_bnb = n_nand * SECONDARY_MARKET_SNAPSHOT["nand_bnb"] + n_latch * SECONDARY_MARKET_SNAPSHOT["latch_bnb"]
    gas_bnb = gas_cost_bnb(live["gas_price_wei"], netlist_byte_len_estimate)
    total_bnb = component_bnb + gas_bnb
    return {
        "gates": n_nand + n_latch,
        "nand": n_nand,
        "latch": n_latch,
        "component_bnb": component_bnb,
        "component_usd": component_bnb * live["bnb_usd"],
        "gas_bnb": gas_bnb,
        "gas_usd": gas_bnb * live["bnb_usd"],
        "total_bnb": total_bnb,
        "total_usd": total_bnb * live["bnb_usd"],
    }


def build_report(live: dict) -> str:
    lines = []
    lines.append("# TapeOut cost quote")
    lines.append("")
    lines.append(f"Generated: {live['fetched_at']} (live re-fetch of BNB/USD, processor registry, and BSC gas price -- see tapeout/quote.py)")
    lines.append("")
    lines.append(
        "**Price-volatility caveat:** every number below is a point-in-time snapshot. "
        "BNB/USD and BSC gas price were re-fetched live for this run; NAND/LATCH secondary-market "
        f"prices were NOT (see snapshot below, dated {SECONDARY_MARKET_SNAPSHOT['snapshot_date']}) -- "
        "component prices on this platform have moved >20%/day on documented occasions "
        "(see feasibility spike findings.md section 1). Treat all totals as order-of-magnitude, "
        "not a firm quote, until re-run immediately before any real spend (Task 5)."
    )
    lines.append("")

    lines.append("## Live inputs")
    lines.append("")
    lines.append(f"- BNB/USD: **${live['bnb_usd']:.2f}** (CoinGecko, live)")
    lines.append(
        f"- TapeOut fab primary mint price: {live['tapeout_fab']['mint_price_bnb']} BNB/unit, "
        f"minted {live['tapeout_fab']['minted']:,} / {live['tapeout_fab']['supply_cap']:,} "
        f"({'SOLD OUT -- primary mint unavailable, secondary market required' if live['tapeout_fab']['sold_out'] else 'still minting'})"
    )
    lines.append(f"- BSC gas price: {live['gas_price_wei'] / 1e9:g} gwei (live eth_gasPrice)")
    lines.append(
        f"- NAND secondary best-bid: {SECONDARY_MARKET_SNAPSHOT['nand_bnb']} BNB "
        f"(~${SECONDARY_MARKET_SNAPSHOT['nand_bnb'] * live['bnb_usd']:.2f}), "
        f"LATCH: {SECONDARY_MARKET_SNAPSHOT['latch_bnb']} BNB "
        f"(~${SECONDARY_MARKET_SNAPSHOT['latch_bnb'] * live['bnb_usd']:.2f}) "
        f"-- **snapshot dated {SECONDARY_MARKET_SNAPSHOT['snapshot_date']}, NOT live-refreshed this run** "
        f"(source: {SECONDARY_MARKET_SNAPSHOT['source']})"
    )
    lines.append("")

    lines.append("## Quote table")
    lines.append("")
    lines.append(
        "Gas is a **rough estimate**: calldata cost (16 gas/byte, live gas price) plus an "
        f"UNCONFIRMED {ASSUMED_EXECUTION_GAS:,}-gas allowance for mint bookkeeping -- the exact "
        "tape-out/mint write function was not identified from bytecode probing (only the read "
        "functions netlist()/circuitInfo() were; see tapeout/SUBMISSION.md). Cross-check against "
        "the feasibility spike's own $2-10/tx estimate (BSC gas is cheap regardless of the exact function)."
    )
    lines.append("")
    lines.append("| Circuit | Gates (NAND+LATCH) | Netlist bytes (est.) | Component cost | Gas (est.) | **Total** |")
    lines.append("|---|---|---|---|---|---|")

    seed_nand, seed_latch = 2, 1
    seed_bytes = 21  # 2*7 (NAND) + 1*4 (LATCH) -- naive "2N+1L" gate count
    seed_row = quote_row(seed_nand, seed_latch, live, seed_bytes)
    lines.append(
        f"| seed, naive \"2 NAND + 1 LATCH\" gate count | {seed_row['gates']} | {seed_bytes} | "
        f"{seed_row['component_bnb']:.5f} BNB (${seed_row['component_usd']:.2f}) | "
        f"{seed_row['gas_bnb']:.6f} BNB (${seed_row['gas_usd']:.4f}) | "
        f"**{seed_row['total_bnb']:.5f} BNB (${seed_row['total_usd']:.2f})** |"
    )

    # TRUE on-chain component cost: our LATCH gate is an SR-latch, which
    # TapeOut cannot express as a bare primitive (its own LATCH is a
    # single-input D-register -- see tapeout/format.py's module docstring).
    # Reproducing our exact SR semantics costs 1 native LATCH + 4 NAND
    # PRIMITIVES, on the canvas exactly as much as via direct bytes -- this
    # is not a submission-path artifact, it is the real cost of the gate.
    # 2 original NAND + 4 SR-latch-translation NAND + 2 output-identity-buffer NAND
    # (tapeout/format.py's encoder always emits an output buffer for generality/
    # simplicity, even though jump_left already happens to be the last-defined
    # gate here -- a size-optimizing encoder could special-case that and save
    # 2 NAND/14 bytes; this project's encoder does not, intentionally, to stay
    # simple and correct for the general case -- see tapeout/SUBMISSION.md).
    true_nand, true_latch = seed_nand + 4 + 2, seed_latch
    true_bytes = 60  # tapeout/format.py's actual encode_netlist(seed.json) output
    true_row = quote_row(true_nand, true_latch, live, true_bytes)
    lines.append(
        f"| **seed, TRUE on-chain cost ({true_nand} NAND + {true_latch} LATCH primitives -- see note below)** | "
        f"{true_row['gates']} | {true_bytes} | "
        f"{true_row['component_bnb']:.5f} BNB (${true_row['component_usd']:.2f}) | "
        f"{true_row['gas_bnb']:.6f} BNB (${true_row['gas_usd']:.4f}) | "
        f"**{true_row['total_bnb']:.5f} BNB (${true_row['total_usd']:.2f})** |"
    )

    for total_gates, n_nand, n_latch in HYPOTHETICAL_SIZES:
        byte_estimate = n_nand * 7 + n_latch * 4
        row = quote_row(n_nand, n_latch, live, byte_estimate)
        lines.append(
            f"| hypothetical {total_gates} gates ({n_nand} NAND + {n_latch} LATCH, illustrative mix) | "
            f"{row['gates']} | {byte_estimate} | "
            f"{row['component_bnb']:.5f} BNB (${row['component_usd']:.2f}) | "
            f"{row['gas_bnb']:.6f} BNB (${row['gas_usd']:.4f}) | "
            f"**{row['total_bnb']:.5f} BNB (${row['total_usd']:.2f})** |"
        )

    lines.append("")
    lines.append(
        "**Important correction to the project's earlier \"~$12, 2N+1L\" estimate** "
        "(docs/plans/2026-09-16-nandfly-mvp.md progress ledger): our LATCH gate is an SR-latch, and "
        "TapeOut's only native stateful primitive is a single-input D-register -- it cannot express "
        "SR set/reset semantics as a bare primitive. Reproducing the seed's exact behavior therefore "
        "costs 1 native LATCH + 4 extra NAND primitives (tapeout/format.py's module docstring has the "
        "derivation), REGARDLESS of submission path: a canvas build would need those same 4 NAND gates "
        "hand-wired, not just a direct-bytes one. The naive \"2N+1L\" row above understates the real "
        "cost; use the \"TRUE on-chain cost\" row for budgeting."
    )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Component prices assume the cheapest liquid fab (TapeOut) best-bid, not ask/depth -- buying "
        "in bulk may walk the book higher (see spike findings.md caveats)."
    )
    lines.append(
        "- Hypothetical 10/50/100-gate rows use the naive gate count (their NAND/LATCH split is already "
        "illustrative/assumed, not a real design), for order-of-magnitude comparison only."
    )
    lines.append("- Re-run `python -m tapeout.quote` immediately before Task 5's real spend for fresh numbers.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    live = fetch_live_data()
    report = build_report(live)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"wrote {REPORT_PATH}")
    print()
    print(report)


if __name__ == "__main__":
    main()
