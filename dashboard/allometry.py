"""Above-ground biomass from one trunk-diameter measurement.

    AGB (kg) = 0.0673 * (rho * D^2 * H) ^ 0.976        Chave et al. 2014, pantropical model (eq. 4)
    H (m)    = 1.3 + 0.55 * D ^ 0.9                     height from diameter, used when H is not measured

with D the diameter at breast height in cm and rho the wood density in g/cm3 (0.6 by default, a mid-range tropical
hardwood). Carbon is taken as 47% of dry biomass (IPCC 2006, AFOLU vol. 4 table 4.3) and CO2-equivalent as carbon
times 44/12, the molar mass ratio of CO2 to C.

Reference: Chave, J. et al. (2014) "Improved allometric models to estimate the aboveground biomass of tropical
trees", Global Change Biology 20(10), 3177-3190, doi:10.1111/gcb.12629.

The pilot tree on Celo mainnet (token 1) stores DBH 10 cm and biomass 20 kg; this model gives 19.9 kg for 10 cm.
The contract stores whole numbers (uint96), so mint_biomass_kg rounds.
"""
from __future__ import annotations

from dataclasses import dataclass

CHAVE_A, CHAVE_B = 0.0673, 0.976
HEIGHT_A, HEIGHT_B, HEIGHT_C = 1.3, 0.55, 0.9
DEFAULT_WOOD_DENSITY = 0.6  # g/cm3
CARBON_FRACTION = 0.47
CO2_PER_C = 44 / 12
DBH_MIN_CM, DBH_MAX_CM = 2, 120  # the planter's slider range


def height_m(dbh_cm: float) -> float:
    if dbh_cm <= 0:
        raise ValueError(f"trunk diameter must be positive, got {dbh_cm} cm")
    return HEIGHT_A + HEIGHT_B * dbh_cm ** HEIGHT_C


def biomass_kg(dbh_cm: float, wood_density: float = DEFAULT_WOOD_DENSITY, height: float | None = None) -> float:
    if dbh_cm <= 0:
        raise ValueError(f"trunk diameter must be positive, got {dbh_cm} cm")
    if wood_density <= 0:
        raise ValueError(f"wood density must be positive, got {wood_density} g/cm3")
    h = height_m(dbh_cm) if height is None else height
    return CHAVE_A * (wood_density * dbh_cm ** 2 * h) ** CHAVE_B


def carbon_kg(biomass: float) -> float:
    return biomass * CARBON_FRACTION


def co2e_kg(biomass: float) -> float:
    return carbon_kg(biomass) * CO2_PER_C


@dataclass(frozen=True)
class Estimate:
    dbh_cm: int
    height_m: float
    biomass_kg: float
    carbon_kg: float
    co2e_kg: float

    @property
    def mint_biomass_kg(self) -> int:
        """What goes into mintTree's initialBiomass (whole kilograms)."""
        return round(self.biomass_kg)


def estimate(dbh_cm: int, wood_density: float = DEFAULT_WOOD_DENSITY) -> Estimate:
    b = biomass_kg(dbh_cm, wood_density)
    return Estimate(int(dbh_cm), height_m(dbh_cm), b, carbon_kg(b), co2e_kg(b))
