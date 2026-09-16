# GF Core Equivalence Report: Binarized NAND/LATCH vs. LIF Reference

Visual inputs kept: 12 of 311 available LC4/LPLC2 neurons (3.9%) (see circuit/DERIVATION.md section 4).

Stimulus set: ALL 4096 possible activation patterns of those 12 kept visual inputs (64 left-hemisphere subsets x 64 right-hemisphere subsets, exhaustive -- not sampled; see circuit/equivalence.py module docstring).

## Headline result (exhaustive, all 4096 patterns)

- **Overall jump/no-jump agreement: 98.9% (4051/4096)**, using the coincidence-detector threshold rule that full.json actually ships (see circuit/binarize.py's `coincidence_threshold()`).

### Agreement by drive level (adjacent to the headline, same run)

| Drive level | Patterns | Agreement |
|---|---|---|
| none | 1 | 1/1 (100.0%) |
| weak | 483 | 438/483 (90.7%) |
| medium | 2765 | 2765/2765 (100.0%) |
| strong | 847 | 847/847 (100.0%) |

## We revised the threshold rule after the first run

The first version of this report used a single `ceil(0.5 * max_possible_sum)` rule for every threshold unit and a SAMPLED 98-pattern stimulus set, reporting 80.6% agreement. An independent re-run against the full exhaustive 4096-pattern space found the true number for that same rule is actually **76.7%** -- lower, not higher. Below is every threshold-fraction value we tried, on both the retired sampled set (historical) and the exhaustive set (current), followed by the coincidence-detector rule we actually shipped:

| Multi-input threshold | Sampled 98-pattern (historical) | Exhaustive 4096-pattern |
|---|---|---|
| ceil(0.5 * max_sum) | 80.6% | 76.7% |
| ceil(0.4 * max_sum) | 85.7% | 88.3% |
| ceil(0.3 * max_sum) | 95.9% | 98.1% |
| ceil(0.2 * max_sum) | 98.0% | 99.1% |
| ceil(0.15 * max_sum) | 100.0% | 99.8% |
| ceil(0.1 * max_sum) | 98.0% | 99.9% |
| **coincidence rule (largest input + 1)** -- shipped in full.json | n/a (didn't exist yet) | **98.9%** |

**We explicitly did NOT pick the best-scoring fraction (0.15, 100% on the old sampled set).** A rule chosen because it maximizes agreement against the one stimulus set we happen to have published is fit to that test set, not derived from anything, and a hostile re-run with a different (still legitimate) stimulus set could make it look arbitrary or worse. The coincidence-detector rule (largest single input's quantized magnitude + 1) was chosen instead ON PRINCIPLE, from the published biology: the Giant Fiber is a convergence/coincidence detector across looming-tuned channels, and no single LC4 or LPLC2 afferent should be able to command a jump by itself. That it also happens to score well on this particular stimulus set is a welcome, but secondary, observation.

## Disagreement analysis (coincidence rule, exhaustive set)

45 of 4096 patterns disagree. LIF-jumped-but-binarized-didn't: 45. Binarized-jumped-but-LIF-didn't: 0.

Sample disagreements (up to 10):

| level_L | level_R | LIF | binarized |
|---|---|---|---|
| 0 | 1 | True | False |
| 0 | 1 | True | False |
| 0 | 1 | True | False |
| 0 | 1 | True | False |
| 0 | 1 | True | False |
| 0 | 1 | True | False |
| 1 | 0 | True | False |
| 1 | 1 | True | False |
| 1 | 1 | True | False |
| 1 | 1 | True | False |

## Honest limitations

- The binarized netlist is purely combinational: it is evaluated once against the stimulus pattern's *fully-formed* active set, not against the LIF reference's tick-by-tick ramp. It has no notion of approach speed, only of the final visual population that ends up active.
- The LIF reference and the binarized comparator use *independently chosen* calibration constants (LIF's weight_scale=1/50 vs. the binarized comparator's coincidence-detector rule) -- they are not fit to agree with each other, so the agreement number above is a genuine measurement, not a tautology.
- This subgraph only models the GF/TTMn (jump) pathway; the DLMn flight-muscle pathway is excluded (see circuit/DERIVATION.md) because MaleCNS v1.0 has no direct DNp01->DLMn synapse in this data (it is known to be indirect, via the PSI interneuron, which is out of scope).
- Only the chemical synapse count is modeled. The GF->TTMn synapse is well documented in the literature to have a strong electrical (gap-junction) component that synapse-count data cannot see, so the TTMn stage's real coupling strength is likely understated here.
- The inherited transmitter->sign map assigns glutamate to inhibitory (-1). That is wrong specifically for motor neurons at the Drosophila neuromuscular junction, where glutamate is excitatory -- TTMn (glutamatergic in this data) is affected, but harmlessly, since TTMn has no outgoing edges in this subgraph and its sign is never read. Disclosed here rather than left for someone else to find; see circuit/DERIVATION.md section 3.
- Only 12 of 311 available LC4/LPLC2 neurons (3.9%) are modeled at all. Both models are toy-scale reductions; neither is a claim of accurately predicting a real fly's behavior, only of a documented, reproducible relationship between two models of the same wiring diagram.
