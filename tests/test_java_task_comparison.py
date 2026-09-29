"""Independent mutations must be visible in the bounded task comparator."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.compare_java_task import compare, compare_groups


def group_fixture():
    bounds = dict(x=10, y=-20, width=11, height=9)
    group = dict(id='j1', raw_name=None, bounds=bounds,
                 members_in_iteration_order=[dict(name='A'), dict(name='B')])
    aux = dict(id='g1', frame='f1', x=15, y=-16,
               source=json.dumps(dict(bounds=bounds, members=['1', '2'])))
    return [aux], {'f1': 'Page'}, {'w1': {'name': 'A'}, 'w2': {'name': 'B'}}, {
        'Page': {'groups_in_first_widget_encounter_order': [group]}}


def test_effective_group_coordinates_cannot_hide_behind_provenance():
    args = group_fixture()
    assert compare_groups(*args)[2]
    args[0][0]['x'] += 100
    rows, _, passed = compare_groups(*args)
    assert rows[0]['bounds_and_member_order_equal']
    assert not rows[0]['effective_center_equal']
    assert not passed


def test_missing_or_duplicated_group_is_not_complete_coverage():
    aux, frames, widgets, java = group_fixture()
    assert not compare_groups([], frames, widgets, java)[2]
    assert not compare_groups(aux + deepcopy(aux), frames, widgets, java)[2]


def test_stale_result_hash_is_rejected_before_step_comparison(tmp_path):
    for name in ('original_scene', 'original_demonstration', 'fresh_steps', 'generation_record'):
        (tmp_path / (name + '.json')).write_text('{}')
    result = tmp_path / 'result.json'
    result.write_text(json.dumps({'input_sha256': 'stale'}))
    example = Path(__file__).resolve().parents[1] / 'examples/single_click.json'
    with pytest.raises(ValueError, match='input_sha256'):
        compare(tmp_path, example, result, tmp_path / 'out')
