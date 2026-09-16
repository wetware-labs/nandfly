"""Extract soma positions for the whole-brain point cloud (site "The whole
brain" section) from a local MaleCNS v1.0 download.

Reads `annotations.feather` (columns: bodyId, somaLocation) from a local
MaleCNS v1.0 checkout -- the same public dataset the derivation used (see
circuit/DERIVATION.md section 1 for the original download URLs). The raw
data is NOT committed; this script and its outputs are, so anyone with the
public dataset can regenerate and diff:

    python site/scripts/extract_brain_points.py <path-to-malecns_v1-dir>

Outputs (committed):
  site/data/brain-points.bin   -- N dim points, 3x uint16 LE per point
                                  (x, y, z), quantized to the soma bounding
                                  box. Deterministic: valid neurons sorted
                                  by bodyId, uniform stride decimation, no
                                  RNG anywhere.
  site/data/brain-points.json  -- honesty manifest: dataset totals, how many
                                  neurons have soma positions, how many are
                                  shown, quantization params, and the 16
                                  on-chain neurons with their real positions.

`somaLocation` is an Arrow list<int64> column ([x, y, z] per row, null for
neurons without an annotated soma). circuit/lib/arrow_feather.py's public
read_feather() flattens list children and drops the offsets, so this script
uses the module's internal batch primitives to recover the parent list's
validity + offsets buffers explicitly. It touches only our own committed
reader -- no new dependencies.
"""

import json
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from circuit.lib import arrow_feather as af  # noqa: E402

NETLIST_PATH = REPO_ROOT / "circuit" / "netlists" / "full.json"
OUT_BIN = REPO_ROOT / "site" / "data" / "brain-points.bin"
OUT_MANIFEST = REPO_ROOT / "site" / "data" / "brain-points.json"

# Desktop render budget. 30k points x 6 bytes = 180 KB -- well under the
# 600 KB budget; the mobile renderer strides over the same file client-side.
TARGET_DIM_POINTS = 30_000

# MaleCNS v1.0 headline count, used for the "shown / total" honesty line.
DATASET_HEADLINE_NEURONS = 166_700


