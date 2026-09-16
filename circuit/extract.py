"""Extract the Giant Fiber (GF) escape-reflex core subgraph from MaleCNS v1.0.

This is an INDEPENDENT derivation: selection criteria below were chosen by
inspecting MaleCNS v1.0's own `annotations.feather` `type` column and the
published GF pathway anatomy (LC4/LPLC2 visual projection neurons -> DNp01
"Giant Fiber" descending neuron -> TTMn tergotrochanteral "jump muscle" motor
neuron), NOT by reading any third-party netlist.

--------------------------------------------------------------------------
What we found in MaleCNS v1.0's annotations.feather `type` column
--------------------------------------------------------------------------
(counts below are from the real, full 166,700-neuron retained dataset;
`node_id -> retained` uses the same policy as FlyMarket's
sim/build_connectome.py, reused here: `superclass` non-null/non-empty AND
`status` != 'Glia' -- see `retained_mask()`)

  DNp01        : 2 neurons  (somaSide L=1, R=1)      -- the Giant Fiber itself
  LC4          : 126 neurons (somaSide L=71, R=55)   -- lobula columnar, looming-tuned
  LPLC2        : 185 neurons (somaSide L=94, R=91)   -- lobula-plate/lobula columnar, looming-tuned
  TTMn         : 2 neurons  (somaSide L=1, R=1)      -- tergotrochanteral "jump muscle" motor neuron
  DLMn a, b    : 2 neurons  (somaSide L=1, R=1)       -- dorsal longitudinal "flight muscle" motor neuron (a/b subtype)
  DLMn c-f     : 8 neurons  (somaSide L=4, R=4)       -- dorsal longitudinal flight muscle motor neuron (c-f subtype)

Also present but NOT used here (documented for honesty, not fabricated):
  GFC1..GFC4   : 3+10+13+8 = 34 neurons, superclass=vnc_intrinsic. These look
  like a MaleCNS-curated "Giant Fiber Circuit" auxiliary family, but the task
  brief scopes this extraction to the well-published LC4/LPLC2 -> DNp01 ->
  TTMn/DLMn path specifically, so GFC1-4 are left out of this v1 subgraph.
  A future extension could fold them in as an intermediate stage.

--------------------------------------------------------------------------
Edge-level finding that shaped the final neuron set (see DERIVATION.md)
--------------------------------------------------------------------------
Every single LC4 and LPLC2 neuron on a given side synapses directly onto
DNp01 of THE SAME side (71/71 LC4-L, 55/55 LC4-R, 94/94 LPLC2-L, 91/91
LPLC2-R have >=1 direct chemical synapse onto ipsilateral DNp01) -- an
ipsilateral, all-to-one convergence, matching the published anatomy of the
GF's dendritic looming-input zone.

DNp01 has exactly ONE outgoing synapse onto TTMn per side (weight 20 on the
left, 70 on the right, chemical synapse COUNT only -- see DERIVATION.md's
limitations section re: the well-documented GF-TTMn electrical/gap-junction
component, which synapse-count data cannot see).

DNp01 has ZERO direct synapses onto any DLMn subtype in MaleCNS v1.0. This
matches the published circuit: GF's flight-muscle pathway is indirect, via
the PSI (peripherally synapsing interneuron) neuron, which is out of scope
for this extraction (the task brief says to use TTMn/DLMn "as available";
DLMn turned out not to be directly available, so it is excluded from the
wired subgraph and only recorded as an investigated-but-unconnected type).

--------------------------------------------------------------------------
Top-K selection (this is the one deliberate lossy/design step)
--------------------------------------------------------------------------
Feeding all 71+94=165 (or 55+91=146) visual inputs into one binarized
threshold unit's adder tree is real to the data, but produces a NAND-gate
adder tree an order of magnitude larger than the project's netlist can
usefully be. We instead keep, per side, the TOP_K=3 highest-synapse-weight
LC4 neurons and TOP_K=3 highest-synapse-weight LPLC2 neurons onto ipsilateral
DNp01 (6 visual inputs per hemisphere, 12 total) -- the strongest, most
reliable channels of the real convergence, not a fabricated substitute for
it. TOP_K is a module constant so the selection is trivially reproducible
and adjustable.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from circuit.lib.arrow_feather import iter_feather_batches, read_feather

DEFAULT_RAW_DIR = Path("circuit/data/malecns_v1")
DEFAULT_OUT = Path("circuit/data/subgraph.json")

GF_TYPE = "DNp01"
VISUAL_TYPES = ("LC4", "LPLC2")
MOTOR_CANDIDATE_TYPES = ("TTMn", "DLMn a, b", "DLMn c-f")
ALL_CANDIDATE_TYPES = (GF_TYPE,) + VISUAL_TYPES + MOTOR_CANDIDATE_TYPES

TOP_K = 3  # strongest-synapse-weight visual inputs kept per population per side

# Same transmitter -> sign policy as FlyMarket's sim/build_connectome.py
# (itself mirroring DOOMFLY's doom/transmitters.py): +1 acetylcholine,
# -1 GABA/glutamate/histamine, +1 (ambiguous default) otherwise.
#
# KNOWN LIMITATION, disclosed here rather than left for someone else to
# find: mapping glutamate -> -1 (inhibitory) is a reasonable population-level
# default in the insect CNS generally, but it is WRONG specifically for
# motor neurons at the Drosophila neuromuscular junction, where glutamate is
# the EXCITATORY transmitter. TTMn (this circuit's jump-motor neuron) is
# glutamatergic in MaleCNS v1.0, so its recorded sign here is backwards for
# what TTMn actually does biologically. This is harmless in the GF circuit
# built by circuit/binarize.py -- TTMn is a leaf/output neuron with no
# outgoing edges in this subgraph, so its sign is recorded but never read to
# flip an edge weight -- see circuit/DERIVATION.md section 3.
TRANSMITTER_POSITIVE = {"acetylcholine"}
TRANSMITTER_NEGATIVE = {"gaba", "glutamate", "histamine"}


def transmitter_sign(consensus_nt, ambiguous_sign: int = 1) -> int:
    if consensus_nt is None:
        return ambiguous_sign
    v = str(consensus_nt).lower()
    if v in TRANSMITTER_POSITIVE:
        return 1
    if v in TRANSMITTER_NEGATIVE:
        return -1
    return ambiguous_sign


def retained_mask(annotations: dict) -> np.ndarray:
    """Node-retention policy reused from FlyMarket's sim/build_connectome.py
    (a non-null, non-empty `superclass` AND `status` != 'Glia')."""
    superclass = annotations["superclass"]
    status = annotations["status"]
    non_empty = np.array([s is not None and str(s) != "" for s in superclass], dtype=bool)
    not_glia = np.array([s != "Glia" for s in status], dtype=bool)
    return non_empty & not_glia


def neurons_of_type(annotations: dict, retained: np.ndarray, type_name: str) -> dict:
    """Returns {body_id: soma_side} for retained neurons of the given type."""
    type_ = annotations["type"]
    body_id = annotations["bodyId"].astype(np.int64)
    soma_side = annotations["somaSide"]
    is_type = np.array([str(t) == type_name for t in type_], dtype=bool) & retained
    return {int(b): s for b, s in zip(body_id[is_type], soma_side[is_type])}


def top_k_by_weight(pre_ids_with_weight: list, k: int) -> list:
    """pre_ids_with_weight: list of (body_id, weight). Returns the k entries
    with the highest weight, ties broken by body_id ascending (deterministic)."""
    return sorted(pre_ids_with_weight, key=lambda pw: (-pw[1], pw[0]))[:k]


def build_subgraph(
    node_types: dict,          # type_name -> {body_id: side}
    consensus_nt: dict,        # body_id -> consensus_nt string or None
    candidate_edges: list,     # list of (pre_id, post_id, raw_weight)
    top_k: int = TOP_K,
) -> dict:
    """Pure assembly of the subgraph JSON from already-extracted candidate
    data (no file I/O -- see main() for the MaleCNS-file-reading driver).
    `candidate_edges` should contain every edge among the candidate neuron
    IDs (all types in ALL_CANDIDATE_TYPES); this function applies the
    ipsilateral-convergence + top-K selection documented in the module
    docstring and returns only the edges actually kept."""
    type_of, side_of = {}, {}
    for type_name, ids in node_types.items():
        for body_id, side in ids.items():
            type_of[body_id] = type_name
            side_of[body_id] = side

    gf_ids = node_types.get(GF_TYPE, {})
    gf_by_side = {side: bid for bid, side in gf_ids.items()}

    # Visual -> GF candidate weights, split by (visual_type, side)
    visual_weight_by_side = {t: {"L": [], "R": []} for t in VISUAL_TYPES}
    for pre, post, w in candidate_edges:
        if type_of.get(post) != GF_TYPE or type_of.get(pre) not in VISUAL_TYPES:
            continue
        side = side_of.get(pre)
        if side not in ("L", "R") or side_of.get(post) != side:
            continue  # only ipsilateral convergence is used (see docstring)
        visual_weight_by_side[type_of[pre]][side].append((pre, w))

    kept_visual = {}  # body_id -> (type, side, weight)
    for t in VISUAL_TYPES:
        for side in ("L", "R"):
            for pre, w in top_k_by_weight(visual_weight_by_side[t][side], top_k):
                kept_visual[pre] = (t, side, w)

    # GF -> TTMn direct edges (motor path); DLMn checked but excluded (see docstring)
    motor_edges = []
    ttmn_ids = node_types.get("TTMn", {})
    for pre, post, w in candidate_edges:
        if type_of.get(pre) != GF_TYPE or type_of.get(post) != "TTMn":
            continue
        if side_of.get(pre) != side_of.get(post):
            continue
        motor_edges.append((pre, post, w))

    excluded = {}
    for motor_type in ("DLMn a, b", "DLMn c-f"):
        ids = node_types.get(motor_type, {})
        has_direct_edge = any(
            type_of.get(pre) == GF_TYPE and type_of.get(post) == motor_type
            for pre, post, _w in candidate_edges
        )
        excluded[motor_type] = {
            "found_in_annotations": len(ids),
            "direct_synapse_from_DNp01": has_direct_edge,
            "reason_excluded": (
                "no direct chemical synapse from DNp01 in MaleCNS v1.0; "
                "GF's flight-muscle output is known to be indirect, via the "
                "PSI interneuron, which is out of scope for this extraction"
            ) if not has_direct_edge else "has a direct synapse but not selected",
        }

    neurons = []
    for body_id, side in gf_ids.items():
        neurons.append({
            "id": body_id, "type": GF_TYPE, "side": side, "role": "gf",
            "transmitter": consensus_nt.get(body_id),
            "sign": transmitter_sign(consensus_nt.get(body_id)),
        })
    for body_id, (t, side, w) in kept_visual.items():
        neurons.append({
            "id": body_id, "type": t, "side": side, "role": "visual_input",
            "transmitter": consensus_nt.get(body_id),
            "sign": transmitter_sign(consensus_nt.get(body_id)),
            "synapse_weight_onto_gf": w,
        })
    for body_id, side in ttmn_ids.items():
        neurons.append({
            "id": body_id, "type": "TTMn", "side": side, "role": "jump_motor",
            "transmitter": consensus_nt.get(body_id),
            "sign": transmitter_sign(consensus_nt.get(body_id)),
        })

    edges = []
    for body_id, (t, side, w) in kept_visual.items():
        gf_id = gf_by_side.get(side)
        if gf_id is None:
            continue
        edges.append({"pre": body_id, "post": gf_id, "weight": w,
                       "sign": transmitter_sign(consensus_nt.get(body_id))})
    for pre, post, w in motor_edges:
        edges.append({"pre": pre, "post": post, "weight": w,
                       "sign": transmitter_sign(consensus_nt.get(pre))})

    return {
        "meta": {
            "gf_type": GF_TYPE,
            "visual_types": list(VISUAL_TYPES),
            "motor_candidate_types": list(MOTOR_CANDIDATE_TYPES),
            "top_k": top_k,
            "selection": (
                f"top-{top_k} by ipsilateral synapse weight onto DNp01, "
                "per visual type per side"
            ),
        },
        "candidate_population_counts": {
            t: {side: sum(1 for s in ids.values() if s == side) for side in ("L", "R")}
            for t, ids in node_types.items()
        },
        "excluded_motor_types": excluded,
        "neurons": neurons,
        "edges": edges,
    }


def stream_candidate_edges(raw_dir: Path, candidate_ids: set) -> list:
    """Stream edges.feather (large, not vendored in-repo) and keep only rows
    where both endpoints are in `candidate_ids`. Not covered by pytest (no
    real MaleCNS data fixture that size); exercised via `python -m
    circuit.extract`, see DERIVATION.md for the exact command and runtime."""
    candidate_arr = np.array(sorted(candidate_ids), dtype=np.int64)
    rows = []
    for batch in iter_feather_batches(raw_dir / "edges.feather",
                                       want={"body_pre", "body_post", "weight"}):
        bp = np.asarray(batch["body_pre"], dtype=np.int64)
        bq = np.asarray(batch["body_post"], dtype=np.int64)
        w = np.asarray(batch["weight"], dtype=np.int64)
        mask = np.isin(bp, candidate_arr) & np.isin(bq, candidate_arr)
        if mask.any():
            idx = np.where(mask)[0]
            rows.extend((int(bp[i]), int(bq[i]), int(w[i])) for i in idx)
    return rows


def extract(raw_dir: Path = DEFAULT_RAW_DIR, top_k: int = TOP_K) -> dict:
    raw_dir = Path(raw_dir)
    annotations = read_feather(
        raw_dir / "annotations.feather",
        want={"bodyId", "superclass", "status", "type", "somaSide", "rootSide"},
    )
    retained = retained_mask(annotations)
    node_types = {t: neurons_of_type(annotations, retained, t) for t in ALL_CANDIDATE_TYPES}

    candidate_ids = set()
    for ids in node_types.values():
        candidate_ids |= set(ids.keys())

    neurotransmitters = read_feather(
        raw_dir / "neurotransmitters.feather", want={"body", "consensus_nt"}
    )
    nt_by_body = dict(zip(
        neurotransmitters["body"].astype(np.int64).tolist(),
        neurotransmitters["consensus_nt"].tolist(),
    ))
    consensus_nt = {bid: nt_by_body.get(bid) for bid in candidate_ids}

    candidate_edges = stream_candidate_edges(raw_dir, candidate_ids)
    return build_subgraph(node_types, consensus_nt, candidate_edges, top_k=top_k)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--top-k", type=int, default=TOP_K)
    args = parser.parse_args(argv)

    subgraph = extract(Path(args.raw_dir), top_k=args.top_k)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(subgraph, f, indent=2, sort_keys=True)
    print(json.dumps({
        "neurons": len(subgraph["neurons"]),
        "edges": len(subgraph["edges"]),
        "candidate_population_counts": subgraph["candidate_population_counts"],
        "excluded_motor_types": subgraph["excluded_motor_types"],
        "out": str(out_path),
    }, indent=2))


if __name__ == "__main__":
    main()
