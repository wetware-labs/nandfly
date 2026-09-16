"""Decoder-against-real-data test: decode two already-minted TapeOut
circuits' netlist bytes (fetched once from BNB Smart Chain mainnet via
public read-only RPC, no wallet/tx/gas -- see each fixture's `source` field
for the exact contract/token id/RPC call and how the unverified contract's
ABI was independently recovered) from the committed fixtures under
tapeout/fixtures/, using ONLY tapeout.format's generic decoder (no reliance
on any third-party tooling). This is the real-data validation half of
deliverable 2 -- see tapeout/verify.py for the live (network) version of the
same check, and tapeout/SUBMISSION.md for the full certainty verdict.

This test makes NO network calls; it is a pure regression test against the
committed fixture bytes.
"""
import json
from pathlib import Path

import pytest

from tapeout import format as tf

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tapeout" / "fixtures"

EXPECTED = {
    "onchain_circuit_1": {"n_inputs": 2, "n_outputs": 1, "n_cells": 3, "nand": 3, "latch": 0, "ref": 0, "bytes": 21},
    "onchain_circuit_5000": {"n_inputs": 0, "n_outputs": 8, "n_cells": 10, "nand": 1, "latch": 9, "ref": 0, "bytes": 43},
}


def _load(name):
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_files_exist_with_required_provenance_fields(name):
    fixture = _load(name)
    assert fixture["source"]["chain_id"] == 56
    assert fixture["source"]["contract"] == "0xb1024b89886b9a34aa4ff5f31c411d708b20a14c"
    assert "token_id" in fixture["source"]
    assert "fetched_at" in fixture["source"]
    assert fixture["netlist_hex"].startswith("0x")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_decode_real_onchain_bytes_matches_expected_structure(name):
    fixture = _load(name)
    info = fixture["circuit_info"]
    data = tf.from_hex(fixture["netlist_hex"])

    circuit = tf.decode_circuit(data, info["n_inputs"], info["n_outputs"])
    desc = circuit.describe()

    expected = EXPECTED[name]
    assert desc["n_inputs"] == expected["n_inputs"]
    assert desc["n_outputs"] == expected["n_outputs"]
    assert desc["n_cells"] == expected["n_cells"]
    assert desc["nand"] == expected["nand"]
    assert desc["latch"] == expected["latch"]
    assert desc["ref"] == expected["ref"]
    assert desc["bytes"] == expected["bytes"]

    # Cross-check against the circuit's own on-chain circuitInfo() reading,
    # independently of our own EXPECTED constants above.
    assert desc["n_cells"] == info["n_cells"]
    assert desc["latch"] == info["n_state"]


def test_onchain_circuit_5000_exercises_a_forward_referencing_latch():
    """This specific real circuit (a 9-stage ring counter/shift register) is
    the one piece of ground truth we have for the "LATCH.d may point to a
    signal defined later in the cell list" rule (tapeout/format.py's module
    docstring) -- its first LATCH cell's d references the last LATCH cell's
    output, defined 9 cells later."""
    fixture = _load("onchain_circuit_5000")
    data = tf.from_hex(fixture["netlist_hex"])
    cells = tf.decode_cells(data, n_inputs=fixture["circuit_info"]["n_inputs"])
    first_latch = cells[0]
    assert isinstance(first_latch, tf.Latch)
    assert first_latch.d == 10  # signal 10 is produced by the 8th LATCH cell, defined later