def read_soma_positions(annotations_path: Path):
    """Return (body_ids, positions) for every row whose somaLocation is a
    3-element list. Uses arrow_feather internals to get list offsets."""
    f = af.open_feather(str(annotations_path))

    # Patch a copy of the layout: rename the list PARENT entry (kind 'skip',
    # 2 buffers: validity + int32 offsets) so _read_record_batch_columns
    # keeps its raw buffers instead of skipping them. The child int64 values
    # keep the original name.
    layout = []
    seen_parent = False
    for spec in f.layout:
        spec = dict(spec)
        if spec["name"] == "somaLocation" and spec["kind"] == "skip" and not seen_parent:
            seen_parent = True
            spec["name"] = "somaLocation__parent"
            # 'utf8' kind keeps 3 buffers; the list parent has only 2. Use a
            # fake int kind purely so the raw buffers are retained; we decode
            # the offsets ourselves below.
            spec["kind"] = "int"
            spec["bitwidth"] = 32
            spec["signed"] = True
        layout.append(spec)
    if not seen_parent:
        raise SystemExit("annotations.feather: no somaLocation list column found")

    want = {"bodyId", "somaLocation", "somaLocation__parent"}
    body_ids = []
    positions = []
    stats = {"rows": 0, "with_soma": 0, "malformed": 0}

    for rb_i in range(f.n_rbs):
        off, _meta, _body = af._read_block(f.rb_buf, f.rb_start, rb_i)
        header_type, header, body_start = af._parse_message_at(f.buf, off)
        assert header_type == af.MESSAGE_HEADER_RECORD_BATCH
        cols = af._read_record_batch_columns(f.buf, header, body_start, layout, want)

        bid = af._to_numpy(cols["bodyId"])
        parent = cols["somaLocation__parent"]
        n = parent["length"]
        offsets = np.frombuffer(parent["data"], dtype="<i4", count=n + 1)
        child = af._to_numpy(cols["somaLocation"])

        stats["rows"] += n
        lengths = offsets[1:] - offsets[:-1]
        for i in range(n):
            if lengths[i] == 3:
                p = child[offsets[i]: offsets[i] + 3]
                body_ids.append(int(bid[i]))
                positions.append((float(p[0]), float(p[1]), float(p[2])))
                stats["with_soma"] += 1
            elif lengths[i] != 0:
                stats["malformed"] += 1

    return np.array(body_ids, dtype=np.int64), np.array(positions, dtype=np.float64), stats


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: extract_brain_points.py <path-to-malecns_v1-dir>")
    data_dir = Path(sys.argv[1])
    annotations = data_dir / "annotations.feather"
    if not annotations.exists():
        raise SystemExit(f"not found: {annotations}")

    netlist = json.loads(NETLIST_PATH.read_text())
    onchain = {n["neuron_id"]: n for n in netlist["neuron_gate_map"]}

    body_ids, positions, stats = read_soma_positions(annotations)
    print(f"rows={stats['rows']} with_soma={stats['with_soma']} malformed={stats['malformed']}")

    # Deterministic order: sort by bodyId.
    order = np.argsort(body_ids, kind="stable")
    body_ids = body_ids[order]
    positions = positions[order]

    # Quantization box over ALL soma positions (so the highlighted neurons
    # and the dim cloud share one coordinate frame).
    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    span = np.where(hi - lo == 0, 1.0, hi - lo)

    def quantize(p):
        q = np.round((p - lo) / span * 65535.0)
        return np.clip(q, 0, 65535).astype(np.uint16)

    # The 16 on-chain neurons, with real positions where the dataset has
    # them. Any without an annotated soma are reported, not invented.
    highlighted = []
    missing = []
    id_to_idx = {int(b): i for i, b in enumerate(body_ids)}
    for nid, meta in sorted(onchain.items()):
        if nid in id_to_idx:
            q = quantize(positions[id_to_idx[nid]])
            highlighted.append({
                "bodyId": nid,
                "label": f"{meta['type']} - {meta['side']}",
                "role": meta["role"],
                "pos": [int(q[0]), int(q[1]), int(q[2])],
            })
        else:
            missing.append(nid)
    if missing:
        print(f"WARNING: {len(missing)} on-chain neurons lack soma positions: {missing}")

    # Dim cloud: everything except the on-chain 16, uniform stride to the
    # target count. Stride on the bodyId-sorted array = deterministic.
    mask = np.array([int(b) not in onchain for b in body_ids])
    dim_pos = positions[mask]
    stride = max(1, len(dim_pos) // TARGET_DIM_POINTS)
    dim_pos = dim_pos[::stride][:TARGET_DIM_POINTS]

    q = quantize(dim_pos)
    OUT_BIN.parent.mkdir(parents=True, exist_ok=True)
    q.astype("<u2").tofile(OUT_BIN)

    manifest = {
        "source": "MaleCNS v1.0 annotations.feather, somaLocation column (soma positions; anatomy, not wiring)",
        "dataset_headline_neurons": DATASET_HEADLINE_NEURONS,
        "annotation_rows": stats["rows"],
        "neurons_with_soma_position": stats["with_soma"],
        "malformed_location_rows": stats["malformed"],
        "dim_points_shown": int(len(dim_pos)),
        "decimation": f"bodyId-sorted uniform stride {stride} (deterministic, no RNG)",
        "quantization": {
            "format": "3x uint16 little-endian per point",
            "box_min": [float(x) for x in lo],
            "box_max": [float(x) for x in hi],
        },
        "onchain_neurons": highlighted,
        "onchain_neurons_missing_soma": missing,
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {OUT_BIN} ({OUT_BIN.stat().st_size} bytes) and {OUT_MANIFEST}")
    print(f"highlighted={len(highlighted)} missing={len(missing)} dim={len(dim_pos)}")


if __name__ == "__main__":
    main()
