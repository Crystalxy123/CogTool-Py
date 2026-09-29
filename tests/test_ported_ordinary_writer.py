"""Independent syntax expectations from fixed Java writer templates.

No Python prediction or Java export is used to form an expected production.
These tests exercise template placement, guards and omitted annotations rather
than compare end times produced by two implementations.
"""
from dataclasses import replace
import re

import pytest

from cogtool_py.control_models import ControlConfig
from cogtool_py.io import save_project
from cogtool_py.models import (CONTROL_ENGINE, Demonstration, DemonstrationStep,
    Design, Frame, InitialState, InputDevice, ParameterSet, Project, Task, Transition, Widget)
from scripts.run_ported_reference import model_text

pytestmark = pytest.mark.independent


def project(steps, *, keyboard=False, hand="mouse", shifted=False, delay=0, label=None):
    params = ParameterSet.parse({name: {"value": .2, "unit": "s", "source": "independent synthetic fixture"}
                                for name in ("click_s", "key_s", "homing_s")}).with_vision_defaults()
    if keyboard:
        params = params.with_keyboard_defaults()
    frames = (Frame("f1", "first", (Widget("w1", "one", "one", "button", 1, 2, 10, 10),)),
              Frame("f2", "second", (Widget("w2", "two", "two", "button", 11 if shifted else 1, 2, 10, 10),)))
    transitions = (Transition("t1", "f1", "w1", "f2", delay, label),
                   Transition("t2", "f2", "w2", "f1", 0))
    config = replace(ControlConfig.source_2014(provenance="independent source template test"),
                     execution_scope="integrated_task")
    task = Task("t", "test", Demonstration(InitialState("f1", (0, 0), "right", hand, None), tuple(steps)))
    return Project(2, "p", "synthetic", CONTROL_ENGINE, params,
                   Design("d", "d", "px", frames, transitions), (task,), config)


def rendered(tmp_path, p):
    path = tmp_path / "input.json"
    save_project(p, path)
    return model_text(path)


def productions(text, kind):
    return re.findall(r'\(p ' + re.escape(kind) + r'-\d+\n.*?(?=\n\(p |\n\(spp |\n\)\n\(format)', text, re.S)


def test_crossframe_preserves_scene_and_skips_second_same_location_look_and_point(tmp_path):
    p = project([DemonstrationStep("click", target="w1", transition="t1"),
                 DemonstrationStep("click", target="w2", transition="t2")])
    text, meta = rendered(tmp_path, p)
    assert text.count("make-instance 'cogtool-frame") == 2
    assert text.count("make-instance 'cogtool-transition") == 2
    assert len(productions(text, "look-at")) == 2  # alternate rules for a single inserted LookAt
    assert len(productions(text, "move-mouse")) == 1
    assert len(productions(text, "think")) == 2
    clicks = productions(text, "click-mouse")
    assert ':current-frame "first" :destination-frame "second"' in clicks[0]
    assert ':current-frame "second" :destination-frame "first"' in clicks[1]
    assert all(':destination-frame' not in p for p in productions(text, "prepare-click"))
    assert meta['python_predictor_used'] is False
    assert meta['java_frontend_executed'] is False


def test_changed_geometry_causes_another_real_visual_and_cursor_request(tmp_path):
    p = project([DemonstrationStep("click", target="w1", transition="t1"),
                 DemonstrationStep("click", target="w2", transition="t2")], shifted=True)
    text, _ = rendered(tmp_path, p)
    assert len(productions(text, "look-at")) == 4
    assert len(productions(text, "move-mouse")) == 2


def test_positive_response_delay_exists_once_only_on_action_not_generated_wait(tmp_path):
    p = project([DemonstrationStep("click", target="w1", transition="t1")],
                delay=.7, label="declared synthetic response")
    text, meta = rendered(tmp_path, p)
    assert text.count(':delay-duration') == 1
    assert ':delay-duration 0.7 :delay-label "declared synthetic response"' in productions(text, "click-mouse")[0]
    assert not productions(text, "wait")
    assert [s['op'] for s in meta['omitted_annotations']] == ['wait', 'transition']


def test_positive_delay_without_original_or_declared_label_is_not_invented(tmp_path):
    p = project([DemonstrationStep("click", target="w1", transition="t1")], delay=.7)
    with pytest.raises(ValueError, match='explicit source or synthetic delay_label'):
        rendered(tmp_path, p)


