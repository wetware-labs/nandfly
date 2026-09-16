# GF Core Equivalence Report: Binarized NAND/LATCH vs. LIF Reference

Stimulus set: 98 looming-ramp patterns (see circuit/equivalence.py module docstring for generation).

## Headline result

- **Overall jump/no-jump agreement: 80.6% (79/98)**

## Agreement by drive level

| Drive level | Patterns | Agreement |
|---|---|---|
| none | 2 | 2/2 (100.0%) |
| weak | 16 | 2/16 (12.5%) |
| medium | 32 | 27/32 (84.4%) |
| strong | 48 | 48/48 (100.0%) |

## Disagreement analysis

19 of 98 patterns disagree. LIF-jumped-but-binarized-didn't: 19. Binarized-jumped-but-LIF-didn't: 0.

Sample disagreements (up to 10):

| level_L | level_R | LIF | binarized |
|---|---|---|---|
| 0 | 1 | True | False |
| 0 | 1 | True | False |
| 0 | 2 | True | False |
| 0 | 2 | True | False |
| 0 | 3 | True | False |
| 1 | 1 | True | False |
| 1 | 1 | True | False |
| 1 | 2 | True | False |
| 1 | 2 | True | False |
| 2 | 0 | True | False |

## Honest limitations

- The binarized netlist is purely combinational: it is evaluated once against the stimulus pattern's *fully-formed* active set, not against the LIF reference's tick-by-tick ramp. It has no notion of approach speed, only of the final visual population that ends up active.
- The LIF reference and the binarized comparator use *independently chosen* calibration constants (LIF's weight_scale=1/50 vs. the binarized comparator's ceil(0.5 * max_possible_sum) rule) -- they are not fit to agree with each other, so the agreement number above is a genuine measurement, not a tautology.
- This subgraph only models the GF/TTMn (jump) pathway; the DLMn flight-muscle pathway is excluded (see circuit/DERIVATION.md) because MaleCNS v1.0 has no direct DNp01->DLMn synapse in this data (it is known to be indirect, via the PSI interneuron, which is out of scope).
- Only the chemical synapse count is modeled. The GF->TTMn synapse is well documented in the literature to have a strong electrical (gap-junction) component that synapse-count data cannot see, so the TTMn stage's real coupling strength is likely understated here.
- Both models are toy-scale reductions (top-3-per-population visual input, 4-bit weight quantization); neither is a claim of accurately predicting a real fly's behavior, only of a documented, reproducible relationship between two models of the same wiring diagram.
