"""Bounded independent official task import; no saved Script/result is consulted.

The original Design/Demonstration is read through audited persistence fields.
Reachability is the closure of original widget/device transitions, not only the
visited demonstration frames. Unsupported semantics are retained in raw_task.json
and rejected when they cannot be represented faithfully in the Python schema.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, math, subprocess, sys
from io import BytesIO
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.convert_phone_additional import InputGraph
from scripts.convert_phone_case import ConversionError, app_for, parent_chain
from scripts.inspect_original_models import CODE_COMMIT,DOC_COMMIT,DOC_ROOT,MAX_BYTES,classname,safe_member
KIND={'0':'noninteractive','1':'button','2':'menu_header','3':'submenu','4':'menu_item','5':'textbox','6':'pulldown_header','7':'pulldown_item','8':'listbox_item','9':'radio','10':'checkbox','11':'graffiti','12':'text','13':'link','14':'context_menu'}
CURRENT_KINDS={'button','link','textbox','text','context_menu','menu_item'}
def sha(b):return hashlib.sha256(b).hexdigest()
def write(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def read_official(path):
    path=Path(path).resolve();relative=path.relative_to(DOC_ROOT.resolve());data=path.read_bytes()
    if len(data)>MAX_BYTES:raise ConversionError('Archive exceeds bounded reader size')
    blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
    expected=subprocess.check_output(['git','-C',str(ROOT/'documentation'),'rev-parse',f'{DOC_COMMIT}:{relative.as_posix()}'],text=True).strip()
    if blob!=expected:raise ConversionError('Official bytes differ from pinned documentation Git object')
    layers=[]
    with zipfile.ZipFile(BytesIO(data))as z:
        if 'PERSIST' in z.namelist():persist=safe_member(z,'PERSIST',layers)
        else:
            choices=[n for n in z.namelist()if n.endswith('.cgt')]
            if len(choices)!=1:raise ConversionError('Expected exactly one original .cgt archive')
            inner=safe_member(z,choices[0],layers)
            with zipfile.ZipFile(BytesIO(inner))as z2:persist=safe_member(z2,'PERSIST',layers)
    if b'<!DOCTYPE' in persist.upper()or b'<!ENTITY' in persist.upper():raise ConversionError('DTD/entity forbidden')
    root=ET.fromstring(persist)
    if root.tag!='persist'or root.get('version')!='2':raise ConversionError('Expected CogTool persistence version 2')
    graph=InputGraph(root)
    if any(n.get('idref')not in graph.index for n in root.iter('ref')):raise ConversionError('Dangling original object reference')
    return graph,{'path':str(path),'sha256':sha(data),'git_blob':blob,'documentation_commit':DOC_COMMIT,'persist_sha256':sha(persist),'persist_metadata':root.attrib,'archive_layers':layers,'semantic_reference_fields_read':False}
def objid(node):return None if node is None or node.tag=='null'else node.get('id')
def devices(g,frame):
    return [g.resolve(n)for n in g.entries(g.get(frame,'devices'))if n.tag!='key']
def transitions(g,source):
    return [g.resolve(n)for n in g.entries(g.get(source,'transitions'))if n.tag!='key']
def extract_task(g,design_name,task_name,case_id):
    app=app_for(g,design_name,task_name);demo=g.get(app,'demonstration');design=g.get(app,'design');start=g.get(demo,'startFrame');initial=g.get(demo,'initialState')
    declared_frames=g.entries(g.get(design,'frames'));by_id={f.get('id'):f for f in declared_frames}
    if objid(start)not in by_id:raise ConversionError('Demonstration starts outside its design')
    reachable=set();todo=[start];edges=[]
    while todo:
        f=todo.pop(0)
        if f.get('id')in reachable:continue
        reachable.add(f.get('id'))
        for source in [*g.entries(g.get(f,'widgets')),*devices(g,f)]:
            for t in transitions(g,source):
                dest=g.get(t,'destination')
                if objid(dest)not in by_id:raise ConversionError('Transition destination absent from original design')
                edges.append({'object_id':t.get('id'),'from_frame_object_id':f.get('id'),'source_object_id':source.get('id'),'source_class':classname(source),'to_frame_object_id':dest.get('id'),'action':g.action(g.get(t,'action')),'delay_s':g.value(t,'delayInSecs'),'delay_label':g.value(t,'delayLabel')})
                if dest.get('id')not in reachable:todo.append(dest)
    scene=[]
    for f in declared_frames:
        if f.get('id')not in reachable:continue
        widgets=[];groups={}
        for w in g.entries(g.get(f,'widgets')):
            item=g.target(w);item.update(kind_code=g.value(w,'widgetType'),kind=KIND.get(g.value(w,'widgetType'),'unknown'),parent_object_id=objid(g.get(w,'parent')),parent_group_object_id=objid(g.get(w,'parentGroup')),level=g.value(w,'level'),auxiliary_text=g.value(w,'auxText'))
            widgets.append(item)
            group=g.get(w,'parentGroup')
            if objid(group):
                members=g.entries(g.get(group,'members'));groups[group.get('id')]={'object_id':group.get('id'),'class':classname(group),'members':[m.get('id')for m in members],'raw_name':g.name(group)}
        scene.append({'object_id':f.get('id'),'name':g.name(f),'speaker_text':g.value(f,'speakerText'),'listen_time_s':g.value(f,'listenTimeInSecs'),'widgets':widgets,'groups':list(groups.values()),'devices':[{'object_id':d.get('id'),'name':g.name(d),'class':classname(d),'device_type_code':g.value(d,'deviceType')}for d in devices(g,f)]})
    steps=[]
    for s in g.entries(g.get(demo,'steps')):
        row=g.step(s);row['current_frame_object_id']=objid(g.get(s,'currentFrame'))
        if classname(s)=='TransitionScriptStep':row['destination_frame_object_id']=objid(g.get(g.get(s,'transition'),'destination'))
        if row.get('target')and row['target']['class']!='InputDevice':row['parent_chain']=parent_chain(g,g.index[row['target']['object_id']])
        steps.append(row)
    return {'case_id':case_id,'design_name':design_name,'task_name':task_name,'design_object_id':design.get('id'),'task_object_id':g.get(app,'task').get('id'),'task_application_object_id':app.get('id'),'demonstration_object_id':demo.get('id'),'initial_state_object_id':initial.get('id'),'start_frame_object_id':start.get('id'),'start_frame_chosen':g.value(demo,'startFrameChosen'),'initial_saved':{k:g.value(initial,k)for k in ('mouseHand','rightHandLoc','leftHandLoc','lastIsMental','modifiers')},'initial_widget_references':{k:objid(g.get(initial,k))for k in ('lastClickedWidget','lastMovedToWidget','lastLookedAtWidget')},'demonstration_steps':steps,'frames':scene,'transitions':edges,'omitted_unreachable_frame_ids':[f.get('id')for f in declared_frames if f.get('id')not in reachable],'frame_order_policy':'Original Design.frames order, filtered by full outgoing transition reachability closure','reference_values_consulted':False}
def make_input(raw,policy):
    if policy['engine']!='cogtool_control_prefix_experimental'or policy['control']['profile']!='source_2014_defaults'or policy['control']['execution_scope']!='integrated_task':raise ConversionError('Explicit source_2014 integrated policy required')
    initial=raw['initial_saved']
    if not raw['start_frame_chosen']or initial['mouseHand']is not True or initial['leftHandLoc']!='K'or initial['rightHandLoc']not in ('M','K')or initial['modifiers']!=0 or initial['lastIsMental']is not False or any(raw['initial_widget_references'].values()):raise ConversionError('Initial state cannot be faithfully represented in bounded schema')
    frames=[];aux=[]
    keyboard_used=any(t['source_class']=='InputDevice' for t in raw['transitions']) or any(s.get('action',{}).get('class')=='KeyAction' for s in raw['demonstration_steps'])
    # DeviceType.KEYBOARD_PERSISTENCE=1, never inferred from display name.
    device_by_id={d['object_id']:d for f in raw['frames'] for d in f['devices']}
    def key_action(action):
        if action['class']!='KeyAction' or action['pressType']!='0' or action['modifiers']!=0 or type(action['isCommand']) is not bool:
            raise ConversionError('Only explicit Stroke KeyAction with zero modifiers is supported')
        text=action['text']
        if not text or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789\ue00d' for c in text):
            raise ConversionError('KeyAction requires lowercase ASCII letters/digits; function keys/chords remain unsupported')
        return {'keys':['DOWN' if c=='\ue00d' else c for c in text], 'key_text':text,
                'is_command':action['isCommand'],'modifiers':action['modifiers']}
    def source_device(object_id):
        device=device_by_id.get(object_id)
        if device is None or device.get('device_type_code')!='1':
            raise ConversionError('Transition source must be the original frame-owned Keyboard InputDevice (DeviceType1)')
        return 'd'+object_id
    for f in raw['frames']:
        if f['speaker_text']not in ('',None)or f['listen_time_s']not in (0,None):raise ConversionError('Auditory frame content requires additional original mechanism')
        if f['groups']:raise ConversionError('Group-bearing scene requires an explicit group semantics adapter; raw input retained')
        widgets=[]
        for w in f['widgets']:
            if w['kind']not in CURRENT_KINDS:raise ConversionError('Unsupported original widget kind '+w['kind']+'; never remapped to button')
            if not w['geometry']or any(not isinstance(v,(float,int))or not math.isfinite(v)for v in w['geometry'].values()):raise ConversionError('Missing/nonfinite original widget geometry')
            if w['auxiliary_text']not in (None,''):raise ConversionError('Nonempty original auxiliary cue needs explicit preservation')
            widgets.append({'id':'w'+w['object_id'],'name':w['name'],'label':w['title']or'','kind':w['kind'],'parent':'w'+w['parent_object_id']if w['parent_object_id']else None,**w['geometry']})
        frames.append({'id':'f'+f['object_id'],'name':f['name'],'widgets':widgets,**({'devices':[{'id':'d'+d['object_id'],'name':d['name'],'kind':'keyboard'}for d in f['devices'] if d['device_type_code']=='1']} if keyboard_used else {})})
    ts=[]
    for t in raw['transitions']:
        a=t['action']
        if t['source_class']=='InputDevice':
            ts.append({'id':'t'+t['object_id'],'from_frame':'f'+t['from_frame_object_id'],
                'source_type':'input_device','source_id':source_device(t['source_object_id']),
                'to_frame':'f'+t['to_frame_object_id'],'delay_s':t['delay_s'],'delay_label':t['delay_label'],**key_action(a)})
            continue
        if a['class']!='ButtonAction'or a['button']!='0'or a['pressType']!='0'or a['modifiers']!=0:raise ConversionError('Transition action cannot be faithfully represented; retain original keyboard/press/chord metadata')
        ts.append({'id':'t'+t['object_id'],'from_frame':'f'+t['from_frame_object_id'],'target':'w'+t['source_object_id'],'to_frame':'f'+t['to_frame_object_id'],'delay_s':t['delay_s'],'delay_label':t['delay_label']})
    steps=[]
    for s in raw['demonstration_steps']:
        if s['class']=='LookAtScriptStep':
            if s.get('duration_s') is not None:
                raise ConversionError('Original LookAt unexpectedly has a duration; refuse to invent source attention semantics')
            steps.append({'op':'look_at','target':'w'+s['target']['object_id']})
            continue
        if s['class']!='TransitionScriptStep':raise ConversionError('Original demonstration requires additional explicit operation semantics')
        if s['action']['class']=='KeyAction':
            if s['target']['class']!='InputDevice':raise ConversionError('KeyAction must retain its original InputDevice source')
            steps.append({'op':'keys','device':'keyboard','device_id':source_device(s['target']['object_id']),
                'transition':'t'+s['transition_object_id'],**key_action(s['action'])})
            continue
        if s['action']['class']!='ButtonAction':raise ConversionError('Unsupported demonstrated action class')
        if s['target']['class']=='MenuItem':raise ConversionError('Menu generation is outside this ordinary-click task adapter')
        steps.append({'op':'click','target':'w'+s['target']['object_id'],'transition':'t'+s['transition_object_id']})
    control=copy.deepcopy(policy['control']);control['auxiliary_locations']=aux
    parameters=copy.deepcopy(policy['parameters'])
    if keyboard_used or initial['rightHandLoc']=='K':
        from cogtool_py.models import ParameterSet
        parameters=ParameterSet.parse(parameters,2).with_keyboard_defaults().input_dict()
    return {'schema_version':2,'id':raw['case_id']+'-official-input','name':raw['case_id']+' original complete demonstration','engine':policy['engine'],'parameters':parameters,'control':control,'design':{'id':'d'+raw['design_object_id'],'name':raw['design_name'],'coordinate_unit':'px','frames':frames,'transitions':ts},'tasks':[{'id':raw['case_id'],'name':raw['task_name'],'demonstration':{'initial':{'frame':'f'+raw['start_frame_object_id'],'mouse':[0.0,0.0],'mouse_hand':'right','hand':'mouse'if initial['rightHandLoc']=='M'else'keyboard','focus':None},'steps':steps}}]}
def convert(source_model,design,task,case_id,policy_input,out,raw_only=False):
    out=Path(out)
    if out.exists():raise FileExistsError('Preserve first conversion; choose a fresh directory')
    graph,provenance=read_official(source_model);raw=extract_task(graph,design,task,case_id);policy=json.loads(Path(policy_input).read_text())
    out.mkdir(parents=True);write(out/'raw_task.json',raw);write(out/'source.json',provenance);write(out/'field_accesses.json',graph.accesses)
    meta={'case_id':case_id,'source':provenance,'policy_input':str(Path(policy_input).resolve()),'policy_sha256':sha(Path(policy_input).read_bytes()),'copied_policy_fields':['engine','full effective parameters','control except newly derived auxiliary_locations'],'initial_mouse_source':{'value':[0,0],'commit':CODE_COMMIT,'path':'java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp','lines':'1150-1151','archive_2009_value':None},'independent_of_Java_export':True,'saved_Script_or_result_read':False,'converter_sha256':sha(Path(__file__).read_bytes()),'status':'raw_extracted_only'if raw_only else'pending'}
    if not raw_only:
        try:
            candidate=make_input(raw,policy);write(out/'input.json',candidate);meta.update(status='input_converted_not_predicted',input_sha256=sha((out/'input.json').read_bytes()),input_schema_note='Schema2 fields; current frozen engine may reject the requested task. No validation bypass or fallback prediction is performed.')
        except ConversionError as e:
            meta.update(status='unsupported_conversion',reason=str(e));write(out/'conversion.json',meta);raise
    write(out/'conversion.json',meta);return meta

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source-model','design','task','case-id','policy-input','out'):p.add_argument('--'+n,required=True)
    p.add_argument('--raw-only',action='store_true');a=p.parse_args();print(json.dumps(convert(a.source_model,a.design,a.task,a.case_id,a.policy_input,a.out,a.raw_only),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