@pytest.mark.parametrize('chars,expected_guard', [('aa', False), ('jj', True)])
def test_home_then_word_spelling_guard_depends_on_first_key_hand(tmp_path, chars, expected_guard):
    p = project([DemonstrationStep("home", device="keyboard"),
                 DemonstrationStep("keys", keys=tuple(chars), device="keyboard")], keyboard=True)
    text, _ = rendered(tmp_path, p)
    assert 'isa hand-to-home' in productions(text, "move-hand")[0]
    spelling = productions(text, 'get-spelling-' + chars)[0]
    assert ('execution free' in spelling) == expected_guard
    key_rules = productions(text, "press-key")
    assert 'execution free' not in key_rules[0]
    assert 'execution free' in key_rules[1]
    assert ':peck-fitts-coeff 0.075' in text
    assert ':key-s' not in text and ':homing-s' not in text


def test_different_hands_and_new_text_actions_do_not_get_same_hand_guard(tmp_path):
    p = project([DemonstrationStep("keys", keys=('a', 'j'), device="keyboard"),
                 DemonstrationStep("keys", keys=('j',), device="keyboard")], keyboard=True, hand='keyboard')
    text, _ = rendered(tmp_path, p)
    assert ':start-with-mouse nil' in text
    assert len(productions(text, "get-spelling-aj")) == 1
    keys = productions(text, "press-key")
    assert len(keys) == 3 and all('execution free' not in r for r in keys)


def test_modifier_or_punctuation_aliases_remain_outside_this_writer_scope(tmp_path):
    p = project([DemonstrationStep("keys", keys=('=',), device="keyboard")], keyboard=True, hand='keyboard')
    with pytest.raises(ValueError, match='lowercase ASCII'):
        rendered(tmp_path, p)


@pytest.mark.parametrize('chars,words', [('5', []), ('zf5j', ['zf']), ('ab3cd', ['ab','cd']), ('a5j', [])])
def test_digits_remain_physical_keys_and_split_word_productions(tmp_path,chars,words):
    p=project([DemonstrationStep('keys',keys=tuple(chars),device='keyboard')],keyboard=True,hand='keyboard')
    text,meta=rendered(tmp_path,p)
    assert re.findall(r'\(p get-spelling-([a-z]+)-\d+',text)==words
    assert re.findall(r'\+manual> isa press-key key ([A-Z0-9])',text)==[c.upper() for c in chars]
    assert len(productions(text,'press-key'))==len(chars)
    assert not productions(text,'think')
    assert meta['source_action_metadata'][0]['keys']==list(chars)


def test_true_text_click_and_device_command_preserve_templates_and_last_key_destination(tmp_path):
    p=project([],keyboard=True,hand='keyboard')
    frames=(Frame('f1','first',(Widget('w1','one','one','text',1,2,10,10),),(InputDevice('k1','Keyboard'),)),p.design.frames[1])
    transitions=(Transition('click','f1','w1','f1',0),
                 Transition('command','f1',None,'f2',0,source_type='input_device',source_id='k1',
                            keys=tuple('zf5j'),is_command=True,key_text='zf5j'))
    demo=replace(p.tasks[0].demonstration,steps=(DemonstrationStep('click',target='w1',transition='click'),
        DemonstrationStep('keys',keys=tuple('zf5j'),device='keyboard',device_id='k1',transition='command',is_command=True,key_text='zf5j')))
    p=replace(p,design=replace(p.design,frames=frames,transitions=transitions),tasks=(replace(p.tasks[0],demonstration=demo),))
    text,meta=rendered(tmp_path,p)
    assert ":wtype 'cogtool-text" in text
    assert "cogtool-keyboard" not in text
    assert text.count("make-instance 'cogtool-transition")==1  # only widget self-loop in scene
    assert len(productions(text,'think'))==1
    assert text.index('(p think-')>text.index('(p click-mouse-')
    keys=productions(text,'press-key')
    assert len(keys)==4 and ':destination-frame' not in ''.join(keys[:-1])
    assert ':destination-frame "second"' in keys[-1]
    assert 'key ENTER' not in text and ':modifiers' not in text
    assert meta['input_device_transition_contracts'][0]['keys']==tuple('zf5j')
