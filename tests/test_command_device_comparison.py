"""Counterexamples for typed command evidence; fabricated fixtures, no accuracy claims."""
from copy import deepcopy

import pytest

from scripts.compare_java_task import (compare_devices, map_demonstrations, map_java_steps,
    map_python_steps)
from scripts.compare_java_generation import differences
from scripts.compare_semantic_trace import internal_execution_checks


def fixture():
    source={'id':'observed-keyboard','name':'Keyboard','frame':'A','kind':'input_device','device_type':'Keyboard','widget_type':None}
    action={'class':'model.KeyAction','text':'zf5j','press_type':'Type','is_command':True,'modifiers':0}
    t={'id':'jt','source':'Keyboard','source_details':source,'destination':'B','action':action,'delay_s':0,'delay_label':'Wait'}
    js={'class':'model.TransitionScriptStep','frame':'A','destination':'B','focus':'Keyboard','focus_details':source,'transition':t}
    project={'design':{'frames':[{'id':f,'name':f,'widgets':[], 'devices':[{'id':'k'+f,'name':'Keyboard','kind':'keyboard'}]} for f in ('A','B')],
        'transitions':[{'id':'t','from_frame':'A','to_frame':'B','source_type':'input_device','source_id':'kA','keys':list('zf5j'),
                        'key_text':'zf5j','is_command':True,'modifiers':0,'delay_s':0}]},
        'tasks':[{'demonstration':{'initial':{'frame':'A'},'steps':[{'op':'keys','keys':list('zf5j'),'key_text':'zf5j',
            'device':'keyboard','device_id':'kA','is_command':True,'modifiers':0,'transition':'t'}]}}]}
    demo={'steps':[js]}
    seg={'class':'model.TextActionSegment','frame':'A','destination':'B','focus':'Keyboard','text':'zf5j',
         'owner_demonstration_index':0,'inserted_by_user':True,'owner_transition':t,'text_segment_destination_applies':True}
    fresh=[{'step':seg}]
    py=[{'op':'key','key':c,'device':'keyboard','frame':'A','demo_index':0,'origin':'demonstrated','duration_s':None} for c in 'zf5j']
    py.append({'op':'transition','frame':'A','demo_index':0,'note':'t','duration_s':0,'state_before':{'frame':'A'},'state_after':{'frame':'B'}})
    return project,demo,fresh,{'steps':py}


def test_command_device_evidence_baseline_matches_without_guessing_name():
    p,d,j,r=fixture()
    a,b,u,_=map_demonstrations(p,d)
    assert not u and not differences(a,b)
    ja,_,jc,ju=map_java_steps(j,d,True)
    pa,_,pc,_,pu=map_python_steps(p,r)
    assert not ju and not pu and ja==pa and jc==pc
    assert jc[0]['source_type']=='input_device'
    assert jc[0]['action_position']==4


@pytest.mark.parametrize('mutation',['lost_command','modifier_confusion','missing_5','swapped_keys','extra_enter','device_as_widget'])
def test_input_counterexamples_fail_independent_of_total(mutation):
    p,d,_,_=fixture();s=p['tasks'][0]['demonstration']['steps'][0]
    if mutation=='lost_command':s['is_command']=False
    if mutation=='modifier_confusion':s['modifiers']=1
    if mutation=='missing_5':s['keys']=list('zfj')
    if mutation=='swapped_keys':s['keys']=list('zf j'.replace(' ',''))+['5']
    if mutation=='extra_enter':s['keys'].append('ENTER')
    if mutation=='device_as_widget':p['design']['transitions'][0].update(source_type='widget',target='kA')
    a,b,u,_=map_demonstrations(p,d)
    assert u or differences(a,b)


@pytest.mark.parametrize('mutation',['early_transition','duplicate_transition','missing_key','missing_owner','false_last_segment'])
def test_generated_sequence_and_commit_counterexamples(mutation):
    p,d,j,r=fixture()
    if mutation=='early_transition':r['steps'].insert(1,r['steps'].pop())
    if mutation=='duplicate_transition':r['steps'].append(deepcopy(r['steps'][-1]))
    if mutation=='missing_key':r['steps'].pop(2)
    if mutation=='missing_owner':j[0]['step']['owner_transition']=None
    if mutation=='false_last_segment':j[0]['step']['text_segment_destination_applies']=False
    ja,_,jc,ju=map_java_steps(j,d,True);pa,_,pc,_,pu=map_python_steps(p,r)
    assert ju or pu or ja!=pa or jc!=pc


def test_unused_device_transition_and_raw_down_text_are_not_discarded():
    p,d,_,_=fixture();frame=p['design']['frames'][0]
    down=deepcopy(d['steps'][0]['transition']);down['action'].update(text='\ue00d'*14,is_command=False)
    down['destination']='A'
    observed={f:{'input_devices_in_iteration_order':[{'id':'observed-keyboard','name':'Keyboard','frame':f,'kind':'input_device','device_type':'Keyboard',
        'transitions_in_iteration_order':[d['steps'][0]['transition'],down] if f=='A' else []}]} for f in ('A','B')}
    edge=deepcopy(p['design']['transitions'][0]);edge.update(id='unused',keys=['DOWN']*14,key_text='\ue00d'*14,is_command=False,to_frame='A')
    p['design']['transitions'].append(edge)
    rows,issues=compare_devices(p['design']['frames'],observed,p['design']['transitions'])
    assert not issues and not any(r['differences'] for r in rows)
    rows,issues=compare_devices(p['design']['frames'],observed,p['design']['transitions'][:1])
    assert any(r['differences'] for r in rows)


