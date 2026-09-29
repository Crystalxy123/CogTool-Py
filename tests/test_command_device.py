"""Source-derived bounded command/device rules; no official total is an oracle."""
from dataclasses import replace
import copy,math
import pytest
from cogtool_py.models import InputDevice,Frame,Transition,DemonstrationStep,Widget,Project,ModelError
from cogtool_py.engine import predict
from cogtool_py.generator import generate
from cogtool_py.io import input_hash,save_project,load_project
from test_task_extension import scene


def command_scene(text='ab3k',command=True,transition=True,two=False):
    p=scene(keyboard=text);t=p.tasks[0]
    frames=tuple(Frame(f,f,(),(InputDevice('kbd','Keyboard'),)) for f in ('A','B','C'))
    steps=[DemonstrationStep('keys',keys=tuple(text),device='keyboard',device_id='kbd',
                            is_command=command,key_text=text,transition='go' if transition else None)]
    transitions=[Transition('go','A',None,'B',0,'response','input_device','kbd',tuple(text),command,0,text)] if transition else []
    if two:
        steps.append(DemonstrationStep('keys',keys=('z','o'),device='keyboard',device_id='kbd',is_command=True,key_text='zo',transition='go2'))
        transitions.append(Transition('go2','B',None,'C',0,'response','input_device','kbd',('z','o'),True,0,'zo'))
    return replace(p,design=replace(p.design,frames=frames,transitions=tuple(transitions)),
                   tasks=(replace(t,demonstration=replace(t.demonstration,steps=tuple(steps))),))


def test_text_is_selection_target_without_textbox_focus_or_button_think():
    p=command_scene(transition=False);t=p.tasks[0]
    frame=Frame('A','A',(Widget('w','Text target','','text',100,80,115,12),),(InputDevice('kbd','Keyboard'),))
    t=replace(t,demonstration=replace(t.demonstration,steps=(DemonstrationStep('click','w'),)))
    p=replace(p,design=replace(p.design,frames=(frame,)),tasks=(t,))
    script=generate(p,t)
    assert [s.op for s in script.steps]==['home','point','click']
    assert script.final_state['focus'] is None
    r=predict(p).to_dict();assert r['completion_status']=='complete'
    assert len([e for e in r['motor_events'] if e['event_type']=='click_output'])==1
    assert r['final_state']['manual']['focus'] is None


def test_command_flag_adds_one_mental_not_a_modifier_and_existing_mental_deduplicates():
    ordinary=command_scene(command=False,transition=False);command=command_scene(command=True,transition=False)
    os=generate(ordinary,ordinary.tasks[0]);cs=generate(command,command.tasks[0])
    assert [s.key for s in cs.steps if s.op=='key']==list('ab3k')
    assert [s.op for s in os.steps]==['key']*4
    assert [s.op for s in cs.steps]==['think']+['key']*4
    t=command.tasks[0];t=replace(t,demonstration=replace(t.demonstration,steps=(DemonstrationStep('think',duration_s=.2),*t.demonstration.steps)))
    p=replace(command,tasks=(t,));ss=generate(p,t)
    assert len([s for s in ss.steps if s.op=='think'])==1
    assert input_hash(ordinary)!=input_hash(command)


@pytest.mark.parametrize('text,words',[('zf5j',['zf']),('ab3k',['ab']),('5ab3cd',['ab','cd']),('123',[])])
def test_source_word_boundaries_do_not_spell_digits_as_words(text,words):
    r=predict(command_scene(text,transition=False)).to_dict()
    spell=[e['name'].removeprefix('get-spelling-') for e in r['compiled_productions'] if e['name'].startswith('get-spelling-')]
    assert spell==words
    assert [e['details']['requested_key'] for e in r['motor_events'] if e['event_type']=='key_output']==list(text)


def test_digit_5_uses_source_rounded_left_index_peck_and_independent_formula():
    r=predict(command_scene('5',command=False,transition=False)).to_dict()
    prep=next(e for e in r['motor_events'] if e['event_type']=='motor_preparation')
    movement=prep['details']['movement']
    assert (movement['style'],movement['hand'],movement['finger'])==('peck_recoil','left','index')
    assert movement['distance_deg']==2.24 and movement['direction_rad']==-1.11
    duration=max(.05,.1,.075*math.log2(2.24+.5))
    expected=.05+.005+round((.05+2*duration+.05)/.001)/1000
    assert r['predicted_time_s']==pytest.approx(expected,abs=1e-12)
    output=next(e for e in r['motor_events'] if e['event_type']=='key_output')
    assert output['details']['coordinates']==[5,2]


