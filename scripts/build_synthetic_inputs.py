"""Independent Python input construction from declared high-level XML specs.

No Java observations, generated steps, model code or prediction times are read.
The specification is shared; the two readers/generators are independent.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, sys
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from cogtool_py.models import Project, ParameterSet
from cogtool_py.io import input_hash


def construct(spec,policy):
    data=Path(spec).read_bytes()
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Synthetic specification cannot contain DTD/entities')
    root=ET.fromstring(data)
    if root.tag!='synthetic-spec' or root.get('origin')!='synthetic' or root.get('schema_version')!='1':
        raise ValueError('Expected synthetic schema 1')
    design=root.find('design'); task=root.find('task'); frames=[]
    for frame in design.findall('frame'):
        widgets=[]
        for w in frame.findall('widget'):
            widgets.append({'id':frame.get('id')+':'+w.get('id'),'name':w.get('name'),
                'label':w.get('title'),'kind':w.get('kind'),'parent':None,
                **{k:float(w.get(k)) for k in ('x','y','width','height')}})
        devices=[]
        for device in frame.findall('device'):
            if device.get('kind')!='keyboard':raise ValueError('Only Keyboard InputDevice is in scope')
            devices.append({'id':frame.get('id')+':'+device.get('id'),
                            'name':device.get('name'),'kind':device.get('kind')})
        frames.append({'id':frame.get('id'),'name':frame.get('name'),'widgets':widgets,
                       **({'devices':devices} if devices else {})})
    transitions=[];steps=[];current=task.get('start_frame');keyboard=False
    for i,action in enumerate(task.find('demonstration')):
        if action.get('frame')!=current:raise ValueError('Declared action frame differs from reached frame')
        if action.tag=='type':
            if action.get('is_command') not in {'false','true'} or action.get('modifiers')!='0' or action.get('focus')!='keyboard_device':
                raise ValueError('Only zero-modifier Stroke on keyboard InputDevice is supported here')
            text=action.get('text')
            if not text or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789\ue00d' for c in text):raise ValueError('Only lowercase ASCII letters/digits and source DOWN marker admitted')
            physical_keys=['DOWN' if c=='\ue00d' else c for c in text]
            keyboard=True;step={'op':'keys','keys':physical_keys,'device':'keyboard'}
            if '\ue00d' in text:step['key_text']=text
            if action.get('is_command')=='true':step['is_command']=True
            if action.get('device_id') is not None:step['device_id']=current+':'+action.get('device_id')
            if action.get('destination') is not None:
                if 'device_id'not in step:raise ValueError('Keyboard transition requires explicit owned device')
                tid='t'+str(i);step['transition']=tid
                transitions.append({'id':tid,'from_frame':current,'source_type':'input_device',
                    'source_id':step['device_id'],'to_frame':action.get('destination'),
                    'keys':physical_keys,'is_command':action.get('is_command')=='true','modifiers':0,
                    **({'key_text':text} if '\ue00d' in text else {}),
                    'delay_s':float(action.get('delay_s')),'delay_label':action.get('delay_label','synthetic response')})
                current=action.get('destination')
            steps.append(step)
        elif action.tag=='look':
            if set(action.attrib)!={'frame','target'}:raise ValueError('Source LookAt has only frame/target, no dwell duration')
            steps.append({'op':'look_at','target':current+':'+action.get('target')})
        elif action.tag=='click':
            if (action.get('button'),action.get('press'),action.get('modifiers'))!=('left','click','0'):
                raise ValueError('Only explicit left single click is supported')
            target=current+':'+action.get('target');tid='t'+str(i)
            transitions.append({'id':tid,'from_frame':current,'target':target,
                'to_frame':action.get('destination'),'delay_s':float(action.get('delay_s')),
                'delay_label':action.get('delay_label','synthetic response')})
            steps.append({'op':'click','target':target,'transition':tid});current=action.get('destination')
        else:raise ValueError('Unknown high-level action '+action.tag)
    if task.get('left_hand')!='keyboard' or task.get('mouse_hand')!='right':
        raise ValueError('Bounded synthetic hand setup requires left keyboard/right mouse hand')
    parameters=ParameterSet.parse(policy['parameters'],2)
    if keyboard or task.get('right_hand')=='keyboard':parameters=parameters.with_keyboard_defaults()
    control=copy.deepcopy(policy['control']);control['auxiliary_locations']=[]
    result={'schema_version':2,'id':root.get('id'),'name':root.get('id')+' synthetic mechanism',
        'engine':policy['engine'],'control':control,'parameters':parameters.input_dict(),
        'design':{'id':'synthetic-design','name':design.get('name'),'coordinate_unit':'px',
                  'frames':frames,'transitions':transitions},
        'tasks':[{'id':root.get('id'),'name':task.get('name'),'demonstration':{
            'initial':{'frame':task.get('start_frame'),'mouse':[0,0],'mouse_hand':'right',
                       'hand':task.get('right_hand'),'focus':None},'steps':steps}}]}
    model=Project.from_dict(result)
    observations=root.find('required-observations')
    key='category'
    if observations is None:
        observations=root.find('required_events');key='kind'
    if observations is None:raise ValueError('Declare required observations before execution')
    return model.to_dict(),{'origin':'synthetic','high_level_spec_shared':True,
        'java_model_or_predictions_read':False,'spec_sha256':hashlib.sha256(data).hexdigest(),
        'required_event_categories':[e.get(key) for e in observations],
        'effective_input_sha256':input_hash(model),'initial_mouse_provenance':'fixed2014 source default, not measured',
        'delay_label_provenance':'synthetic schema v1 Java/Python builder contract: synthetic response'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True)
    p.add_argument('--policy-input',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('Preserve earlier inputs; choose new output')
    data,record=construct(a.spec,json.loads(a.policy_input.read_text()));a.out.mkdir(parents=True)
    for name,obj in [('input.json',data),('conversion.json',record)]:
        (a.out/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(record,ensure_ascii=False))
if __name__=='__main__':main()
