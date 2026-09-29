"""Synthetic evidence-adapter counterexamples, not CogTool accuracy fixtures.

The timestamps below exercise ownership and comparison only. They are not
computed by the predictor or presented as an upstream reference experiment.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.compare_semantic_trace import compare


def fixture():
    model={'design':{'frames':[{'id':f,'name':f,'widgets':[]} for f in ('A','B')]}}
    control=[]
    def event(kind,at,**fields):
        control.append({'event_id':'c'+str(len(control)),'event_type':kind,'start_s':at,'end_s':at,**fields})
    event('proc_display',0,state_after={'current_frame':'A'})
    event('production_fired',.55,rule='stop')
    event('model_stop',.55)
    event('frame_transition',.655,details={'from_frame':'A','to_frame':'B','trigger_step_index':2})
    event('proc_display',.655,state_after={'current_frame':'B'})
    event('system_wait_start',.655,details={'frame':'B','duration_s':.1})
    event('system_wait_end',.755,details={'frame':'B'})
    event('proc_display',.755,state_after={'current_frame':'B'},details={'reason':'system_wait_complete'})
    event('task_boundary',.805)
    motor=[]
    def movement(index,op,request,prepared,initiated,output,finished,key=None,coords=None):
        for kind,start,end in [('motor_preparation',request,prepared),('motor_initiation',prepared,initiated),
                               ('hand_move' if op=='home' else 'key_output',prepared,output),
                               ('hand_finish' if op=='home' else 'key_finish',prepared,finished)]:
            details={'backend_key':key,'coordinates':coords} if kind=='key_output' else {}
            motor.append({'event_id':'m'+str(len(motor)),'event_type':kind,'op':op,'step_index':index,
                'target':None,'start_s':start,'end_s':end,'state_after':{},'details':details})
    movement(0,'home',0,.004,.054,.2,.25)
    movement(1,'key',.3,.303,.353,.363,.453,'A',[1,4])
    movement(2,'key',.5,.505,.555,.655,.805,'B',[5,5])
    result={'predicted_time_s':.805,'events':control,'motor_events':motor,'vision_events':[],
        'steps':[{'index':0,'op':'home','device':'keyboard','frame':'A'},
                 {'index':1,'op':'key','key':'a','frame':'A'}, {'index':2,'op':'key','key':'b','frame':'A'}],
        'model_stop_time_s':.55,'last_device_output_time_s':.655,
        'last_manual_release_time_s':.805,'simulation_end_time_s':.805}
    raw='''0.000 COGTOOL TRANSITION-TO "A"
0.000 MOTOR HAND-TO-HOME
0.004 MOTOR PREPARATION-COMPLETE MOVE-ID 0
0.054 MOTOR INITIATION-COMPLETE MOVE-ID 0
0.200 MOTOR MOVE-A-HAND RIGHT 21.095022 3.0466409
0.250 MOTOR FINISH-MOVEMENT MOVE-ID 0
0.300 MOTOR PRESS-KEY A
0.303 MOTOR PREPARATION-COMPLETE MOVE-ID 0
0.353 MOTOR INITIATION-COMPLETE MOVE-ID 0
0.363 MOTOR OUTPUT-KEY #(1 4) MOVE-ID 0
0.453 MOTOR FINISH-MOVEMENT MOVE-ID 0
0.500 MOTOR PRESS-KEY B
0.505 MOTOR PREPARATION-COMPLETE MOVE-ID 0
0.550 PROCEDURAL PRODUCTION-FIRED STOP-9
0.555 MOTOR INITIATION-COMPLETE MOVE-ID 0
0.655 MOTOR OUTPUT-KEY #(5 5) MOVE-ID 0
0.655 COGTOOL TRANSITION-TO "B"
0.655 COGTOOL START-SYSTEM-WAIT 0.1 "synthetic"
0.755 COGTOOL SYSTEM-WAIT-DONE "synthetic" 0.1
0.755 COGTOOL END-SYSTEM-WAIT
0.805 MOTOR FINISH-MOVEMENT MOVE-ID 0
0.805 NONE Stopped because no events left to process
REFERENCE_RETURNED_TIME 0.805
'''
    return model,result,raw


def run(tmp_path,result=None,raw=None):
    model,base,trace=fixture()
    for name,value in [('input',model),('result',base if result is None else result),
                       ('plan',{'numeric_comparison':{'raw_total_abs_tolerance_s':'0.0000005'}})]:
        (tmp_path/(name+'.json')).write_text(json.dumps(value))
    (tmp_path/'trace.txt').write_text(trace if raw is None else raw)
    summary=compare(tmp_path/'input.json',tmp_path/'result.json',tmp_path/'trace.txt',
                    tmp_path/'plan.json',tmp_path/'out','ported_reference_backend')
    return summary


def test_complete_bounded_mechanisms_match_without_granting_full_equivalence(tmp_path):
    s=run(tmp_path)
    assert s['required_mechanisms_status']=='pass'
    assert s['observed_paired_events_status']=='pass'
    assert s['raw_total_comparison_status']=='pass'
    assert s['comparison_status']=='not_comparable'
    assert s['full_resource_state_equivalence'] is None
    assert s['proc_display_equivalence'] is None
    assert s['mechanism_counts']['motor.key.output']=={'reference':2,'python':2}
    assert s['mechanism_counts']['frame.transition']=={'reference':1,'python':1}
    assert (tmp_path/'out/reference_trace.txt').read_text()==fixture()[2]


@pytest.mark.parametrize('corruption', ['missing_key','swap_keys','early_frame','double_wait','missing_page',
    'early_stop','missing_home_release','missing_wait_end','missing_queue_end','wrong_key_coordinates',
    'wrong_frame','false_boundary_claim','missing_page_display','missing_wait_visibility'])
def test_total_match_cannot_hide_required_mechanism_corruption(tmp_path,corruption):
    _,r,_=fixture()
    if corruption=='missing_key':
        r['motor_events']=[e for e in r['motor_events'] if not(e['event_type']=='key_output' and e['step_index']==2)]
    elif corruption=='swap_keys':
        # Keep all timestamps/identities, change only preserved request order.
        r['motor_events']=r['motor_events'][:4]+r['motor_events'][8:]+r['motor_events'][4:8]
    elif corruption=='early_frame':
        next(e for e in r['events'] if e['event_type']=='frame_transition')['end_s']=.654
    elif corruption=='double_wait':
        extra=deepcopy(next(e for e in r['events'] if e['event_type']=='system_wait_start'))
        extra['event_id']='extra-wait';r['events'].insert(5,extra)
    elif corruption=='missing_page':
        r['events']=[e for e in r['events'] if e['event_type']!='frame_transition']
    elif corruption=='early_stop':
        for e in r['events']:
            if e['event_type'] in {'model_stop','production_fired'}:e['end_s']=.54
    elif corruption=='missing_home_release':
        r['motor_events']=[e for e in r['motor_events'] if e['event_type']!='hand_finish']
    elif corruption=='missing_wait_end':
        r['events']=[e for e in r['events'] if e['event_type']!='system_wait_end']
    elif corruption=='missing_queue_end':
        r['events']=[e for e in r['events'] if e['event_type']!='task_boundary']
    elif corruption=='wrong_key_coordinates':
        next(e for e in r['motor_events'] if e['event_type']=='key_output')['details']['coordinates']=[7,4]
    elif corruption=='wrong_frame':
        next(e for e in r['events'] if e['event_type']=='frame_transition')['details']['to_frame']='A'
    elif corruption=='false_boundary_claim':r['model_stop_time_s']=.54
    elif corruption=='missing_page_display':
        r['events']=[e for e in r['events'] if not(e['event_type']=='proc_display' and e['end_s']==.655)]
    elif corruption=='missing_wait_visibility':
        r['events']=[e for e in r['events'] if not(e['event_type']=='proc_display' and e['end_s']==.755)]
    s=run(tmp_path,r)
    assert s['raw_total_comparison_status']=='pass'
    assert s['required_mechanisms_status']=='mismatch'
    assert s['observed_paired_events_status']=='mismatch'
    assert s['comparison_status']=='mismatch'
    if corruption=='swap_keys':
        assert s['mapped_time_mismatches']==0
        assert s['ordered_action_comparison']['motor_requests']['status']=='mismatch'
    if corruption=='wrong_key_coordinates':assert s['mapped_attribute_mismatches']==1


def test_missing_reference_output_is_preserved_and_fails_even_with_same_total(tmp_path):
    raw=fixture()[2].replace('0.655 MOTOR OUTPUT-KEY #(5 5) MOVE-ID 0\n','')
    s=run(tmp_path,raw=raw)
    assert s['raw_total_comparison_status']=='pass'
    assert s['required_mechanisms_status']=='mismatch'
    rows=json.loads((tmp_path/'out/semantic_mapping.json').read_text())
    assert any(r['semantic_signature'][0]=='motor.key.output' and r['status']=='unmatched_python' for r in rows)
    assert (tmp_path/'out/reference_trace.txt').read_text()==raw


def test_missing_output_does_not_relax_timestamp_tolerance(tmp_path):
    _,r,_=fixture()
    next(e for e in r['motor_events'] if e['event_type']=='key_output')['end_s']+=.0006
    s=run(tmp_path,r)
    assert s['mapped_time_mismatches']==1
    assert s['first_timestamp_mismatch']['tolerance_s']==.0005
