"""Compare observed semantic events, retaining all unmapped evidence.

This is a diagnostic adapter over the existing lossless trace parser. It never
feeds reference times back to the predictor, shifts time, or treats adjacent log
rows as durations. New upstream runs and archived references remain distinct.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.analyze_npb1_trace import parse_trace


def read(path): return json.loads(Path(path).read_text())
def write(path,data): Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def base_rule(name): return re.sub(r'-\d+$','',name.lower())


def quoted_strings(message):
    return [json.loads(value) for value in re.findall(r'"(?:[^"\\]|\\.)*"',message)]


def unique_names(items):
    counts=defaultdict(list)
    for name,value in items:counts[name].append(value)
    return {name:values[0] for name,values in counts.items() if len(values)==1}


def motor_actions(events, frames, target_in):
    """Bounded source FIFO ownership, using commands and phases, never time fit.

    Preparation is unique; PREPARE PUNCH is preparation-only. Completed normal
    preparations enter the explicit source FIFO and FINISH releases its head.
    Missing/ambiguous phases remain diagnostics rather than guessed ownership.
    """
    actions=[];issues=[];preparing=None;executing=None;queue=[]
    current_frame=None;cursor=None;cursor_target=None
    frame_names=unique_names((f['name'],f) for f in frames)
    def issue(e,reason):issues.append({'event_id':e['event_id'],'reason':reason})
    for e in events:
        msg=re.sub(r'\s+MOVE-ID\s+\d+$','',e['message'])
        if e['module']=='COGTOOL' and msg.startswith('TRANSITION-TO '):
            labels=quoted_strings(msg)
            current_frame=frame_names.get(labels[0]) if labels else None
        if e['module']!='MOTOR':continue
        kind=('point' if msg.startswith('MOVE-CURSOR OBJECT ') else
              'prepare' if msg.startswith('PREPARE PUNCH ') else
              'click' if msg.startswith('CLICK-MOUSE') else
              'key' if msg.startswith('PRESS-KEY ') else
              'home' if msg in {'HAND-TO-HOME','HAND-TO-MOUSE'} else None)
        if kind:
            if preparing is not None:
                issue(e,'overlapping preparation; no new ownership inferred');continue
            if kind=='point':cursor_target=target_in(msg)
            target=cursor_target
            preparing_known_target=(kind=='prepare' and current_frame and
                                   any(w['id']==cursor_target for w in current_frame['widgets']))
            if kind in {'click','prepare'} and current_frame and cursor is not None and not preparing_known_target:
                # Same-position clicks after a page transition need no new
                # MOVE. Bind only a unique current-frame widget at the last
                # explicitly printed cursor centre; never a case/step name.
                at=[w['id'] for w in current_frame['widgets'] if all(k in w for k in ('x','y','width','height'))
                    and [w['x']+math.floor(w['width']/2),w['y']+math.floor(w['height']/2)]==cursor]
                target=at[0] if len(at)==1 else None
            if kind=='key':
                key=msg.split(maxsplit=1)[1].upper()
                target=f"{current_frame['id'] if current_frame else '?'}:key:{key}"
            elif kind=='home':target='keyboard' if msg=='HAND-TO-HOME' else 'mouse'
            action={'kind':kind,'target':target,'phase_events':{'request':e['event_id']},
                    'attributes':{},'request_order':len(actions),
                    'pairing_basis':'unique preparation and source FIFO execution; explicit frame and cursor geometry for pointer targets'}
            actions.append(action);preparing=action
        elif msg=='PREPARATION-COMPLETE':
            if preparing is None:issue(e,'preparation completion without unique request');continue
            preparing['phase_events']['preparation_complete']=e['event_id']
            if preparing['kind']!='prepare':queue.append(preparing)
            preparing=None
            if executing is None and queue:executing=queue.pop(0)
        elif msg in {'INITIATION-COMPLETE','FINISH-MOVEMENT'} or msg.startswith(('MOVE-CURSOR-ABSOLUTE ','OUTPUT-KEY ','MOVE-A-HAND ')):
            phase=('initiation_complete' if msg=='INITIATION-COMPLETE' else 'finish' if msg=='FINISH-MOVEMENT' else 'output')
            if executing is None:issue(e,'lifecycle event without executing FIFO head');continue
            if phase in executing['phase_events']:issue(e,'duplicate '+phase);continue
            if phase=='output':
                expected={'point':'MOVE-CURSOR-ABSOLUTE ','click':'OUTPUT-KEY ','key':'OUTPUT-KEY ','home':'MOVE-A-HAND '}[executing['kind']]
                if not msg.startswith(expected):issue(e,'output command differs from FIFO head');continue
                if msg.startswith(('OUTPUT-KEY ','MOVE-CURSOR-ABSOLUTE ')):
                    match=re.search(r'#\(([^)]+)\)',msg)
                    if match:
                        coords=[float(v) for v in match[1].split()]
                        executing['attributes']['output']={'coordinates':coords}
                        if executing['kind']=='point':cursor=coords
            executing['phase_events'][phase]=e['event_id']
            if phase=='finish':executing=queue.pop(0) if queue else None
    return {'actions':actions,'issues':issues}


def internal_execution_checks(model,result):
    """Validate printed Python evidence; do not impute unprinted Lisp state."""
    checks=[]
    def check(name,ok,details):
        checks.append({'check':name,'status':'pass' if ok else 'mismatch','details':details,
                       'scope':'Python internal evidence; reference pending counters/reset state are not printed'})
    events=result.get('events',[]);steps={s.get('index',i):s for i,s in enumerate(result.get('steps',[]))}
    for kind in ('startup_empty_proc_display','model_stop','task_boundary'):
        found=[e for e in events if e['event_type']==kind]
        check('single_'+kind,len(found)<=1,{'event_ids':[e['event_id'] for e in found]})
        if kind=='startup_empty_proc_display' and found:
            check('startup_clear_at_zero',found[0]['end_s']==0,{'event_id':found[0]['event_id'],'time_s':found[0]['end_s']})
    starts=[e for e in events if e['event_type']=='production_fired' and base_rule(e.get('rule',''))=='set-start-frame']
    check('single_start_rule',len(starts)<=1,{'event_ids':[e['event_id'] for e in starts]})
    resets=[e for e in events if e['event_type'] in ('reset','model_reset','clock_reset')]
    check('no_mid_task_reset',not resets,{'event_ids':[e['event_id'] for e in resets]})
    bounds=[e for e in events if e['event_type']=='task_boundary']
    if result.get('completion_status')=='complete':
        check('complete_requires_prediction',result.get('predicted_time_s') is not None,
              {'predicted_time_s':result.get('predicted_time_s')})
        check('complete_is_not_timeout',result.get('termination_reason')=='event_queue_exhausted_after_stop',
              {'termination_reason':result.get('termination_reason')})
        policy=result.get('runtime_policy',{})
        if policy.get('run_policy')=='reference_2014':
            elapsed=result.get('elapsed_simulation_s',result.get('simulation_end_time_s'))
            limit=policy.get('simulation_limit_s')
            check('source_timeout_boundary_not_complete',isinstance(elapsed,(int,float)) and isinstance(limit,(int,float)) and elapsed<limit,
                  {'elapsed_simulation_s':elapsed,'simulation_limit_s':limit})
    if bounds:
        tail=max((e['end_s'] for layer in ('events','motor_events','vision_events') for e in result.get(layer,[])
                  if e.get('status','executed')=='executed'),default=0)
        check('queue_end_includes_all_executed_events',bounds[0]['end_s']>=tail,
              {'queue_end_s':bounds[0]['end_s'],'latest_executed_s':tail})
        for field in ('predicted_time_s','reported_task_time_s'):
            if result.get(field) is not None:
                check(field+'_equals_queue_end',result[field]==bounds[0]['end_s'],
                      {'reported':result[field],'queue_end_s':bounds[0]['end_s']})
    keyboard=[e for e in events if e['event_type'].startswith('keyboard_')]
    explicit=any(f.get('devices') for f in model['design']['frames'])
    for sid,step in steps.items():
        if step.get('op')!='key' or step.get('key')!='DOWN':continue
        outputs=[e for e in result.get('motor_events',[]) if e['event_type']=='key_output' and e.get('step_index')==sid]
        if result.get('completion_status')=='complete':
            check('direction_key_has_one_physical_output',len(outputs)==1,{'step_index':sid,'output_event_ids':[e['event_id'] for e in outputs]})
        for e in outputs:
            d=e.get('details',{})
            check('direction_key_source_backend_identity',d.get('requested_key')=='DOWN' and str(d.get('backend_key')).upper()=='SLASH',
                  {'step_index':sid,'event_id':e['event_id'],'requested_key':d.get('requested_key'),'backend_key':d.get('backend_key'),
                   'basis':'fixed Java encodeKey DOWN_ARROW_CHAR -> slash; physical output time/coordinates compared separately'})
    if not keyboard and not explicit:return checks
    key_steps=[s for s in steps.values() if s['op']=='key']
    physical={e['event_id']:e for e in result.get('motor_events',[]) if e['event_type']=='key_output'}
    requested=[];output=[];completed=[];pending=0;zero_outputs={}
    for e in keyboard:
        d=e.get('details',{});kind=e['event_type'];sid=d.get('step_index');step=steps.get(sid,{})
        if kind=='keyboard_request_registered':
            pending+=1;requested.append(sid)
            check('key_request_identity',step.get('op')=='key' and step.get('key')==d.get('key'),{'event_id':e['event_id']})
            check('pending_increment',d.get('pending_keystrokes')==pending,{'event_id':e['event_id'],'expected':pending,'observed':d.get('pending_keystrokes')})
        elif kind=='keyboard_output_registered':
            pending-=1;output.append(sid);device=physical.get(d.get('device_event_id'))
            check('key_output_identity',device is not None and device['step_index']==sid and device['end_s']==e['end_s'] and step.get('key')==d.get('key'),{'event_id':e['event_id'],'device_event_id':d.get('device_event_id')})
            check('pending_decrement',pending>=0 and d.get('pending_keystrokes')==pending,{'event_id':e['event_id'],'expected':pending,'observed':d.get('pending_keystrokes')})
            if pending==0:zero_outputs[d.get('device_event_id')]=e
        elif kind=='keyboard_action_complete':
            di=d.get('demo_index');completed.append(di)
            demos=model.get('tasks',[{}])[0].get('demonstration',{}).get('steps',[])
            demo=demos[di] if isinstance(di,int) and 0<=di<len(demos) else {}
            sequence=[s for s in key_steps if s.get('demo_index')==di]
            device=physical.get(d.get('device_event_id'))
            check('last_key_unique_action_commit',bool(sequence) and sid==sequence[-1].get('index') and
                  device is not None and device['step_index']==sid and device['end_s']==e['end_s'] and
                  d.get('keys')==demo.get('keys') and d.get('is_command')==demo.get('is_command',False) and
                  d.get('modifiers')==demo.get('modifiers',0) and d.get('device_id')==demo.get('device_id'),
                  {'event_id':e['event_id'],'demo_index':di})
    expected=[s.get('index') for s in key_steps]
    check('all_key_requests_once_in_script_order',requested==expected,{'expected':expected,'observed':requested})
    check('all_key_outputs_once_in_script_order',output==expected,{'expected':expected,'observed':output})
    demo_order=list(dict.fromkeys(s.get('demo_index') for s in key_steps))
    check('all_keyboard_actions_commit_once_in_order',completed==demo_order,{'expected':demo_order,'observed':completed})
    check('pending_drained',pending==0,{'pending':pending})
    for e in events:
        if e['event_type']!='frame_transition':continue
        d=e['details'];step=steps.get(d.get('trigger_step_index'),{})
        if step.get('op')!='key':continue
        output_event=zero_outputs.get(d.get('device_event_id'))
        check('key_frame_transition_at_drained_output',output_event is not None and output_event['end_s']==e['end_s'],
              {'event_id':e['event_id'],'device_event_id':d.get('device_event_id')})
    return checks


def compare(input_path, python_result, reference_trace, plan_path, out, reference_kind):
    out=Path(out)
    if out.exists(): raise FileExistsError('comparison output exists; preserve evidence in a new directory')
    model,result,plan=map(read,(input_path,python_result,plan_path))
    raw=Path(reference_trace).read_text();parsed=parse_trace(raw)
    # Reuse the archived parser grammar without inheriting its provenance label
    # for a newly executed backend. The original raw text remains unchanged.
    for parameter in parsed['parameters']:
        parameter['source']['parser_default_kind']=parameter['source']['kind']
        parameter['source']['kind']=reference_kind+'_parameter_printout'
        parameter['source']['reference_trace_sha256']=digest(reference_trace)
    frames=model['design']['frames']
    widgets={w['id']:w for f in frames for w in f['widgets']}
    names=unique_names(((w['name']+' in '+f['name']).upper(),w['id']) for f in frames for w in f['widgets'])
    def target_in(message):
        labels={label.upper() for label in quoted_strings(message)}
        matches=[ident for name,ident in names.items() if name.upper() in labels]
        return matches[0] if len(matches)==1 else None
    reference=[];python=[];used_ref=set();used_py=set();counts=defaultdict(int)
    def add_ref(event,kind,target=None,rule=None,basis='explicit trace message',attributes=None):
        signature=(kind,target,rule);index=counts[signature];counts[signature]+=1
        reference.append({'signature':list(signature)+[index],'event_id':event['event_id'],
            'time_s':event['timestamp_s'],'time_text':event['timestamp_text'],'line_number':event['line_number'],
            'raw_message':event['message'],'mapping_basis':basis,'resource_state':None,'attributes':attributes})
        used_ref.add(event['event_id'])
    by_id={e['event_id']:e for e in parsed['events']}
    # Motor lifecycle pairing uses explicit commands/completions from the
    # preserved parser, never a timing-nearest match or adjacent-row interval.
    # Later ACT-R motor messages append a movement identity. Preserve the raw
    # trace and strip this explicit suffix only in the lifecycle grammar view.
    motor=motor_actions(parsed['events'],frames,target_in)
    ref_actions=[];py_actions=[]
    for action in motor['actions']:
        target=action['target']
        ref_actions.append({'kind':action['kind'],'target':target,'event_id':action['phase_events']['request']})
        for phase,event_id in action['phase_events'].items():
            add_ref(by_id[event_id],f"motor.{action['kind']}.{phase}",target,
                    basis=action['pairing_basis'],
                    attributes=action['attributes'].get(phase) if action['kind'] in {'key','point'} else None)
    vision_target=None;eye_tokens={};vision_chunks={}
    current_frame=None;frame_names=unique_names((f['name'],f['id']) for f in frames)
    ref_boundaries={};ref_waits=[];ref_frames=[]
    for event in parsed['events']:
        msg=event['message'];module=event['module'];upper=msg.upper()
        production=re.fullmatch(r'PRODUCTION-(SELECTED|FIRED)\s+(\S+)',msg,re.I)
        if module=='PROCEDURAL' and production:
            add_ref(event,'production.'+production[1].lower(),rule=base_rule(production[2]),
                basis='same production template name excluding generated numeric suffix; ordered occurrence, not line position')
            if production[1].upper()=='FIRED' and base_rule(production[2])=='stop':
                add_ref(event,'boundary.model_stop');ref_boundaries['model_stop']=event
        elif module=='COGTOOL' and upper.startswith('TRANSITION-TO '):
            labels=quoted_strings(msg);destination=frame_names.get(labels[0]) if labels else None
            if current_frame is None:add_ref(event,'frame.initial',destination)
            else:add_ref(event,'frame.transition',f'{current_frame}->{destination}')
            ref_frames.append({'from':current_frame,'to':destination,'event_id':event['event_id']})
            current_frame=destination
        elif module=='COGTOOL' and upper.startswith('START-SYSTEM-WAIT '):
            value=re.match(r'START-SYSTEM-WAIT\s+([0-9.eE+-]+)',msg,re.I)
            add_ref(event,'wait.start',current_frame,attributes={'duration_s':float(value[1])} if value else None)
            ref_waits.append({'event_id':event['event_id'],'frame':current_frame,'phase':'start'})
        elif module=='COGTOOL' and upper.startswith('SYSTEM-WAIT-DONE '):
            add_ref(event,'wait.end',current_frame)
            ref_waits.append({'event_id':event['event_id'],'frame':current_frame,'phase':'end'})
        elif module=='COGTOOL' and upper=='END-SYSTEM-WAIT':
            add_ref(event,'wait.visible',current_frame)
        elif module=='VISION':
            if upper.startswith('MOVE-ATTENTION '):
                vision_target=target_in(msg)
                if vision_target is not None:
                    add_ref(event,'vision.request',vision_target)
                    chunk=re.match(r'MOVE-ATTENTION (.+?) NIL(?: |$)',msg,re.I)
                    if chunk:vision_chunks[chunk[1].upper()]=vision_target
            elif upper.startswith('PREPARATION-COMPLETE '):
                token=msg.split()[-1]
                if token not in eye_tokens and vision_target is not None:eye_tokens[token]=vision_target
                if token in eye_tokens:add_ref(event,'vision.eye_prepare',eye_tokens[token],basis='TRGT token within explicitly requested static target sequence')
            elif upper.startswith('COMPLETE-EYE-MOVEMENT '):
                token=msg.split()[1]
                if token in eye_tokens:add_ref(event,'vision.eye_complete',eye_tokens[token],basis='same explicit TRGT token')
            elif upper.startswith('ENCODING-COMPLETE '):
                target=target_in(msg) or vision_chunks.get(msg[len('ENCODING-COMPLETE '):].upper())
                if target is not None:add_ref(event,'vision.encoding',target)
            elif upper=='CHANGE-STATE LAST NONE PREP FREE':add_ref(event,'vision.clear_complete',basis='explicit visual preparation release; request time is not inferred')
            elif upper.startswith('SET-BUFFER-CHUNK VISUAL-LOCATION '):
                target=target_in(msg)
                if target is not None:add_ref(event,'location.write',target)
            elif upper.startswith('CLEAR ' ) or upper=='CLEAR':add_ref(event,'vision.clear_request')
        if msg=='Stopped because no events left to process':add_ref(event,'task.queue_end')
        if module=='MOTOR' and upper.startswith(('OUTPUT-KEY ','MOVE-CURSOR-ABSOLUTE ','MOVE-A-HAND ')):
            ref_boundaries['last_device_output']=event
        if module=='MOTOR' and upper.startswith('FINISH-MOVEMENT'):
            ref_boundaries['last_manual_release']=event
    for kind,event in ref_boundaries.items():
        if kind!='model_stop':add_ref(event,'boundary.'+kind)
    counts=defaultdict(int)
    def add_py(e,kind,target=None,rule=None,when='end_s',layer='control',attributes=None):
        signature=(kind,target,rule);index=counts[signature];counts[signature]+=1
        python.append({'signature':list(signature)+[index],'event_id':e['event_id'],'layer':layer,
                       'time_s':e[when],'resource_state':e.get('state_after'),'source':e.get('source'),'attributes':attributes})
        used_py.add((layer,e['event_id']))
    initial_display_seen=False;py_waits=[];py_frames=[]
    for e in result['events']:
        if e['event_type'] in {'production_selected','production_fired'}:
            add_py(e,'production.'+e['event_type'].split('_')[1],rule=base_rule(e['rule']))
        elif e['event_type'] in {'visual_location_stuffed','visual_location_return'}:
            loc=e.get('state_after',{}).get('visual_location')
            if loc:add_py(e,'location.write',loc['target'])
        elif e['event_type']=='task_boundary':add_py(e,'task.queue_end')
        elif e['event_type']=='model_stop':add_py(e,'boundary.model_stop')
        elif e['event_type']=='proc_display' and not initial_display_seen:
            initial_display_seen=True
            frame=(e.get('state_after') or {}).get('current_frame')
            add_py(e,'frame.initial',frame)
            py_frames.append({'from':None,'to':frame,'event_id':e['event_id']})
        elif e['event_type']=='proc_display' and e.get('details',{}).get('reason')=='system_wait_complete':
            add_py(e,'wait.visible',(e.get('state_after') or {}).get('current_frame'),
                   attributes=None)
        elif e['event_type']=='frame_transition':
            d=e['details'];add_py(e,'frame.transition',f"{d.get('from_frame')}->{d.get('to_frame')}")
            py_frames.append({'from':d.get('from_frame'),'to':d.get('to_frame'),'event_id':e['event_id']})
        elif e['event_type'] in {'system_wait_start','system_wait_end'}:
            phase=e['event_type'].rsplit('_',1)[1]
            frame=e['details'].get('frame')
            attributes={'duration_s':e['details'].get('duration_s')} if phase=='start' else None
            add_py(e,'wait.'+phase,frame,attributes=attributes)
            py_waits.append({'event_id':e['event_id'],'frame':frame,'phase':phase})
    steps={s.get('index',i):s for i,s in enumerate(result.get('steps',[]))}
    # The key's backend identity must come from the executed output record,
    # not by importing the predictor's key mapping into this evidence adapter.
    key_outputs={e['step_index']:e for e in result['motor_events'] if e['event_type']=='key_output'}
    py_device=[];py_release=[]
    for e in result['motor_events']:
        if e.get('state_after') is None:continue
        op=e['op'] if e['op'] in {'point','key','home'} else 'prepare' if e.get('details',{}).get('exec_immediate') is False else 'click'
        step=steps.get(e.get('step_index'),{})
        target=e['target']
        if op=='key':
            backend=key_outputs.get(e['step_index'],{}).get('details',{}).get('backend_key')
            target=f"{step.get('frame',e.get('state_before',{}).get('frame','?'))}:key:{str(backend).upper()}"
        elif op=='home':target=step.get('device')
        phase={'motor_preparation':'preparation_complete','motor_initiation':'initiation_complete','cursor_move':'output','click_output':'output','cursor_finish':'finish','click_finish':'finish','key_output':'output','key_finish':'finish','hand_move':'output','hand_finish':'finish'}.get(e['event_type'])
        if phase:
            if e['event_type']=='motor_preparation':
                add_py(e,f'motor.{op}.request',target,when='start_s',layer='motor')
                py_actions.append({'kind':op,'target':target,'event_id':e['event_id']})
            attributes={'coordinates':e.get('details',{}).get('coordinates')} if op=='key' and phase=='output' else None
            if op=='point' and phase=='output':attributes={'coordinates':e['state_after'].get('mouse')}
            add_py(e,f'motor.{op}.{phase}',target,layer='motor',attributes=attributes)
            if phase=='output':py_device.append(e)
            if phase=='finish':py_release.append(e)
    for kind,items in [('last_device_output',py_device),('last_manual_release',py_release)]:
        if items:
            add_py(max(items,key=lambda e:(e['end_s'],e.get('completion_order',-1))), 'boundary.'+kind,layer='motor')
    attention_seen=False
    for e in result.get('vision_events',[]):
        if e['status']!='executed':continue
        kind={'visual_attention_request':'request','eye_preparation_complete':'eye_prepare','eye_movement_complete':'eye_complete','visual_encoding_complete':'encoding','visual_clear_complete':'clear_complete','visual_clear_request':'clear_request'}.get(e['event_type'])
        if kind=='request': attention_seen=True
        if (kind=='clear_request' and not attention_seen and
                any(c['event_type']=='startup_empty_proc_display' for c in result['events'])):
            # Wrapper invokes this synchronously before run; it is not one of
            # the later +visual clear requests emitted by suppression rules.
            kind='startup_clear_request'
        if kind:add_py(e,'vision.'+kind,e['target'],layer='vision')
    ref_index={tuple(e['signature']):e for e in reference};py_index={tuple(e['signature']):e for e in python}
    rows=[]
    for signature in sorted(set(ref_index)|set(py_index),key=str):
        ref,py=ref_index.get(signature),py_index.get(signature)
        if ref and py:
            printed=Decimal(ref['time_text']);resolution=Decimal(1).scaleb(printed.as_tuple().exponent)
            tolerance=abs(resolution)/2
            delta=Decimal(str(py['time_s']))-printed
            status='time_match_at_printed_precision' if abs(delta)<=tolerance else 'time_mismatch'
            if status=='time_match_at_printed_precision' and ref.get('attributes')!=py.get('attributes'):
                status='attribute_mismatch'
        else:delta=tolerance=None;status='unmatched_reference' if ref else 'unmatched_python'
        rows.append({'semantic_signature':list(signature),'reference':ref,'python':py,'delta_s':float(delta) if delta is not None else None,'tolerance_s':float(tolerance) if tolerance is not None else None,'status':status,'resource_comparison':'not_comparable unless source explicitly prints the same state; null does not imply free'})
    unmatched_ref=[e for e in parsed['events'] if e['event_id'] not in used_ref]
    unmatched_py=[{'layer':layer,**e} for layer,key in [('control','events'),('motor','motor_events'),('vision','vision_events')] for e in result.get(key,[]) if (layer,e['event_id']) not in used_py]
    mismatches=[r for r in rows if r['status']!='time_match_at_printed_precision']
    def moment(row):return min(e['time_s'] for e in (row['reference'],row['python']) if e)
    first=min(mismatches,key=moment) if mismatches else None
    timed=[r for r in rows if r['status']=='time_mismatch']
    production_differences=[r for r in mismatches if r['semantic_signature'][0].startswith('production.')]
    required_prefixes=('production.','motor.','frame.','wait.','boundary.','task.queue_end',
                       'vision.request','vision.eye_prepare','vision.eye_complete','vision.encoding')
    required_differences=[r for r in mismatches if r['semantic_signature'][0].startswith(required_prefixes)]
    def ordered_check(ref,py):
        strip=lambda items:[{k:v for k,v in item.items() if k!='event_id'} for item in items]
        a,b=strip(ref),strip(py)
        differences=[{'index':i,'reference':a[i] if i<len(a) else None,'python':b[i] if i<len(b) else None}
                     for i in range(max(len(a),len(b))) if i>=len(a) or i>=len(b) or a[i]!=b[i]]
        return {'status':'mismatch' if differences else 'pass','reference':ref,'python':py,'differences':differences,
                'policy':'preserved within-domain event order; no sorting, deletion, nearest-time matching or time shift'}
    order_checks={'motor_requests':ordered_check(ref_actions,py_actions),
                  'frame_transitions':ordered_check(ref_frames,py_frames),'system_waits':ordered_check(ref_waits,py_waits)}
    order_mismatch=any(check['status']=='mismatch' for check in order_checks.values())
    unresolved_targets=[a for a in ref_actions if a['target'] is None]
    unresolved_frames=[f for f in ref_frames if f['to'] is None]
    # Reported summary boundaries must agree with actual executed events too;
    # this cannot be satisfied merely by keeping the final scalar unchanged.
    py_boundaries={'model_stop_time_s':next((e['end_s'] for e in result['events'] if e['event_type']=='model_stop'),None),
        'task_stop_time_s':next((e['end_s'] for e in result['events'] if e['event_type']=='model_stop'),None),
        'last_device_output_time_s':max((e['end_s'] for e in py_device),default=None),
        'last_manual_release_time_s':max((e['end_s'] for e in py_release),default=None),
        'simulation_end_time_s':next((e['end_s'] for e in result['events'] if e['event_type']=='task_boundary'),None)}
    boundary_claims=[{'field':field,'reported':result[field],'executed_event_time_s':value,
                     'status':'pass' if result[field]==value else 'mismatch'}
                    for field,value in py_boundaries.items() if field in result]
    claims_mismatch=any(item['status']=='mismatch' for item in boundary_claims)
    display_integrity=[]
    for index,event in enumerate(result['events']):
        if event['event_type']!='frame_transition':continue
        destination=event['details'].get('to_frame')
        displays=[e for e in result['events'][index+1:] if e['event_type']=='proc_display'
                  and e['end_s']==event['end_s'] and (e.get('state_after') or {}).get('current_frame')==destination]
        display_integrity.append({'transition_event_id':event['event_id'],'destination':destination,
            'proc_display_event_ids':[e['event_id'] for e in displays],
            'status':'pass' if len(displays)==1 else 'mismatch',
            'scope':'Python internal transition/display evidence; upstream synchronous proc-display itself is not printed'})
    display_mismatch=any(item['status']=='mismatch' for item in display_integrity)
    internal_checks=internal_execution_checks(model,result)
    internal_mismatch=any(item['status']=='mismatch' for item in internal_checks)
    mechanism_bad=bool(required_differences or order_mismatch or motor['issues'] or claims_mismatch or display_mismatch or internal_mismatch)
    mechanism_status='mismatch' if mechanism_bad else 'not_comparable' if unresolved_targets or unresolved_frames else 'pass'
    scalar=[x['value'] for x in parsed['raw_lines'] if x['kind']=='scalar_output']
    explicit_return=re.findall(r'^REFERENCE_RETURNED_TIME\s+([0-9.eE+-]+)\s*$',raw,re.M)
    if explicit_return: scalar.append(float(explicit_return[-1]))
    total_delta=(Decimal(str(result['predicted_time_s']))-Decimal(explicit_return[-1] if explicit_return else str(scalar[-1]))) if scalar and result['predicted_time_s'] is not None else None
    total_status=('not_comparable' if total_delta is None else 'pass' if
                  abs(total_delta)<=Decimal(plan['numeric_comparison']['raw_total_abs_tolerance_s']) else 'mismatch')
    paired_count=sum(r['reference'] is not None and r['python'] is not None for r in rows)
    archived=reference_kind=='archived_reference'
    evidence={'reference_kind':reference_kind,'comparison_scope':'archived_diagnostic' if archived else 'mapped_backend_events_only',
        'comparison_status':'not_comparable' if archived else 'mismatch' if timed or mechanism_bad or total_status=='mismatch' else 'not_comparable',
        'observed_paired_events_status':'mismatch' if timed or mechanism_bad else 'pass' if paired_count and mechanism_status=='pass' else 'not_comparable',
        'required_mechanisms_status':mechanism_status,
        'required_mechanism_differences':len(required_differences),
        'ordered_action_comparison':order_checks,
        'motor_ownership_diagnostics':motor['issues'],'unresolved_reference_targets':unresolved_targets,
        'unresolved_reference_frames':unresolved_frames,
        'boundary_claim_checks':boundary_claims,
        'python_frame_display_integrity':display_integrity,
        'python_execution_integrity':internal_checks,
        'reference_pending_keystrokes_observed':None,
        'mechanism_counts':{kind:{'reference':sum(e['signature'][0]==kind for e in reference),
                                 'python':sum(e['signature'][0]==kind for e in python)}
                            for kind in sorted({e['signature'][0] for e in reference+python})},
        'first_required_mechanism_difference':min(required_differences,key=moment) if required_differences else None,
        'proc_display_equivalence':None,
        'reason':'Different source generation/version; archived agreement is not a 2014 differential pass' if archived else 'Input/parameter/frontend equivalence and unmatched state evidence require explicit separate assessment; adapter never grants full pass',
        'first_observed_difference':first,'first_timestamp_mismatch':min(timed,key=moment) if timed else None,
        'first_production_difference':min(production_differences,key=moment) if production_differences else None,
        'mapped_time_matches':sum(r['status']=='time_match_at_printed_precision' for r in rows),
        'mapped_time_mismatches':len(timed),'mapped_attribute_mismatches':sum(r['status']=='attribute_mismatch' for r in rows),
        'unmatched_semantic_events':sum(r['status'].startswith('unmatched_') for r in rows),
        'unmapped_reference_event_count':len(unmatched_ref),'unmapped_python_event_count':len(unmatched_py),
        'reference_scalar_last':scalar[-1] if scalar else None,'python_prediction_s':result['predicted_time_s'],
        'total_tolerance_s':plan['numeric_comparison']['raw_total_abs_tolerance_s'],
        'raw_total_delta_s':float(total_delta) if total_delta is not None else None,
        'raw_total_comparison_status':total_status,
        'raw_reference_return_text':explicit_return[-1] if explicit_return else None,
        'cross_module_equal_time_order_equivalence':None,
        'no_time_shift':True,'no_adjacent_row_duration':True,'full_resource_state_equivalence':None,
        'adapter_sha256':digest(__file__),
        'hashes':{str(path):digest(path) for path in (input_path,python_result,reference_trace,plan_path)}}
    out.mkdir(parents=True)
    (out/'reference_trace.txt').write_text(raw)
    write(out/'parsed_reference.json',parsed);write(out/'semantic_mapping.json',rows)
    write(out/'unmatched_reference.json',unmatched_ref);write(out/'unmatched_python.json',unmatched_py)
    write(out/'summary.json',evidence)
    write(out/'ordered_actions.json',order_checks)
    write(out/'motor_ownership.json',motor)
    lines=['# 语义事件对照','',f'范围：{evidence["comparison_scope"]}；状态：{evidence["comparison_status"]}。',evidence['reason'],'','| 语义锚点 | 参考秒 | Python秒 | 差(s) | 状态 |','|---|---:|---:|---:|---|']
    for row in sorted(rows,key=moment):
        lines.append('| '+str(row['semantic_signature'])+' | '+str((row['reference'] or {}).get('time_s'))+' | '+str((row['python'] or {}).get('time_s'))+' | '+str(row['delta_s'])+' | '+row['status']+' |')
    lines+=['','全部未映射原始事件单独保存，未删除；resource state未知不填值。原始小数文本保留，时间只按该字段实际打印精度判断。','最早差异字段既包含时间不同，也包含某侧缺少的规则/事件；不把所有下游偏差重复当作独立根因。']
    (out/'COMPARISON_zh.md').write_text('\n'.join(lines)+'\n')
    return evidence


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('input','python-result','reference-trace','plan','out'):p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--reference-kind',required=True,choices=['archived_reference','upstream_end_to_end','upstream_backend_only','shared_generator_backend_check','ported_reference_backend'])
    a=p.parse_args();result=compare(a.input,a.python_result,a.reference_trace,a.plan,a.out,a.reference_kind)
    print(json.dumps({k:result[k] for k in ['reference_kind','comparison_status','mapped_time_matches','mapped_time_mismatches']},ensure_ascii=False))
if __name__=='__main__':main()
