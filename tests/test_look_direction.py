"""Independent fixed-source rules, not official totals or copied reference times."""
from dataclasses import replace
import json,math
import pytest
from cogtool_py.control_models import ControlConfig
from cogtool_py.models import Project,Frame,Widget,DemonstrationStep,ModelError,InputDevice
from cogtool_py.engine import predict
from cogtool_py.generator import generate
from cogtool_py.io import input_hash,load_project,save_project
from test_task_extension import scene


def visual_scene(*steps):
    p=scene(keyboard='a');t=p.tasks[0]
    f=Frame('A','A',(Widget('w','Target','','text',100,100,80,30),),(InputDevice('kbd','Keyboard'),))
    return replace(p,design=replace(p.design,frames=(f,)),tasks=(replace(t,demonstration=replace(t.demonstration,steps=steps)),))


def down_sequence(count):
    return visual_scene(DemonstrationStep('keys',keys=('DOWN',)*count,device='keyboard',key_text='\ue00d'*count))


def test_explicit_look_has_no_duration_and_no_mouse_and_real_visual_events():
    p=visual_scene(DemonstrationStep('look_at','w'));r=predict(p).to_dict()
    assert [(s['op'],s['origin']) for s in r['steps']]==[('look_at','demonstrated'),('think','automatic')]
    assert r['steps'][0]['duration_s'] is None
    assert r['motor_events']==[]
    assert len(r['vision_requests'])==1
    assert r['vision_requests'][0]['completed']
    required={'visual_attention_request','visual_encoding_complete','eye_preparation_complete','eye_movement_complete'}
    assert required <= {e['event_type'] for e in r['vision_events'] if e['status']=='executed'}
    think=next(e for e in r['events'] if e['event_type']=='production_selected' and e['rule']=='think')
    encoded=next(e for e in r['vision_events'] if e['event_type']=='visual_encoding_complete')
    assert think['start_s'] < encoded['end_s']  # source THINK has manual guard only
    assert r['predicted_time_s']>=max(e['end_s'] for e in r['vision_events'] if e['status']=='executed')


@pytest.mark.parametrize('target',['w','other'])
def test_same_bounds_second_explicit_look_is_preserved_in_demo_but_suppressed_in_script(target):
    p=visual_scene(DemonstrationStep('look_at','w'),DemonstrationStep('look_at',target))
    if target=='other':
        f=p.design.frames[0]
        p=replace(p,design=replace(p.design,frames=(replace(f,widgets=(*f.widgets,Widget('other','Other','','text',100,100,80,30))),)))
    generated=generate(p,p.tasks[0]);r=predict(p).to_dict()
    assert len(r['demonstration'])==2
    assert [s.op for s in generated.steps]==['look_at','think']
    assert any('sameLocation' in warning for warning in generated.warnings)
    if target=='w':
        assert r['completion_status']=='complete' and len(r['vision_requests'])==1
    else:
        # Generator sameBounds is defined even when runtime auto-stuffing
        # has two tied candidates. Never choose an arbitrary scene winner.
        assert r['completion_status']=='partial'
        assert any(e['event_type']=='unsupported_stuffing_tie' for e in r['events'])


def test_same_explicit_look_after_key_adds_mental_without_second_attention():
    p=visual_scene(DemonstrationStep('look_at','w'),DemonstrationStep('keys',keys=('a',),device='keyboard'),DemonstrationStep('look_at','w'))
    r=predict(p).to_dict()
    assert [s['op'] for s in r['steps']]==['look_at','think','key','think']
    assert len(r['vision_requests'])==1 and r['completion_status']=='complete'


def test_automatic_writer_look_does_not_replace_generator_explicit_history():
    p=visual_scene(DemonstrationStep('click','w'),DemonstrationStep('look_at','w'))
    r=predict(p).to_dict()
    assert sum(s['op']=='look_at' for s in r['steps'])==1
    assert len(r['vision_requests'])==2
    assert sum(e['event_type']=='click_output' for e in r['motor_events'])==1


def test_existing_mental_before_new_explicit_look_is_not_repeated():
    p=visual_scene(DemonstrationStep('think',duration_s=.25),DemonstrationStep('look_at','w'))
    assert [s.op for s in generate(p,p.tasks[0]).steps]==['think','look_at']


@pytest.mark.parametrize('count',[1,2,3])
def test_down_is_one_source_marked_physical_stroke_and_uses_retained_peck_memory(count):
    r=predict(down_sequence(count)).to_dict();assert r['completion_status']=='complete'
    outputs=[e for e in r['motor_events'] if e['event_type']=='key_output']
    assert len(outputs)==count
    assert all(e['details']['requested_key']=='DOWN' and e['details']['backend_key']=='slash' and e['details']['coordinates']==[10,5] for e in outputs)
    preps=[e for e in r['motor_events'] if e['event_type']=='motor_preparation']
    assert preps[0]['duration_s']==pytest.approx(5*.001)
    assert all(e['duration_s']==0 for e in preps[1:])
    assert all((e['details']['movement']['hand'],e['details']['movement']['finger'],e['details']['movement']['style'])==('right','pinkie','peck_recoil') for e in preps)
    assert sum(s['op']=='think' for s in r['steps'])==1
    spelling=[p for p in r['compiled_productions'] if p['name'].startswith('get-spelling')]
    assert len(spelling)==int(count>1)
    if spelling:assert spelling[0]['name']=='get-spelling-'+'?'*count
    # Source DAT + optional WORD DAT, 5 features only once, per-key
    # initiation + outward/recoil Fitts + burst. Never count*single-key task.
    fitts=max(.05,.1,.075*math.log2(1+.5))
    expected=1.2+(.05 if count>1 else 0)+count*.05+.005+count*(.05+2*fitts+.05)
    assert r['predicted_time_s']==pytest.approx(expected,abs=1e-12)


