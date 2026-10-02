"""The allometric model behind the planter's trunk slider: the pilot tree's stored pair, the plan's worked numbers,
monotonicity across the slider, and the carbon arithmetic."""
import pytest

from dashboard import allometry as al


def test_pilot_tree_reproduced_within_one_percent():
    # Token 1 on Celo mainnet stores DBH 10 cm, biomass 20 kg (getTreeStats(1)).
    b = al.biomass_kg(10)
    assert abs(b - 20) / 20 < 0.01
    assert al.estimate(10).mint_biomass_kg == 20


def test_default_slider_position_matches_the_plan():
    e = al.estimate(24)
    assert round(e.biomass_kg) == 208 and round(e.carbon_kg) == 98 and round(e.co2e_kg) == 359


def test_height_relation():
    assert al.height_m(10) == pytest.approx(1.3 + 0.55 * 10 ** 0.9)
    assert al.height_m(10) == pytest.approx(5.669, abs=1e-3)


def test_monotonic_across_the_slider():
    values = [al.biomass_kg(d) for d in range(al.DBH_MIN_CM, al.DBH_MAX_CM + 1)]
    assert all(b > a for a, b in zip(values, values[1:]))
    assert values[0] > 0


def test_measured_height_and_density_are_honoured():
    assert al.biomass_kg(20, height=10) == pytest.approx(0.0673 * (0.6 * 400 * 10) ** 0.976)
    assert al.biomass_kg(20, wood_density=0.8) > al.biomass_kg(20)


def test_carbon_and_co2e():
    assert al.carbon_kg(100) == pytest.approx(47)
    assert al.co2e_kg(100) == pytest.approx(47 * 44 / 12)
    assert al.co2e_kg(12) == pytest.approx(0.47 * 44)


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_non_positive_diameter(bad):
    with pytest.raises(ValueError):
        al.biomass_kg(bad)
    with pytest.raises(ValueError):
        al.height_m(bad)


def test_rejects_non_positive_density():
    with pytest.raises(ValueError):
        al.biomass_kg(10, wood_density=0)
