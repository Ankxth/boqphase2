# Methodology notes

Decisions that need to be pinned down explicitly and kept up to date here,
so they don't drift into hand-waving once deep in code.

## ICE → CEA adjustment

- Split each ICE v4.1 factor into process emissions (unaffected by geography)
  vs. energy-derived emissions (fuel + electricity).
- Rescale only the energy-derived portion using the ratio of India's grid
  emission factor (CEA CO2 Baseline Database) to the UK/EU grid factor ICE assumed.
- adjusted_factor = process_emissions + energy_emissions * (india_grid_factor / uk_grid_factor)
- Pin the CEA baseline edition used, for reproducibility.
- Spot-check against Indian EPDs where available.

## GRIHA-style baseline benchmark

- No ready-made published "kgCO2/sqm for typology X" table exists from GRIHA.
- Instead: define a default/typical spec per typology + GFA band, run it through
  the same calculation engine, and benchmark the user's actual project against
  that computed reference building.
- Label this in the UI as "compared to a typical building of this type and size" —
  not as an official GRIHA-published figure.
- Cross-check defaults against published Indian embodied-carbon studies
  (CSTEP, TERI, academic literature) as a secondary sanity check.
- Let the reference spec self-calibrate over time as more real projects run
  through the tool.
