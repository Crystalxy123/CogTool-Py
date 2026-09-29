"""Compare original Java observations with bounded Python task inputs/steps.

Comparisons preserve widget, action and group-member order. Raw Java flags and
Python zero-time transition annotations are retained alongside the mapped view.
"""
from __future__ import annotations
import argparse,json,hashlib,math,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cogtool_py.io import load_project, input_hash
try:
    from scripts.compare_java_generation import differences
except ModuleNotFoundError:
    from compare_java_generation import differences


def read(p):return json.loads(Path(p).read_text())
def write(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def compare_groups(auxiliary, frame_names, widgets, java_frames):
    """Check executed coordinates as well as provenance, without filling gaps."""
    rows=[]; covered=[]
    expected={(name,g['id']) for name in frame_names.values()
              for g in java_frames[name]['groups_in_first_widget_encounter_order']}
    for aux in auxiliary:
        src=json.loads(aux['source']); name=frame_names[aux['frame']]
        members=[widgets['w'+m]['name'] for m in src['members']]
        matches=[g for g in java_frames[name]['groups_in_first_widget_encounter_order']
                 if [m['name'] for m in g['members_in_iteration_order']]==members]
        center=None
        if len(matches)==1:
            g=matches[0];b=g['bounds'];covered.append((name,g['id']))
            center={'x':b['x']+math.floor(b['width']/2),
                    'y':b['y']+math.floor(b['height']/2)}
        actual={k:aux[k] for k in ('x','y')}
        rows.append({'python_group':aux['id'],'java_matches':[g['id'] for g in matches],
                     'bounds_and_member_order_equal':len(matches)==1 and matches[0]['bounds']==src['bounds'],
                     'members':members,'java_raw_name':matches[0]['raw_name'] if len(matches)==1 else None,
                     'python_geometry':src['bounds'],'java_expected_center':center,
                     'python_effective_center':actual,'effective_center_equal':actual==center})
    coverage={'unmatched_java_groups':[list(g) for g in sorted(expected-set(covered))],
              'unexpected_java_groups':[list(g) for g in sorted(set(covered)-expected)],
              'duplicate_matches':len(covered)!=len(set(covered))}
    passed=all(r['bounds_and_member_order_equal'] and r['effective_center_equal'] for r in rows)
    return rows,coverage,passed and not any(coverage.values())


def action(step):
    a=step.get('action') or (step.get('transition') or {}).get('action')
    if not a:
        if step['class'].endswith('.ThinkScriptStep'):return 'think'
        if step['class'].endswith('.TextActionSegment'):return 'text_segment'
        if step['class'].endswith('.TransitionDelayScriptStep'):return 'wait'
        if step['class'].endswith('.LookAtScriptStep'):return 'look_at'
        raise ValueError('Unmapped Java step class '+step['class'])
    if a['class'].endswith('.MoveMouseAction'):return 'point'
    if a['class'].endswith('.HomeAction'):return 'home'
    if (a['class'].endswith('.KeyAction') and type(a.get('is_command')) is bool
            and type(a.get('modifiers')) is int):return 'keys'
    if a['class'].endswith('.ButtonAction') and a['press_type']=='Click':
        if a['button'] in ('Left','Right'):return 'click' if a['button']=='Left' else 'right_click'
    raise ValueError('Unmapped Java action '+str(a))


def model_context(project):
    frames=project['design']['frames']
    names={f['id']:f['name'] for f in frames}
    widgets={w['id']:w for f in frames for w in f['widgets']}
    widget_frames={w['id']:f['id'] for f in frames for w in f['widgets']}
    transitions={t['id']:t for t in project['design']['transitions']}
    return names,widgets,widget_frames,transitions


def mapped_row(op,frame,target,demo_index,origin,*,duration=None,key=None,device=None,hand=None,label=None):
    return {'op':op,'frame':frame,'target':target,'demo_index':demo_index,
            'input_or_generated':origin,'duration_s':duration,'key':key,'device':device,
            'hand':hand,'delay_label':label}


def key_text(text):
    if not isinstance(text,str) or not text or not all('a'<=c<='z' or '0'<=c<='9' or c=='\ue00d' for c in text):
        raise ValueError('Expected observed unshifted lowercase ASCII letters/digits or source DOWN U+E00D')
    return ['DOWN' if c=='\ue00d' else c for c in text]


def python_key_text(action):
    return action.get('key_text',''.join('\ue00d' if k=='DOWN' else k for k in action['keys']))


def java_source(transition,frame,require_typed=False):
    details=transition.get('source_details')
    if details is None:
        if require_typed:raise ValueError('Typed transition source evidence missing; regenerate observer')
        kind='input_device' if transition['action']['class'].endswith('.KeyAction') else 'widget'
        # Compatibility for previously frozen observer files. New explicit
        # device inputs require actual source_details instead of this path.
        return {'source_type':kind,'trigger_target':transition['source'],'source_frame':frame,
                'device_kind':'keyboard' if kind=='input_device' else None}
    if details['frame']!=frame or details['name']!=transition['source']:
        raise ValueError('Transition source name/frame disagree with its observed object')
    kind=details['kind']
    if kind not in {'widget','input_device'}:raise ValueError('Unknown observed source type')
    return {'source_type':kind,'trigger_target':details['name'],'source_frame':details['frame'],
            'device_kind':str(details['device_type']).lower() if kind=='input_device' else None}


def python_source(project,transition):
    names,widgets,widget_frames,_=model_context(project)
    frame=transition['from_frame'];kind=transition.get('source_type','widget')
    if kind=='input_device':
        candidates=[d for f in project['design']['frames'] if f['id']==frame for d in f.get('devices',[])
                    if d['id']==transition.get('source_id')]
        if len(candidates)!=1:raise ValueError('InputDevice source does not belong to the transition frame')
        d=candidates[0]
        return {'source_type':kind,'trigger_target':d['name'],'source_frame':names[frame],'device_kind':d['kind']}
    target=transition.get('target')
    if target not in widgets or widget_frames[target]!=frame:raise ValueError('Widget transition source belongs to another frame')
    return {'source_type':'widget','trigger_target':widgets[target]['name'],'source_frame':names[frame],'device_kind':None}


def transition_key_fields(transition,java=False):
    a=transition['action'] if java else transition
    if java and not a['class'].endswith('.KeyAction') or not java and transition.get('source_type','widget')!='input_device':
        return {'keys':None,'key_text':None,'is_command':None,'modifiers':None}
    return {'keys':key_text(a['text']) if java else list(a['keys']),
            'key_text':a['text'] if java else python_key_text(a),
            'is_command':a['is_command'],'modifiers':a['modifiers']}


def map_java_steps(fresh,demonstration=None,require_typed=False):
    """Map every raw state or record an explicit unresolved entry; preserve order."""
    rows,witnesses,contracts,unmapped=[],[],[],[]
    for index,state in enumerate(fresh):
        s=state['step']
        try:
            op=action(s);demo=s['owner_demonstration_index']
            origin='input' if s['inserted_by_user'] else 'generated'
            if op=='text_segment':
                text=s.get('text')
                for offset,key in enumerate(key_text(text)):
                    rows.append(mapped_row('key',s['frame'],None,demo,origin,key=key,device='keyboard'))
                    witnesses.append({'mapped_index':len(rows)-1,'java_raw_step_index':index,
                                      'segment_text':text,'character_index':offset,'character':key,
                                      'source_character':text[offset],'source_codepoint':f'U+{ord(text[offset]):04X}'})
                owner=s.get('owner_transition')
                if require_typed and ('owner_transition' not in s or type(s.get('text_segment_destination_applies')) is not bool):
                    raise ValueError('TextActionSegment owner/destination evidence missing')
                if 'owner_transition' not in s and demonstration is not None:
                    owner=demonstration['steps'][s['owner_demonstration_index']].get('transition')
                if demonstration is not None:
                    expected=demonstration['steps'][s['owner_demonstration_index']].get('transition')
                    if require_typed and owner!=expected:
                        raise ValueError('TextActionSegment owner differs from demonstrated transition')
                applies=s.get('text_segment_destination_applies',s['inserted_by_user'])
                if owner is not None and applies:
                    if s['destination']!=owner['destination']:
                        raise ValueError('TextActionSegment destination disagrees with owner transition')
                    position=len(rows)
                    if owner['delay_s']>0:
                        if index+1>=len(fresh) or not fresh[index+1]['step']['class'].endswith('.TransitionDelayScriptStep'):
                            raise ValueError('Positive key transition delay lacks generated delay state')
                        position+=1
                    contracts.append({'demo_index':s['owner_demonstration_index'],
                        'from_frame':s['frame'],'to_frame':owner['destination'],
                        **java_source(owner,s['frame'],require_typed),**transition_key_fields(owner,java=True),
                        'action_position':position,'duration_s':0.0})
                continue
            kwargs={'duration':s.get('duration_s')}
            target=s['focus']
            if op=='home':
                a=s['action'];device={'Keyboard':'keyboard','Mouse':'mouse'}.get(a.get('home_target'))
                if device is None or a.get('hand') not in ('left','right'):
                    raise ValueError('Home target/hand not observed; regenerate with current observer')
                target=None;kwargs.update(device=device,hand=a['hand'])
            elif op=='wait':
                kwargs['label']=s.get('delay_label')
                previous=fresh[index-1]['step'] if index else {}
                trigger=previous.get('transition') or previous.get('owner_transition')
                if not trigger and demonstration is not None and previous.get('owner_demonstration_index') is not None:
                    trigger=demonstration['steps'][previous['owner_demonstration_index']].get('transition')
                if index==0 or previous.get('owner_demonstration_index')!=demo or not trigger:
                    raise ValueError('TransitionDelay has no immediately preceding trigger in this bounded mapping')
            elif op=='keys':
                raise ValueError('Raw KeyAction generated state is outside TextActionSegment mapping')
            rows.append(mapped_row(op,s['frame'],target,demo,origin,**kwargs))
            witnesses.append({'mapped_index':len(rows)-1,'java_raw_step_index':index})
            if 'transition' in s:
                t=s['transition'];position=len(rows)
                if t['delay_s']>0:
                    if index+1>=len(fresh) or not fresh[index+1]['step']['class'].endswith('.TransitionDelayScriptStep'):
                        raise ValueError('Positive transition delay has no generated delay state')
                    position+=1
                contracts.append({'demo_index':demo,'from_frame':s['frame'],'to_frame':t['destination'],
                                  **java_source(t,s['frame'],require_typed),**transition_key_fields(t,java=True),
                                  'action_position':position,'duration_s':0.0})
        except (ValueError,KeyError) as exc:
            unmapped.append({'raw_step_index':index,'reason':str(exc),'raw':state})
    return rows,witnesses,contracts,unmapped


def map_python_steps(project,result):
    names,widgets,widget_frames,transitions=model_context(project)
    task=project['tasks'][0];demo=task['demonstration']['steps']
    rows,witnesses,contracts,annotations,unmapped=[],[],[],[],[]
    offsets={}
    for index,s in enumerate(result['steps']):
        try:
            frame=names[s['frame']];op=s['op'];di=s['demo_index']
            if not isinstance(di,int) or not 0<=di<len(demo):raise ValueError('Invalid demonstration reference')
            if op=='transition':
                annotations.append(s)
                t=transitions.get(s.get('note'))
                if t is None or demo[di].get('transition')!=s.get('note'):
                    raise ValueError('Transition annotation does not bind its demonstrated transition')
                before,after=s['state_before']['frame'],s['state_after']['frame']
                contracts.append({'demo_index':di,'from_frame':names[before],'to_frame':names[after],
                                  **python_source(project,t),**transition_key_fields(t),'action_position':len(rows),
                                  'duration_s':s['duration_s']})
                if s['frame']!=before:raise ValueError('Transition annotation frame differs from before-state')
                continue
            if op not in ('think','point','click','right_click','home','key','wait','look_at'):
                raise ValueError('Unsupported generated operation '+str(op))
            target=s.get('target')
            if target is not None and widget_frames[target]!=s['frame']:
                raise ValueError('Widget reference belongs to another frame, even if its name is equal')
            kwargs={'duration':s.get('duration_s')}
            if op=='key':
                key=s.get('key')
                if not isinstance(key,str) or (key!='DOWN' and len(key)!=1):raise ValueError('Unsupported physical key')
                key_text('\ue00d' if key=='DOWN' else key)
                kwargs.update(key=key,device=s.get('device'));target=None
            elif op=='home':
                kwargs.update(device=s.get('device'),hand=task['demonstration']['initial']['mouse_hand'])
            elif op=='wait':
                t=transitions.get(demo[di].get('transition'))
                if t is None or s['origin']!='automatic':raise ValueError('Wait is not a mapped automatic transition delay')
                kwargs['label']=t.get('delay_label')
            rows.append(mapped_row(op,frame,widgets[target]['name'] if target else None,di,
                                   'input' if s['origin']=='demonstrated' else 'generated',**kwargs))
            witness={'mapped_index':len(rows)-1,'python_raw_step_index':index}
            if op=='key':
                witness['character_index_within_demo']=offsets.get(di,0)
                offsets[di]=offsets.get(di,0)+1
            if op=='wait':witness['delay_label_source']='Python input transition bound by demo_index; step has no label field'
            witnesses.append(witness)
        except (ValueError,KeyError) as exc:
            unmapped.append({'raw_step_index':index,'reason':str(exc),'raw':s})
    return rows,witnesses,contracts,annotations,unmapped


def map_demonstrations(project,demo):
    names,widgets,widget_frames,transitions=model_context(project)
    java,python,unmapped=[],[],[]
    initial=project['tasks'][0]['demonstration']['initial']
    current=initial['frame'];zero_labels=[]
    require_typed=any(f.get('devices') for f in project['design']['frames'])
    for index,s in enumerate(demo['steps']):
        try:
            op=action(s);t=s.get('transition')
            if op=='keys':
                a=s.get('action') or t['action']
                focus=s.get('focus_details')
                if a.get('press_type')!='Type' or (require_typed and
                        (not focus or focus['kind']!='input_device' or focus['device_type']!='Keyboard' or focus['frame']!=s['frame'])):
                    raise ValueError('Keyboard mapping requires observed current-frame InputDevice and Type action')
                if not require_typed and s.get('focus')!='Keyboard':
                    raise ValueError('Legacy keyboard focus is not observed')
                source=java_source(t,s['frame'],require_typed) if t else None
                if t and focus and focus['id']!=t['source_details']['id']:
                    raise ValueError('Keyboard focus identity differs from transition source')
                java.append({'op':'keys','frame':s['frame'],'destination':s['destination'],
                    'target':None,'device':'keyboard','keys':key_text(a.get('text')),'key_text':a.get('text'),
                    'is_command':a['is_command'],'modifiers':a['modifiers'],'transition_source':source,
                    'delay_s':t['delay_s'] if t else None,
                    'delay_label':t.get('delay_label') if t and t['delay_s']>0 else None})
            elif op=='look_at':
                if s['destination']!=s['frame'] or s.get('duration_s') is not None:
                    raise ValueError('Source LookAt must be a duration-free same-frame visual request')
                java.append({'op':'look_at','frame':s['frame'],'destination':s['destination'],
                             'target':s['focus'],'duration_s':None})
            elif op=='click':
                if t is None:raise ValueError('Click lacks a retained transition object')
                java.append({'op':'click','frame':s['frame'],'destination':s['destination'],'target':s['focus'],
                    'delay_s':t['delay_s'],'delay_label':t.get('delay_label') if t['delay_s']>0 else None,
                    'transition_source':java_source(t,s['frame'],require_typed)})
            else:raise ValueError('Unsupported demonstration '+op)
            if t and t['delay_s']==0:zero_labels.append({'side':'java','demo_index':index,'label':t.get('delay_label')})
        except (ValueError,KeyError,TypeError) as exc:unmapped.append({'side':'java','index':index,'reason':str(exc),'raw':s})
    for index,s in enumerate(project['tasks'][0]['demonstration']['steps']):
        try:
            t=transitions.get(s.get('transition'))
            if s['op']=='keys':
                if s.get('device')!='keyboard':raise ValueError('Unsupported keyboard role')
                if t and (t['from_frame']!=current or t.get('source_type')!='input_device' or s.get('device_id')!=t.get('source_id')):
                    raise ValueError('Key transition does not bind the current keyboard device')
                if s.get('device_id') is not None:
                    matches=[d for f in project['design']['frames'] if f['id']==current for d in f.get('devices',[]) if d['id']==s['device_id']]
                    if len(matches)!=1 or matches[0]['kind']!='keyboard':raise ValueError('Key device is absent from current frame')
                python.append({'op':'keys','frame':names[current],'destination':names[t['to_frame']] if t else names[current],
                    'target':None,'device':'keyboard','keys':s['keys'],'key_text':python_key_text(s),
                    'is_command':s.get('is_command',False),'modifiers':s.get('modifiers',0),
                    'transition_source':python_source(project,t) if t else None,
                    'delay_s':t['delay_s'] if t else None,
                    'delay_label':t.get('delay_label') if t and t['delay_s']>0 else None})
            elif s['op']=='look_at':
                if widget_frames[s['target']]!=current or s.get('duration_s') is not None or t is not None:
                    raise ValueError('Source LookAt must bind current widget without duration/transition')
                python.append({'op':'look_at','frame':names[current],'destination':names[current],
                               'target':widgets[s['target']]['name'],'duration_s':None})
            elif s['op'] in ('click','menu_select'):
                if t is None:raise ValueError('Demonstrated click has no transition binding')
                if t['from_frame']!=current or widget_frames[s['target']]!=current:
                    raise ValueError('Demonstration references the wrong current frame')
                python.append({'op':'click','frame':names[current],'destination':names[t['to_frame']],
                    'target':widgets[s['target']]['name'],'delay_s':t['delay_s'],
                    'delay_label':t.get('delay_label') if t['delay_s']>0 else None,
                    'transition_source':python_source(project,t)})
            else:raise ValueError('Unsupported demonstration operation '+s['op'])
            if t:
                if t['delay_s']==0:zero_labels.append({'side':'python','demo_index':index,'label':t.get('delay_label')})
                current=t['to_frame']
        except (ValueError,KeyError,TypeError) as exc:unmapped.append({'side':'python','index':index,'reason':str(exc),'raw':s})
    return java,python,unmapped,zero_labels


def inventory_keys(text):
    """Read-only known KeyAction units, preserving unexecuted transition edges.

    KeyboardUtil.java defines DOWN_ARROW_CHAR U+E00D. The bounded execution
    mapping admits that exact physical direction key through key_text().
    """
    return ['DOWN' if c=='\ue00d' else c for c in text]


def compare_devices(frames,java_frames,transitions):
    rows=[];issues=[]
    for frame in frames:
        declared=frame.get('devices',[])
        if not declared:continue  # legacy projects do not claim explicit device inventory
        jf=java_frames.get(frame['name'],{})
        observed=jf.get('input_devices_in_iteration_order')
        if observed is None:
            issues.append('InputDevice inventory not observed for '+frame['name']);continue
        # Preserve relative order of the explicitly retained device subset;
        # unused Java mouse devices are retained in the raw scene, not fabricated.
        selected=[d for d in observed if d['name'] in {p['name'] for p in declared}]
        java=[{'name':d['name'],'kind':str(d['device_type']).lower(),'frame':d['frame'],'source_type':d['kind']} for d in selected]
        python=[{'name':d['name'],'kind':d['kind'],'frame':frame['name'],'source_type':'input_device'} for d in declared]
        rows.append({'frame':frame['name'],'java':java,'python':python,'differences':differences(java,python)})
        for device in declared:
            matches=[d for d in selected if d['name']==device['name']]
            if len(matches)!=1:
                issues.append('Device name does not uniquely bind observed object: '+device['name']);continue
            jt=matches[0].get('transitions_in_iteration_order')
            if jt is None:
                issues.append('Device transition inventory missing: '+device['name']);continue
            expected=[]
            for t in jt:
                a=t['action']
                if not a['class'].endswith('.KeyAction') or a.get('press_type')!='Type':
                    issues.append('Unsupported observed device action: '+str(a));continue
                source=t.get('source_details')
                if (not source or source.get('id')!=matches[0].get('id') or source.get('kind')!='input_device'
                        or source.get('frame')!=frame['name'] or source.get('name')!=device['name']):
                    issues.append('Device transition source identity disagrees with owning observed device: '+device['name'])
                expected.append({'destination':t['destination'],'keys':inventory_keys(a['text']),
                    'key_text':a['text'],'is_command':a['is_command'],'modifiers':a['modifiers'],
                    'delay_s':t['delay_s'],'delay_label':t.get('delay_label') if t['delay_s']>0 else None})
            names={f['id']:f['name'] for f in frames}
            actual=[{'destination':names[t['to_frame']],'keys':t['keys'],
                    'key_text':python_key_text(t),'is_command':t['is_command'],'modifiers':t['modifiers'],
                    'delay_s':t['delay_s'],'delay_label':t.get('delay_label') if t['delay_s']>0 else None}
                    for t in transitions if t.get('source_type')=='input_device' and t.get('source_id')==device['id'] and t['from_frame']==frame['id']]
            rows.append({'frame':frame['name'],'device':device['name'],'scope':'complete retained device transition inventory including unexecuted edges',
                         'java':expected,'python':actual,'differences':differences(expected,actual)})
    return rows,issues

def compare(generation,python_input,python_result,out):
    generation,out=Path(generation),Path(out)
    if out.exists():raise FileExistsError('Comparison exists; choose new output')
    scene=read(generation/'original_scene.json');demo=read(generation/'original_demonstration.json');fresh=read(generation/'fresh_steps.json');record=read(generation/'generation_record.json')
    project,result=read(python_input),read(python_result)
    effective_hash=input_hash(load_project(python_input))
    if result.get('input_sha256')!=effective_hash:
        raise ValueError('Python result input_sha256 does not match the effective input being compared')
    frames=project['design']['frames'];frame_names,widgets,widget_frames,transitions=model_context(project)
    task=project['tasks'][0];initial=task['demonstration']['initial']
    by_name={f['name']:f for f in scene['frames_in_iteration_order']};frame_rows=[]
    scene_issues=[]
    if len(by_name)!=len(scene['frames_in_iteration_order']) or len(set(frame_names.values()))!=len(frame_names):
        scene_issues.append('Frame names are ambiguous; no global name-only match is valid')
    kinds={'Context Menu':'context_menu','Menu Item':'menu_item','Button':'button','Link':'link','Text Box':'textbox','Text':'text'}
    for pf in frames:
        jf=by_name.get(pf['name'])
        if jf is None:
            scene_issues.append('Python retained frame absent from Java: '+pf['name']);continue
        java=[{'name':w['name'],'label':w['title'],'kind':kinds.get(w['kind'],w['kind']),
               'bounds':w['bounds'],'parent':w['parent']} for w in jf['widgets_in_iteration_order']]
        python=[{'name':w['name'],'label':w['label'],'kind':w['kind'],
                 'bounds':{k:w[k] for k in ('x','y','width','height')},
                 'parent':widgets[w['parent']]['name'] if w.get('parent') else None} for w in pf['widgets']]
        frame_rows.append({'frame':pf['name'],'java':java,'python':python,'differences':differences(java,python)})
    reachable={demo['start_frame']}|{s['frame'] for s in demo['steps']}|{s['destination'] for s in demo['steps']}
    missing_reachable=sorted(reachable-set(frame_names.values()))
    if missing_reachable:scene_issues.append('Reachable Java frame omitted: '+str(missing_reachable))
    jdemo,pdemo,demo_unmapped,zero_labels=map_demonstrations(project,demo)
    jsteps,jwitness,jcontracts,junmapped=map_java_steps(fresh,demo,any(f.get('devices') for f in frames))
    device_rows,device_issues=compare_devices(frames,by_name,project['design']['transitions'])
    psteps,pwitness,pcontracts,annotations,punmapped=map_python_steps(project,result)
    initial_fields=('mouse_hand','left_hand','right_hand','last_clicked','last_moved','last_looked','keyboard_modifiers')
    jinitial={k:demo['initial_state'][k] for k in initial_fields}
    pinitial={'mouse_hand':initial['mouse_hand']=='right','left_hand':'Keyboard','right_hand':'Keyboard',
              'last_clicked':None,'last_moved':None,'last_looked':None,'keyboard_modifiers':0}
    pinitial[initial['mouse_hand']+'_hand']='Mouse' if initial['hand']=='mouse' else 'Keyboard'
    jinitial['start_frame']=demo['start_frame'];pinitial['start_frame']=frame_names[initial['frame']]
    if 'last_step_is_mental' in demo['initial_state']:
        jinitial['last_step_is_mental']=demo['initial_state']['last_step_is_mental'];pinitial['last_step_is_mental']=False
    groups_issue=None
    try:
        groups,group_coverage,groups_pass=compare_groups(project['control']['auxiliary_locations'],frame_names,widgets,by_name)
    except (ValueError,KeyError) as exc:
        groups,group_coverage,groups_pass=[],{},False;groups_issue=str(exc)
    d={'scene':frame_rows,'scene_issues':scene_issues,'devices':device_rows,'device_issues':device_issues,'demonstration':differences(jdemo,pdemo),
       'fresh_steps':differences(jsteps,psteps),'transition_contracts':differences(jcontracts,pcontracts),
       'initial_saved_fields':differences(jinitial,pinitial),
       'unmapped_demonstrations':demo_unmapped,'unmapped_java_steps':junmapped,'unmapped_python_steps':punmapped}
    def status(diff,unknown=False):return 'not_comparable' if unknown else ('mismatch' if diff else 'pass')
    summary={'case_id':record['case_id'],'fresh_regeneration_verified':record['fresh_regeneration_verified'],
             'case_origin':record.get('case_origin','official_original_project'),
             'high_level_spec_shared':record.get('high_level_spec_shared',False),
             'retained_scene_geometry_label_parent_order_status':status(scene_issues or any(r['differences'] for r in frame_rows)),
             'demonstration_status':status(d['demonstration'],bool(demo_unmapped)),
             'typed_input_device_status':status(any(r['differences'] for r in device_rows),bool(device_issues)),
             'fresh_action_sequence_status':status(d['fresh_steps'],bool(junmapped or punmapped)),
             'transition_commit_contract_status':status(d['transition_contracts'],bool(junmapped or punmapped)),
             'initial_saved_fields_status':status(d['initial_saved_fields']),
             'group_geometry_and_member_order_status':status(not groups_pass,groups_issue is not None),
             'group_coverage':group_coverage,'group_mapping_issue':groups_issue,
             'python_result_input_hash_verified':True,'effective_input_sha256':effective_hash,
             'original_java_step_count':len(fresh),'java_mapped_action_count':len(jsteps),
             'python_original_step_count':len(result['steps']),'python_action_step_count':len(psteps),
             'python_extra_annotations_count':len(annotations),
             'granularity_policy':'Raw Java states and complete Python steps retained separately. TextActionSegment maps by explicit character index; no sort or deduplication.',
             'annotation_meaning':'Python transition commits are retained and separately compared with original Java TransitionScriptStep source/destination/trigger and position after its optional delay. No extra Java production is claimed.',
             'zero_delay_label_policy':'Raw labels preserved in zero_delay_labels.json and original inputs. With delay=0 no delay event consumes its label; mapped action contract uses null only for that inactive label.',
             'java_flags_note':'inserted_by_user determines mapped input origin; all original demonstrated/generated flags retained.',
             'frames_absent_in_python':[f['name'] for f in scene['frames_in_iteration_order'] if f['name'] not in frame_names.values()],
             'reachable_frames_absent_in_python':missing_reachable,
             'initial_eye_and_cursor_in_archived_state':'not_observed; runtime defaults compared separately',
             'full_state_snapshot_equivalence':'not_comparable: Java generator and Python controller state schemas differ; original snapshots retained',
             'full_model_equivalence':None,
             'hashes':{str(p):sha(p) for p in (generation/'generation_record.json',generation/'original_scene.json',
                       generation/'original_demonstration.json',generation/'fresh_steps.json',Path(python_input),Path(python_result),Path(__file__))}}
    checked=[summary[key] for key in ('retained_scene_geometry_label_parent_order_status','demonstration_status',
             'fresh_action_sequence_status','transition_commit_contract_status','initial_saved_fields_status','group_geometry_and_member_order_status','typed_input_device_status')]
    summary['bounded_task_comparison_status']='pass' if all(x=='pass' for x in checked) else ('not_comparable' if 'not_comparable' in checked else 'mismatch')
    out.mkdir(parents=True)
    for filename in ('original_scene.json','original_demonstration.json','fresh_steps.json','generation_record.json'):
        shutil.copyfile(generation/filename,out/('java_raw_'+filename))
    write(out/'python_raw_steps.json',result['steps'])
    for filename,value in {'summary':summary,'differences':d,'groups':groups,'java_mapped_steps':jsteps,
                           'python_mapped_steps':psteps,'java_mapping_witnesses':jwitness,'python_mapping_witnesses':pwitness,
                           'java_transition_contracts':jcontracts,'python_transition_contracts':pcontracts,
                           'python_retained_annotations':annotations,'java_demonstration':jdemo,
                           'python_demonstration':pdemo,'zero_delay_labels':zero_labels}.items():
        write(out/(filename+'.json'),value)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('generation','python-input','python-result','out'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();print(json.dumps(compare(a.generation,a.python_input,a.python_result,a.out),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