@pytest.mark.parametrize('mutation',['repeat_start','mid_reset','early_return','queue_before_tail'])
def test_return_and_reset_counterexamples_are_internal_evidence_failures(mutation):
    model={'design':{'frames':[]}}
    r={'events':[{'event_id':'stop','event_type':'task_boundary','end_s':1}],
       'motor_events':[{'event_id':'tail','event_type':'key_finish','end_s':1}], 'predicted_time_s':1}
    if mutation=='repeat_start':
        r['events'][:0]=[{'event_id':str(i),'event_type':'production_fired','rule':'set-start-frame-'+str(i),'end_s':i*.1} for i in (1,2)]
    elif mutation=='mid_reset':r['events'].insert(0,{'event_id':'reset','event_type':'model_reset','end_s':.5})
    elif mutation=='early_return':r['predicted_time_s']=.9
    else:r['motor_events'][0]['end_s']=1.1
    assert any(c['status']=='mismatch' for c in internal_execution_checks(model,r))


def test_deleted_true_text_click_is_visible_in_demonstration_mapping():
    p,d,_,_=fixture()
    w={'id':'w','name':'text','kind':'text','label':'text','x':0,'y':0,'width':10,'height':10}
    p['design']['frames'][0]['widgets']=[w]
    source={'id':'jw','name':'text','frame':'A','kind':'widget','widget_type':'Text','device_type':None}
    transition={'source':'text','source_details':source,'destination':'A','delay_s':0,'delay_label':'Wait',
                'action':{'class':'model.ButtonAction','press_type':'Click','button':'Left','modifiers':0}}
    d['steps'].insert(0,{'class':'model.TransitionScriptStep','frame':'A','destination':'A','focus':'text',
                        'focus_details':source,'transition':transition})
    p['design']['transitions'].insert(0,{'id':'click','from_frame':'A','to_frame':'A','target':'w','delay_s':0})
    p['tasks'][0]['demonstration']['steps'].insert(0,{'op':'click','target':'w','transition':'click'})
    a,b,u,_=map_demonstrations(p,d)
    assert not u and a==b
    p['tasks'][0]['demonstration']['steps'].pop(0)
    a,b,u,_=map_demonstrations(p,d)
    assert differences(a,b)


def internal_keyboard_fixture():
    p,_,_,_=fixture();p['tasks'][0]['demonstration']['steps'][0]['keys']=list('z5')
    steps=[{'index':i,'op':'key','key':k,'demo_index':0,'frame':'A'} for i,k in enumerate('z5')]
    events=[];motor=[]
    for i,k in enumerate('z5'):
        at=.1+.2*i
        events.append({'event_id':f'r{i}','event_type':'keyboard_request_registered','end_s':at,
            'details':{'step_index':i,'key':k,'pending_keystrokes':1}})
        motor.append({'event_id':f'm{i}','event_type':'key_output','step_index':i,'end_s':at+.1})
        events.append({'event_id':f'o{i}','event_type':'keyboard_output_registered','end_s':at+.1,
            'details':{'step_index':i,'key':k,'pending_keystrokes':0,'device_event_id':f'm{i}'}})
    events.extend([{'event_id':'commit','event_type':'keyboard_action_complete','end_s':.4,
        'details':{'step_index':1,'demo_index':0,'keys':list('z5'),'device_id':'kA',
                   'is_command':True,'modifiers':0,'device_event_id':'m1'}},
        {'event_id':'transition','event_type':'frame_transition','end_s':.4,
         'details':{'trigger_step_index':1,'device_event_id':'m1','from_frame':'A','to_frame':'B'}},
        {'event_id':'end','event_type':'task_boundary','end_s':.5}])
    # Keep binary arithmetic exact to the deliberately authored fixture clocks.
    events[3]['end_s']=motor[1]['end_s']=.4
    return p,{'steps':steps,'events':events,'motor_events':motor,'predicted_time_s':.5}


def test_keyboard_counter_metadata_is_separate_python_evidence():
    p,r=internal_keyboard_fixture()
    checks=internal_execution_checks(p,r)
    assert checks and all(c['status']=='pass' for c in checks)
    assert all('not printed' in c['scope'] for c in checks)


@pytest.mark.parametrize('mutation',['duplicate_commit','premature_commit','lost_output_registration','invented_pending','wrong_device','wrong_command'])
def test_keyboard_internal_commit_counterexamples(mutation):
    p,r=internal_keyboard_fixture();commit=r['events'][4]
    if mutation=='duplicate_commit':r['events'].insert(5,deepcopy(commit))
    elif mutation=='premature_commit':commit['end_s']=.2;commit['details'].update(step_index=0,device_event_id='m0')
    elif mutation=='lost_output_registration':r['events'].pop(3)
    elif mutation=='invented_pending':r['events'][3]['details']['pending_keystrokes']=1
    elif mutation=='wrong_device':commit['details']['device_id']='kB'
    else:commit['details']['is_command']=False
    assert any(c['status']=='mismatch' for c in internal_execution_checks(p,r))
