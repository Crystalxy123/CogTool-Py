"""Source template checks and fabricated evidence mutations, not accuracy data."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from cogtool_py.control_models import ControlConfig
from cogtool_py.io import save_project
from cogtool_py.models import (CONTROL_ENGINE, Demonstration, DemonstrationStep, Design, Frame,
    InitialState, InputDevice, ParameterSet, Project, Task, Widget)
from scripts.run_ported_reference import model_text
from scripts.compare_java_task import key_text, map_demonstrations, map_java_steps, map_python_steps
from scripts.compare_semantic_trace import compare, internal_execution_checks

pytestmark=pytest.mark.independent


def project(steps):
    params=ParameterSet.parse({k:{'value':.2,'unit':'s','source':'independent synthetic fixture'} for k in ('click_s','key_s','homing_s')}).with_vision_defaults().with_keyboard_defaults()
    control=replace(ControlConfig.source_2014(provenance='independent source template fixture'),execution_scope='integrated_task')
    frame=Frame('f','page',(Widget('w','text','text','text',1,2,10,10),),(InputDevice('keyboard','Keyboard'),))
    return Project(2,'p','fixture',CONTROL_ENGINE,params,Design('d','d','px',(frame,),()),
        (Task('t','fixture',Demonstration(InitialState('f',(0,0),'right','keyboard',None),tuple(steps))),),control)


def render(tmp_path,steps):
    p=project(steps);path=tmp_path/'input.json';save_project(p,path)
    text,meta=model_text(path)
    return p,text,meta


@pytest.mark.parametrize('count',[1,2,14])
def test_each_source_down_is_one_right_hand_slash_and_word_uses_private_char(tmp_path,count):
    p,text,meta=render(tmp_path,[DemonstrationStep('keys',keys=('DOWN',)*count,device='keyboard',device_id='keyboard',key_text='\ue00d'*count)])
    assert text.count('isa press-key key slash')==count
    assert text.count(':key "(DOWN)" :hand \'RIGHT')==count
    assert '(p get-spelling-DOWN' not in text
    names=re.findall(r'\(p get-spelling-(\|[?]+\|)-\d+',text)
    assert names==(['|'+'?'*count+'|'] if count>=2 else [])
    assert [s['key'] for s in meta['shared_generated_steps'] if s['op']=='key']==['DOWN']*count
    key_rules=re.findall(r'\(p press-key-\d+\n.*?(?=\n\(p |\n\)\n\(format)',text,re.S)
    assert 'execution free' not in key_rules[0]
    assert all('execution free' in s for s in key_rules[1:])


def test_explicit_look_uses_visual_module_not_duration_mouse_or_fixed_wait(tmp_path):
    _,text,meta=render(tmp_path,[DemonstrationStep('look_at',target='w')])
    assert len(re.findall(r'\(p look-at-\d+',text))==2
    assert len(re.findall(r'\(p find-\d+',text))==1
    assert text.count('isa move-attention screen-pos =visual-location')==2
    assert 'isa move-cursor' not in text and 'isa click-mouse' not in text
    looks=[s for s in meta['shared_generated_steps'] if s['op']=='look_at']
    assert len(looks)==1 and looks[0]['duration_s'] is None
    assert ':duration None' not in text


def test_repeated_same_location_is_a_klm_decision_raw_demonstrations_stay_two(tmp_path):
    p,text,meta=render(tmp_path,[DemonstrationStep('look_at',target='w'),DemonstrationStep('look_at',target='w')])
    assert len(p.tasks[0].demonstration.steps)==2
    assert len([s for s in meta['shared_generated_steps'] if s['op']=='look_at'])==1
    assert len([s for s in meta['shared_generated_steps'] if s['op']=='think'])==1
    assert len(re.findall(r'\(p look-at-\d+',text))==2


def look_mapping_fixture():
    p=project([DemonstrationStep('look_at',target='w')]).to_dict()
    js={'class':'original.LookAtScriptStep','frame':'page','destination':'page','focus':'text',
        'owner_demonstration_index':0,'inserted_by_user':True}
    ps={'op':'look_at','frame':'f','target':'w','demo_index':0,'origin':'demonstrated','duration_s':None}
    return p,js,ps


def test_explicit_look_preserves_raw_kind_origin_target_and_missing_duration():
    p,j,py=look_mapping_fixture()
    a,b,u,_=map_demonstrations(p,{'steps':[j]})
    assert not u and a==b
    ja,_,_,ju=map_java_steps([{'step':j}]);pa,_,_,_,pu=map_python_steps(p,{'steps':[py]})
    assert not ju and not pu and ja==pa and ja[0]['duration_s'] is None


@pytest.mark.parametrize('mutation',['constant_dwell','replace_with_think','missing_look','wrong_target'])
def test_look_cannot_be_replaced_hidden_or_given_fabricated_duration(mutation):
    p,j,py=look_mapping_fixture();ja,_,_,_=map_java_steps([{'step':j}])
    if mutation=='constant_dwell':py['duration_s']=.1
    elif mutation=='replace_with_think':py.update(op='think',target=None,duration_s=1.2)
    elif mutation=='wrong_target':py['target']='absent'
    rows=[] if mutation=='missing_look' else [py]
    pa,_,_,_,pu=map_python_steps(p,{'steps':rows})
    assert pu or ja!=pa


def test_raw_direction_units_never_turn_into_four_letters():
    assert key_text('\ue00d'*14)==['DOWN']*14
    with pytest.raises(ValueError):key_text('DOWN')


def evidence_fixture():
    model={'design':{'frames':[{'id':'f','name':'page','widgets':[{'id':'w','name':'text'}]}]}}
    controls=[{'event_id':'c0','event_type':'proc_display','start_s':0,'end_s':0,'state_after':{'current_frame':'f'}},
              {'event_id':'c1','event_type':'model_stop','start_s':.1,'end_s':.1},
              {'event_id':'c2','event_type':'production_fired','rule':'stop','start_s':.1,'end_s':.1},
              {'event_id':'c3','event_type':'task_boundary','start_s':.2,'end_s':.2}]
    vision=[{'event_id':'v0','event_type':'visual_attention_request','target':'w','start_s':.05,'end_s':.05,'status':'executed'},
            {'event_id':'v1','event_type':'eye_preparation_complete','target':'w','start_s':.08,'end_s':.08,'status':'executed'},
            {'event_id':'v2','event_type':'visual_encoding_complete','target':'w','start_s':.12,'end_s':.12,'status':'executed'},
            {'event_id':'v3','event_type':'eye_movement_complete','target':'w','start_s':.15,'end_s':.15,'status':'executed'}]
    result={'events':controls,'motor_events':[],'vision_events':vision,'steps':[], 'predicted_time_s':.2}
    raw='''0.000 COGTOOL TRANSITION-TO "page"
0.050 VISION MOVE-ATTENTION LOC NIL "text in page"
0.080 VISION PREPARATION-COMPLETE TRGT1
0.100 PROCEDURAL PRODUCTION-FIRED STOP-5
0.120 VISION ENCODING-COMPLETE "text in page"
0.150 VISION COMPLETE-EYE-MOVEMENT TRGT1
0.200 NONE Stopped because no events left to process
REFERENCE_RETURNED_TIME 0.2
'''
    return model,result,raw


@pytest.mark.parametrize('missing',[None,'visual_attention_request','eye_preparation_complete','visual_encoding_complete','eye_movement_complete'])
def test_real_vision_lifecycle_is_required_not_only_unmatched_note(tmp_path,missing):
    model,result,raw=evidence_fixture()
    if missing:result['vision_events']=[e for e in result['vision_events'] if e['event_type']!=missing]
    for name,data in [('input',model),('result',result),('plan',{'numeric_comparison':{'raw_total_abs_tolerance_s':'0.0000005'}})]:
        (tmp_path/(name+'.json')).write_text(json.dumps(data))
    (tmp_path/'raw.txt').write_text(raw)
    s=compare(tmp_path/'input.json',tmp_path/'result.json',tmp_path/'raw.txt',tmp_path/'plan.json',tmp_path/'out','ported_reference_backend')
    assert s['raw_total_comparison_status']=='pass'
    assert s['required_mechanisms_status']==('mismatch' if missing else 'pass')
    assert s['comparison_status']!='pass'


@pytest.mark.parametrize('elapsed,predicted,reason',[(600,600,'event_queue_exhausted_after_stop'),(599,None,'event_queue_exhausted_after_stop'),(599,599,'time_limit')])
def test_timeout_and_missing_prediction_cannot_masquerade_as_complete(elapsed,predicted,reason):
    model={'design':{'frames':[]}}
    result={'events':[],'motor_events':[],'steps':[],'completion_status':'complete','predicted_time_s':predicted,
            'elapsed_simulation_s':elapsed,'termination_reason':reason,
            'runtime_policy':{'run_policy':'reference_2014','simulation_limit_s':600}}
    assert any(c['status']=='mismatch' for c in internal_execution_checks(model,result))


@pytest.mark.parametrize('count',[1,2,14])
def test_direction_count_is_physical_not_word_label_count(count):
    p=project([DemonstrationStep('keys',keys=('DOWN',)*count,device='keyboard')]).to_dict()
    raw={'class':'original.TextActionSegment','frame':'page','destination':'page','focus':'Keyboard',
         'owner_demonstration_index':0,'inserted_by_user':True,'text':'\ue00d'*count}
    java,_,_,u=map_java_steps([{'step':raw}]);assert not u and len(java)==count
    rows=[{'op':'key','key':'DOWN','device':'keyboard','target':None,'frame':'f','demo_index':0,
           'origin':'demonstrated','duration_s':None} for _ in range(count)]
    python,_,_,_,u=map_python_steps(p,{'steps':rows});assert not u and java==python
    python,_,_,_,u=map_python_steps(p,{'steps':rows[:-1]});assert java!=python


@pytest.mark.parametrize('wrong_preparation',[False,True])
def test_repeated_direction_preparation_memory_has_observed_timing_counterexample(tmp_path,wrong_preparation):
    # Deliberately authored evidence fixture; these values are not a prediction
    # of an official task and are never passed to the implementation as targets.
    model={'design':{'frames':[{'id':'f','name':'page','widgets':[]}]}}
    motor=[]
    for i,(request,prep,init,out,finish) in enumerate([(.05,.054,.104,.114,.204),(.3,.301,.351,.361,.451)]):
        for kind,start,end in [('motor_preparation',request,prep),('motor_initiation',prep,init),('key_output',prep,out),('key_finish',prep,finish)]:
            motor.append({'event_id':f'm{len(motor)}','event_type':kind,'op':'key','step_index':i,'target':None,
                'start_s':start,'end_s':end,'state_after':{},'details':{'requested_key':'DOWN','backend_key':'SLASH','coordinates':[10,5]} if kind=='key_output' else {}})
    if wrong_preparation:motor[4]['end_s']=.303
    result={'events':[{'event_id':'c0','event_type':'proc_display','start_s':0,'end_s':0,'state_after':{'current_frame':'f'}},
                      {'event_id':'c1','event_type':'production_fired','rule':'stop','start_s':.4,'end_s':.4},
                      {'event_id':'c2','event_type':'model_stop','start_s':.4,'end_s':.4},
                      {'event_id':'c3','event_type':'task_boundary','start_s':.5,'end_s':.5}],
            'motor_events':motor,'vision_events':[], 'predicted_time_s':.5,
            'steps':[{'index':i,'op':'key','key':'DOWN','frame':'f'} for i in range(2)]}
    raw='''0.000 COGTOOL TRANSITION-TO "page"
0.050 MOTOR PRESS-KEY SLASH
0.054 MOTOR PREPARATION-COMPLETE MOVE-ID 1
0.104 MOTOR INITIATION-COMPLETE MOVE-ID 1
0.114 MOTOR OUTPUT-KEY #(10 5) MOVE-ID 1
0.204 MOTOR FINISH-MOVEMENT MOVE-ID 1
0.300 MOTOR PRESS-KEY SLASH
0.301 MOTOR PREPARATION-COMPLETE MOVE-ID 2
0.351 MOTOR INITIATION-COMPLETE MOVE-ID 2
0.361 MOTOR OUTPUT-KEY #(10 5) MOVE-ID 2
0.400 PROCEDURAL PRODUCTION-FIRED STOP-5
0.451 MOTOR FINISH-MOVEMENT MOVE-ID 2
0.500 NONE Stopped because no events left to process
REFERENCE_RETURNED_TIME 0.5
'''
    for name,data in [('input',model),('result',result),('plan',{'numeric_comparison':{'raw_total_abs_tolerance_s':'0.0000005'}})]:
        (tmp_path/(name+'.json')).write_text(json.dumps(data))
    (tmp_path/'raw.txt').write_text(raw)
    s=compare(tmp_path/'input.json',tmp_path/'result.json',tmp_path/'raw.txt',tmp_path/'plan.json',tmp_path/'out','ported_reference_backend')
    assert s['raw_total_comparison_status']=='pass'
    assert s['required_mechanisms_status']==('mismatch' if wrong_preparation else 'pass')
    assert s['mapped_time_mismatches']==(1 if wrong_preparation else 0)


def test_backend_alias_cannot_hide_lost_direction_identity():
    model={'design':{'frames':[]}}
    result={'events':[],'motor_events':[{'event_id':'out','event_type':'key_output','step_index':0,'end_s':.2,
            'details':{'requested_key':'D','backend_key':'slash'}}],
            'steps':[{'index':0,'op':'key','key':'DOWN'}]}
    checks=internal_execution_checks(model,result)
    assert any(c['check']=='direction_key_source_backend_identity' and c['status']=='mismatch' for c in checks)


def test_optional_raw_text_absence_uses_source_single_character_encoding():
    p=project([DemonstrationStep('keys',keys=('DOWN','DOWN'),device='keyboard',device_id='keyboard')]).to_dict()
    observed={'class':'original.ActionScriptStep','frame':'page','destination':'page','focus':'Keyboard',
        'focus_details':{'id':'jk','kind':'input_device','name':'Keyboard','frame':'page','device_type':'Keyboard'},
        'action':{'class':'original.KeyAction','text':'\ue00d\ue00d','is_command':False,'modifiers':0,'press_type':'Type'}}
    j,py,u,_=map_demonstrations(p,{'steps':[observed]})
    assert not u and j==py and py[0]['key_text']=='\ue00d\ue00d'