def test_two_commands_share_start_stop_and_commit_on_pending_zero_after_last_output():
    r=predict(command_scene('zf5j',two=True)).to_dict()
    assert r['completion_status']=='complete'
    assert sum(e['rule']=='set-start-frame' and e['event_type']=='production_fired' for e in r['events'])==1
    assert sum(e['event_type']=='model_stop' for e in r['events'])==1
    changes=[e for e in r['events'] if e['event_type']=='frame_transition']
    outputs=[e for e in r['motor_events'] if e['event_type']=='key_output']
    assert [e['details']['to_frame'] for e in changes]==['B','C']
    assert [e['start_s'] for e in changes]==[outputs[3]['end_s'],outputs[5]['end_s']]
    assert all(e['state_after']['pending_keystrokes']==0 for e in changes)
    requests=[e for e in r['events'] if e['event_type']=='keyboard_request_registered']
    assert max(e['details']['pending_keystrokes'] for e in requests)>1
    assert len([e for e in r['events'] if e['event_type']=='keyboard_action_complete'])==2
    assert r['predicted_time_s']>=max(e['end_s'] for e in r['motor_events'])
    assert changes[1]['state_after']['manual']['hand_locations']==changes[0]['state_after']['manual']['hand_locations']


def test_unused_known_function_transition_preserves_text_and_does_not_execute():
    p=command_scene();unused=Transition('unused','A',None,'A',0,None,'input_device','kbd',('DOWN',)*14,False,0,'\ue00d'*14)
    p=replace(p,design=replace(p.design,transitions=(*p.design.transitions,unused)))
    q=Project.from_dict(p.to_dict());r=predict(q).to_dict()
    assert q.design.transitions[-1]==unused
    assert r['completion_status']=='complete'
    assert all(e['details']['requested_key']!='DOWN' for e in r['motor_events'] if e['event_type']=='key_output')
    t=q.tasks[0];step=replace(t.demonstration.steps[0],keys=('DOWN',)*14,is_command=False,key_text='\ue00d'*14,transition='unused')
    q=replace(q,tasks=(replace(t,demonstration=replace(t.demonstration,steps=(step,))),))
    # 0.6 admits source-mapped DOWN; retaining an unused edge remains inert.
    active=predict(q).to_dict()
    assert active['completion_status']=='complete'
    assert [e['details']['requested_key'] for e in active['motor_events'] if e['event_type']=='key_output']==['DOWN']*14
    # Another unimplemented function key must still be explicit partial.
    unsupported=replace(step,keys=('UP',),key_text=None,transition=None)
    q=replace(q,tasks=(replace(t,demonstration=replace(t.demonstration,steps=(unsupported,))),))
    assert predict(q).to_dict()['completion_status']=='partial'


@pytest.mark.parametrize('field,value',[('keys',()),('keys',('UNKNOWN',)),('device_id','missing'),('modifiers',1),('is_command','true'),('key_text','wrong')])
def test_invalid_actual_action_objects_are_rejected_with_task_context(field,value):
    p=command_scene();t=p.tasks[0];step=replace(t.demonstration.steps[0],**{field:value})
    p=replace(p,tasks=(replace(t,demonstration=replace(t.demonstration,steps=(step,))),))
    with pytest.raises(ModelError,match=r'task\[t\].steps\[0\]'):
        predict(p)


def test_missing_frame_or_wrong_transition_source_does_not_fall_back_to_widget():
    p=command_scene()
    for changed in [replace(p.design.transitions[0],to_frame='missing'),replace(p.design.transitions[0],target='kbd')]:
        with pytest.raises(ModelError):predict(replace(p,design=replace(p.design,transitions=(changed,))))


def test_command_input_roundtrip_and_a_b_a_preserve_effective_identity(tmp_path):
    p=command_scene(two=True);path=tmp_path/'model.json';save_project(p,path);q=load_project(path)
    assert p==q and input_hash(p)==input_hash(q)
    a=predict(q).to_dict();predict(command_scene('5',False,False));b=predict(q).to_dict()
    for d in [a,b]:d.pop('program_runtime_s')
    assert a==b
    with pytest.raises(TypeError):p.parameters.entries['think_s']=0


def test_nonperceptual_ids_and_case_name_do_not_change_behavior():
    p=command_scene('ab3k',two=True);d=copy.deepcopy(p.to_dict());d['id']='different-case';d['name']='renamed project'
    frame_map={f['id']:'f_'+f['id'] for f in d['design']['frames']}
    trans_map={t['id']:'t_'+t['id'] for t in d['design']['transitions']}
    for f in d['design']['frames']:
        f['id']=frame_map[f['id']]
        for device in f['devices']:device['id']='new_'+device['id']
    for t in d['design']['transitions']:
        t['id']=trans_map[t['id']];t['from_frame']=frame_map[t['from_frame']];t['to_frame']=frame_map[t['to_frame']];t['source_id']='new_'+t['source_id']
    task=d['tasks'][0];task['id']='renamed task';task['demonstration']['initial']['frame']=frame_map[task['demonstration']['initial']['frame']]
    for step in task['demonstration']['steps']:step['device_id']='new_'+step['device_id'];step['transition']=trans_map[step['transition']]
    q=Project.from_dict(d);a=predict(p).to_dict();b=predict(q).to_dict()
    assert input_hash(p)!=input_hash(q)
    assert a['predicted_time_s']==b['predicted_time_s']
    motor=lambda r:[(e['event_type'],e['start_s'],e['end_s'],e.get('details',{}).get('requested_key'))for e in r['motor_events']]
    assert motor(a)==motor(b)
