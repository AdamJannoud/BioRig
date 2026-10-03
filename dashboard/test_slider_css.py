"""The trunk-diameter slider's thumb is pinned to the value, so the fill cannot run ahead of it.

Adam caught the two out of step on the hosted app: the green track ended at 43 cm while the thumb
sat where ~79 cm would be. Streamlit derives both from the widget value, so pinning the thumb to
that value whenever the pointer is off the widget makes the captured state impossible.
"""
from dashboard.allometry import DBH_MAX_CM, DBH_MIN_CM
from dashboard.ui import slider_thumb_css


def test_pin_uses_the_widgets_own_percentage() -> None:
    assert "left: 34.7458% !important" in slider_thumb_css(43, DBH_MIN_CM, DBH_MAX_CM)  # (43-2)/118
    assert "left: 18.6441% !important" in slider_thumb_css(24, DBH_MIN_CM, DBH_MAX_CM)  # the default


def test_pin_spans_the_whole_range() -> None:
    assert "left: 0.0000% !important" in slider_thumb_css(DBH_MIN_CM, DBH_MIN_CM, DBH_MAX_CM)
    assert "left: 100.0000% !important" in slider_thumb_css(DBH_MAX_CM, DBH_MIN_CM, DBH_MAX_CM)


def test_pin_leaves_the_native_drag_alone() -> None:
    css = slider_thumb_css(43, DBH_MIN_CM, DBH_MAX_CM)
    assert ":not(:active)" in css and ":not(:hover)" in css
    assert "direction: ltr" in css  # an inherited RTL direction would place the thumb mirrored


def test_pin_targets_the_thumb_only() -> None:
    # The track's container is position: relative with touch-action: none, so a looser selector
    # would move the whole track instead of the thumb.
    css = slider_thumb_css(43, DBH_MIN_CM, DBH_MAX_CM)
    assert 'div[style*="position: absolute"][style*="touch-action: none"]' in css
    assert "position: relative" not in css


def test_pin_overrides_the_widgets_inline_position() -> None:
    # Streamlit writes the thumb's left as an inline style, so only !important can win.
    css = slider_thumb_css(43, DBH_MIN_CM, DBH_MAX_CM)
    assert "!important" in css
    assert 'id="br-slider-pin"' in css
