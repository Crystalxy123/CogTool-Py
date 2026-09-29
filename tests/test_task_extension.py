"""Source-derived integration invariants, independent of official total times."""
from dataclasses import replace
import pytest
from cogtool_py.engine import predict
from cogtool_py.io import load_project,save_project,input_hash
from cogtool_py.models import (Project,ParameterSet,CONTROL_ENGINE,Design,Frame,Widget,
    Transition,Task,Demonstration,InitialState,DemonstrationStep,ModelError)
from cogtool_py.control_models import ControlConfig


def scene(delay=0, *, same_geometry=False, keyboard=None):
    p=ParameterSet.parse({k:{'value':v,'unit':'s','source':'independent source-rule test'}
        for k,v in [('click_s',.2),('key_s',.1),('homing_s',.4)]}).with_vision_defaults()
    control=replace(ControlConfig.source_2014(provenance='source-rule integration test'),execution_scope='integrated_task')
    if keyboard is not None:
        p=p.with_keyboard_defaults(); frames=(Frame('A','A',()),);ts=()
        steps=(DemonstrationStep('keys',keys=tuple(keyboard),device='keyboard'),);hand='keyboard'
    else:
        frames=(Frame('A','A',(Widget('same','Next','Next','button',100,100,80,30),)),
                Frame('B','B',(Widget('same','Done','Done','button',100 if same_geometry else 260,
                                           100 if same_geometry else 160,80,30),)))
        ts=(Transition('go','A','same','B',delay,'test response'),)
        steps=(DemonstrationStep('click','same',transition='go'),DemonstrationStep('click','same'))
        hand='mouse'
    return Project(2,'test','Test',CONTROL_ENGINE,p,Design('d','D','px',frames,ts),
        (Task('t','Task',Demonstration(InitialState('A',(0,0),'right',hand,None),steps)),),control)


def test_frame_activates_on_click_output_and_keeps_mouse_eye_and_target_identity():
    r=predict(scene()).to_dict()
    assert r['completion_status']=='complete'
    clicks=[e for e in r['motor_events'] if e['event_type']=='click_output']
    change=next(e for e in r['events'] if e['event_type']=='frame_transition')
    assert change['start_s']==clicks[0]['end_s']
    request=next(e for e in r['events'] if e['event_type']=='manual_request' and e['rule']=='click-mouse')
    assert request['start_s'] < change['start_s']
    assert change['state_after']['manual']['mouse']==clicks[0]['state_after']['mouse']
    assert change['state_after']['vision']['eye_location'] != [0,0]
    moves=[e for e in r['motor_events'] if e['event_type']=='cursor_move']
    assert moves[1]['state_before']['mouse']==moves[0]['state_after']['mouse']
    assert r['final_state']['current_frame']=='B'
    assert len(r['vision_requests'])==2
    assert [v['location']['frame'] for v in r['vision_requests']]==['A','B']


def test_response_is_one_timed_event_and_can_overlap_think():
    short=predict(scene(.5)).to_dict();long=predict(scene(2)).to_dict()
    for result,duration in [(short,.5),(long,2)]:
        start=[e for e in result['events'] if e['event_type']=='system_wait_start']
        end=[e for e in result['events'] if e['event_type']=='system_wait_end']
        assert len(start)==len(end)==1
        assert end[0]['start_s']-start[0]['start_s']==pytest.approx(duration,abs=1e-12)
        click=next(e for e in result['motor_events'] if e['event_type']=='click_output')
        assert start[0]['start_s']==click['end_s']
        assert not start[0]['state_after']['frame_visible']
        assert not any(e['name']=='wait' for e in result['compiled_productions'])
        second_move=[e for e in result['events'] if e['event_type']=='production_fired' and e['rule']=='move-mouse'][1]
        assert second_move['start_s']>=end[0]['start_s']
        assert result['predicted_time_s']>=end[0]['start_s']
    zero=predict(scene()).to_dict()
    assert short['predicted_time_s']==zero['predicted_time_s']
    assert 0 < long['predicted_time_s']-zero['predicted_time_s'] < 2


def test_same_bounds_across_real_frames_suppress_redundant_point_without_collapsing_pages():
    r=predict(scene(same_geometry=True)).to_dict()
    assert r['completion_status']=='complete'
    assert sum(s['op']=='point' for s in r['steps'])==1
    assert [s['frame'] for s in r['steps'] if s['op']=='click']==['A','B']
    assert sum(e['event_type']=='frame_transition' for e in r['events'])==1