def test_one_action_boundary_for_down_sequence_and_one_start_stop():
    r=predict(down_sequence(4)).to_dict()
    assert len(r['demonstration'])==1 and len(r['demonstration'][0]['keys'])==4
    assert len([e for e in r['events'] if e['event_type']=='keyboard_action_complete'])==1
    assert len([e for e in r['events'] if e['event_type']=='model_stop'])==1
    assert r['final_state']['pending_keystrokes']==0


@pytest.mark.parametrize('step',[DemonstrationStep('look_at','missing'),DemonstrationStep('look_at','w',duration_s=.15),DemonstrationStep('keys',keys=(),device='keyboard'),DemonstrationStep('keys',keys=('\ue0ff',),device='keyboard'),DemonstrationStep('keys',keys=('DOWN',),device='keyboard',modifiers=1)])
def test_illegal_look_or_special_key_input_has_context(step):
    with pytest.raises(ModelError,match=r'task\[t\].steps\[0\]'):predict(visual_scene(step))


def test_wrong_initial_frame_is_rejected_before_visual_prediction():
    p=visual_scene(DemonstrationStep('look_at','w'));t=p.tasks[0]
    p=replace(p,tasks=(replace(t,demonstration=replace(t.demonstration,initial=replace(t.demonstration.initial,frame='absent'))),))
    with pytest.raises(ModelError,match=r'task\[t\].initial.frame'):predict(p)


@pytest.mark.parametrize('duration,complete',[ (599,True),(600,False),(601,False)])
def test_reference_runtime_bound_executes_equal_time_events_then_classifies_timeout(duration,complete):
    p=visual_scene(DemonstrationStep('think',duration_s=duration));p=replace(p,control=ControlConfig.reference_2014(provenance='source runtime boundary check'))
    r=predict(p).to_dict()
    assert r['completion_status']==('complete' if complete else 'time_limit')
    assert r['reported_task_time_s']==(duration if complete else None)
    assert r['elapsed_simulation_s']==min(duration,600)
    if duration==600:
        assert r['model_stop_time_s']==600  # equal-time STOP processed, no early cutoff
        assert r['termination_reason']=='time_limit'
    if duration>600:assert r['model_stop_time_s'] is None


def test_legacy_ten_second_policy_survives_and_is_separate_from_event_guard():
    p=visual_scene(DemonstrationStep('think',duration_s=11))
    assert p.control.max_time_s==10 and 'run_policy' not in p.to_dict()['control']
    old=predict(p).to_dict();assert old['completion_status']=='time_limit' and old['reported_task_time_s'] is None
    newer=replace(p,control=ControlConfig.reference_2014(provenance='fixed source policy'))
    assert input_hash(newer)!=input_hash(p)
    assert predict(newer).to_dict()['reported_task_time_s']==11
    event_guard=predict(replace(newer,control=replace(newer.control,max_events=1))).to_dict()
    assert event_guard['completion_status']=='event_limit' and event_guard['reported_task_time_s'] is None
    with pytest.raises(ModelError,match='reference_2014'):
        predict(replace(newer,control=replace(newer.control,max_time_s=11)))


def test_new_inputs_and_runtime_policy_roundtrip_a_b_a(tmp_path):
    p=visual_scene(DemonstrationStep('look_at','w'),DemonstrationStep('keys',keys=('DOWN','DOWN'),device='keyboard',key_text='\ue00d\ue00d'))
    p=replace(p,control=ControlConfig.reference_2014(provenance='roundtrip'))
    f=tmp_path/'input.json';save_project(p,f);q=load_project(f)
    assert input_hash(q)==input_hash(p) and q==p
    assert 'duration_s' not in q.to_dict()['tasks'][0]['demonstration']['steps'][0]
    a=predict(p).to_dict();predict(down_sequence(1));b=predict(q).to_dict()
    a.pop('program_runtime_s');b.pop('program_runtime_s');assert a==b


def test_spelling_and_previous_hand_reset_at_generated_segment_not_whole_action():
    # Source flushTextSegment inserts mental before the different command key;
    # following ordinary b stays in that segment. One KeyAction, two segments.
    p=visual_scene(DemonstrationStep('keys',keys=('a','DOWN','b'),device='keyboard',key_text='a\ue00db'))
    r=predict(p).to_dict()
    assert [s['op'] for s in r['steps']]==['key','think','key','key']
    rules=r['compiled_productions']
    assert [rule['name'] for rule in rules if rule['name'].startswith('get-spelling')]==['get-spelling-?b']
    assert [rule['execution_free'] for rule in rules if rule['name']=='press-key']==[False,False,False]
    assert [e['details']['requested_key'] for e in r['motor_events'] if e['event_type']=='key_output']==['a','DOWN','b']
