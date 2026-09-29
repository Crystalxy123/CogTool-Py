"""Small evidence-adapter checks; no predictor or reference totals are fitted."""
import json
from pathlib import Path
from scripts.compare_semantic_trace import compare


def check(tmp_path, extra_reference='', python_time=.05):
    model={'design':{'frames':[{'id':'f','name':'Frame','widgets':[{'id':'x','name':'Target'}]}]}}
    result={'predicted_time_s':.2,'events':[
        {'event_id':'c0','event_type':'visual_location_stuffed','start_s':0,'end_s':0,
         'state_after':{'visual_location':{'target':'x'}}},
        {'event_id':'c1','event_type':'production_fired','rule':'find','start_s':python_time,'end_s':python_time},
    ],'motor_events':[],'vision_events':[]}
    plan={'numeric_comparison':{'raw_total_abs_tolerance_s':'0.0000005'}}
    for name,data in [('input',model),('result',result),('plan',plan)]:
        (tmp_path/(name+'.json')).write_text(json.dumps(data))
    raw=('0.000 VISION SET-BUFFER-CHUNK VISUAL-LOCATION LOC0 REQUESTED NIL "Target in Frame"\n'
         '0.050 PROCEDURAL PRODUCTION-FIRED FIND-999\n'+extra_reference+'0.200 NONE Stopped because no events left to process\n0.2\n')
    (tmp_path/'trace.txt').write_text(raw)
    output=tmp_path/'comparison'
    summary=compare(tmp_path/'input.json',tmp_path/'result.json',tmp_path/'trace.txt',tmp_path/'plan.json',output,'archived_reference')
    return summary,json.loads((output/'semantic_mapping.json').read_text()),output,raw


def test_actual_location_event_name_and_numeric_rule_suffix_map_without_claiming_equivalence(tmp_path):
    summary,rows,out,raw=check(tmp_path,extra_reference='0.075 VISION SOMETHING-UNSUPPORTED\n')
    assert summary['mapped_time_matches']==2
    assert summary['comparison_status']=='not_comparable'
    assert summary['first_timestamp_mismatch'] is None
    assert (out/'reference_trace.txt').read_text()==raw
    assert json.loads((out/'unmatched_reference.json').read_text())[0]['message']=='SOMETHING-UNSUPPORTED'
    assert all(r['reference']['resource_state'] is None for r in rows if r['reference'])
    assert summary['raw_total_comparison_status']=='pass'
    assert summary['cross_module_equal_time_order_equivalence'] is None


def test_more_than_half_printed_quantum_is_a_mismatch_and_unmatched_rules_remain(tmp_path):
    summary,rows,out,raw=check(tmp_path,extra_reference='0.060 PROCEDURAL PRODUCTION-FIRED EXTRA-1\n',python_time=.051)
    first=summary['first_timestamp_mismatch']
    assert first['semantic_signature']==['production.fired',None,'find',0]
    assert first['delta_s']==.001 and first['tolerance_s']==.0005
    assert any(r['status']=='unmatched_reference' and r['semantic_signature'][2]=='extra' for r in rows)
    assert summary['no_time_shift'] and summary['no_adjacent_row_duration']
    # A conflicting actual wrapper return cannot disappear behind event matches.
    trace=tmp_path/'trace.txt'
    trace.write_text(raw+'REFERENCE_RETURNED_TIME 0.201\n')
    total_check=compare(tmp_path/'input.json',tmp_path/'result.json',trace,
                        tmp_path/'plan.json',tmp_path/'total_check','ported_reference_backend')
    assert total_check['raw_total_comparison_status']=='mismatch'
    assert total_check['raw_reference_return_text']=='0.201'
    assert total_check['raw_total_delta_s']==-.001
    assert total_check['comparison_status']=='mismatch'