def test_one_key_full_controller_duration_is_derived_from_source_events():
    r=predict(scene(keyboard='a')).to_dict()
    # First key: one DAT=.05 + punch preparation 3*.001 + initiation .05
    # + 2*burst=.1 to release. STOP fires at request, not at completion.
    assert r['predicted_time_s']==pytest.approx(.05+3*.001+.05+2*.05,abs=1e-12)
    assert r['model_stop_time_s']==.05
    assert r['last_device_output_time_s']==pytest.approx(.05+.003+.05+.01,abs=1e-12)
    assert r['last_manual_release_time_s']==r['predicted_time_s']
    assert [s['op'] for s in r['steps']]==['key']


def test_key_profile_roundtrip_hash_is_immutable_and_devices_are_virtual(tmp_path):
    p=scene(keyboard='aj');before=input_hash(p);out=tmp_path/'p.json';save_project(p,out)
    restored=load_project(out)
    assert input_hash(restored)==before
    a=predict(restored).to_dict();predict(scene(2));b=predict(restored).to_dict()
    for x in (a,b):x.pop('program_runtime_s')
    assert a==b and input_hash(p)==before
    with pytest.raises(TypeError):p.parameters.entries['motor_peck_fitts_coefficient_s']=.1
    altered=replace(p,parameters=p.parameters.override('motor_peck_fitts_coefficient_s',
        .09,unit='s',source='synthetic sensitivity'))
    assert input_hash(altered)!=before


def test_response_timeout_is_partial_not_a_short_complete_task():
    p=scene(20);r=predict(p).to_dict()
    assert r['completion_status']=='time_limit'
    assert r['predicted_time_s'] is None


def test_commands_and_explicit_wait_remain_explicitly_unsupported():
    p=scene(keyboard='a');task=p.tasks[0]
    for s in [DemonstrationStep('keys',keys=('ENTER',),device='keyboard'),DemonstrationStep('wait',duration_s=.2)]:
        changed=replace(p,tasks=(replace(task,demonstration=replace(task.demonstration,steps=(s,))),))
        r=predict(changed).to_dict()
        assert r['completion_status']=='partial' and r['predicted_time_s'] is None
        assert r['blocker']['reason']


@pytest.mark.parametrize('rule_name',['press-key','get-spelling-aj'])
def test_keyboard_frame_name_query_inherits_source_visibility_gate(rule_name):
    from cogtool_py.generator import generate
    from cogtool_py.task_control import IntegratedController
    p=scene(keyboard='aj');t=p.tasks[0];c=IntegratedController(p,t,generate(p,t))
    rule=next(r for r in c.rules if r['name']==rule_name)
    c.state.update(current_frame='A',frame_visible=False,goal_state=rule['state_from'])
    assert not any(r['name']==rule_name for r in c.candidates())
    c.state['frame_visible']=True
    assert any(r['name']==rule_name for r in c.candidates())


def test_already_selected_find_uses_visicon_during_response_not_frame_flag():
    from cogtool_py.generator import generate
    from cogtool_py.task_control import IntegratedController
    p=scene();t=p.tasks[0];c=IntegratedController(p,t,generate(p,t))
    c.target='same';c.visible={'same'}
    c.state.update(current_frame='A',frame_visible=False,goal_state=99)
    # Independent source boundary: frame query is hidden while its previously
    # displayed visicon still exists. No fictitious display change is injected.
    c.find_request();c.clock.drain()
    assert c.state['visual_location']['value']=='Next in A'
    assert c.state['location_requested'] and not c.state['location_failure']


@pytest.mark.parametrize('collision',['frame','widget'])
def test_ambiguous_reachable_scene_returns_partial_instead_of_id_based_choice(collision):
    p=scene();a,b=p.design.frames
    if collision=='frame':b=replace(b,name=a.name)
    else:b=replace(b,widgets=b.widgets+(replace(b.widgets[0],id='other',x=400),))
    r=predict(replace(p,design=replace(p.design,frames=(a,b)))).to_dict()
    assert r['completion_status']=='partial' and r['predicted_time_s'] is None
    assert 'ambiguous duplicate' in r['blocker']['reason']


def test_emit_production_clears_pending_home_before_spelling_after_think():
    from cogtool_py.generator import generate
    from cogtool_py.task_control import IntegratedController
    p=scene(keyboard='aa');t=p.tasks[0]
    steps=(DemonstrationStep('home',device='keyboard'),DemonstrationStep('think',duration_s=.2),
           DemonstrationStep('keys',keys=('a','a'),device='keyboard'))
    t=replace(t,demonstration=replace(t.demonstration,initial=replace(t.demonstration.initial,hand='mouse'),steps=steps))
    p=replace(p,tasks=(t,))
    c=IntegratedController(p,t,generate(p,t))
    word=next(r for r in c.rules if r['name']=='get-spelling-aa')
    assert word['execution_free'] is True
