import types

import pytest

from tools import generate_demo as G
from tools.demo_scenes import scene4_protect


def test_plan_segment_lengths_at_30fps():
    assert [s.SECONDS for s in G.SCENES] == [20, 25, 25, 20]
    assert G.frame_plan(30) == [600, 750, 750, 600]
    assert sum(G.frame_plan(30)) == 2700 == 30 * G.TOTAL_SECONDS


@pytest.mark.parametrize("fps", [12, 24, 25, 30, 50, 60])
def test_total_is_exactly_90s_at_any_integer_fps(fps):
    counts = G.frame_plan(fps)
    assert sum(counts) == fps * 90
    assert sum(counts) / fps == 90.0


def test_scene_boundaries():
    assert G.scene_starts() == [0, 20, 45, 70]


@pytest.mark.parametrize("fps", [0, -30, 29.97, "30"])
def test_rejects_bad_fps(fps):
    with pytest.raises(ValueError):
        G.frame_plan(fps)


def test_rejects_scene_table_not_summing_to_90():
    bad = [types.SimpleNamespace(SECONDS=20)] * 4
    with pytest.raises(ValueError, match="sum to 80"):
        G.frame_plan(30, bad)


@pytest.mark.parametrize("scene", G.SCENES)
def test_captions_fit_inside_their_scene(scene):
    last_end = 0.0
    for start, end, text in scene.CAPTIONS:
        assert 0 <= start < end <= scene.SECONDS
        assert start >= last_end - 1e-9, "captions overlap"
        assert text.strip()
        last_end = end
    assert scene.NARRATION.strip()


def test_buffer_pool_split_is_labelled_roadmap():
    label = scene4_protect.ROADMAP_LABEL.lower()
    assert "roadmap" in label and "not yet implemented" in label
    assert any("roadmap, not yet implemented" in c.lower() for _, _, c in scene4_protect.CAPTIONS)
    assert "roadmap" in scene4_protect.NARRATION.lower()


def test_render_frame_is_1080p():
    img = G.render_frame(3, 7.0, G.load_facts())
    assert img.size == (1920, 1080)
