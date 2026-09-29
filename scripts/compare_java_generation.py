"""Read-only, ordered structural diagnostics for Java and Python Lisp exports.

This bounded syntax reader does not evaluate Lisp or infer semantic equality of
arbitrary programs. It keeps model/prod/scene definition order; group renaming
requires a unique geometry-and-member witness. Raw exports are never rewritten.
"""
from __future__ import annotations
import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def tokens(text):
    i=0
    while i<len(text):
        c=text[i]
        if c.isspace():i+=1;continue
        if c==';':
            end=text.find('\n',i);i=len(text) if end<0 else end+1;continue
        if text.startswith('#|',i):
            depth=1;i+=2
            while depth and i<len(text):
                if text.startswith('#|',i):depth+=1;i+=2
                elif text.startswith('|#',i):depth-=1;i+=2
                else:i+=1
            if depth:raise ValueError('Unterminated block comment')
            continue
        if c in '()':yield c;i+=1;continue
        if c in "'`" or c==',' or text.startswith("#'",i):
            if text.startswith("#'",i):yield '#quote';i+=2
            elif text.startswith(',@',i):yield ',@';i+=2
            else:yield c;i+=1
            continue
        if c=='"':
            i+=1;value=[]
            while i<len(text) and text[i]!='"':
                if text[i]=='\\':
                    i+=1
                    if i==len(text):raise ValueError('Unterminated string escape')
                value.append(text[i]);i+=1
            if i==len(text):raise ValueError('Unterminated string')
            i+=1;yield {'string':''.join(value)};continue
        if text.startswith('#\\',i):
            start=i;i+=2
            if i<len(text):i+=1
            while i<len(text) and not text[i].isspace() and text[i] not in '()':i+=1
            yield {'character':text[start:i]};continue
        if c=='|':
            start=i;i+=1
            while i<len(text):
                if text[i]=='\\':i+=2;continue
                if text[i]=='|':break
                i+=1
            if i==len(text):raise ValueError('Unterminated escaped symbol')
            i+=1;yield {'escaped_symbol':text[start:i]};continue
        start=i
        while i<len(text) and not text[i].isspace() and text[i] not in '();"':i+=1
        raw=text[start:i]
        if not raw:raise ValueError(f'Unsupported token at {start}')
        if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdDfFlL][+-]?\d+)?',raw):
            try:yield {'number':str(Decimal(re.sub('[dDfFlL]','e',raw)).normalize())}
            except InvalidOperation:raise ValueError('Invalid numeric atom '+raw)
        else:yield raw.lower()


def parse(text):
    stream=iter(tokens(text));prefix={"'":'quote','#quote':'function','`':'backquote',',':'unquote',',@':'unquote-splicing'}
    def item(token):
        if isinstance(token,str) and token in prefix:
            try:return [prefix[token],item(next(stream))]
            except StopIteration:raise ValueError('Dangling quote')
        if token==')':raise ValueError('Unexpected closing parenthesis')
        if token=='(':
            result=[]
            for child in stream:
                if child==')':return result
                result.append(item(child))
            raise ValueError('Unclosed list')
        return token
    return [item(t) for t in stream]


def walk(value):
    if isinstance(value,list):
        yield value
        for child in value:yield from walk(child)


def head(form,name):return isinstance(form,list) and bool(form) and form[0]==name

def literal(value):
    if isinstance(value,dict):return value.get('string',value.get('number',value))
    if head(value,'quote'):return literal(value[1])
    if isinstance(value,list):return [literal(v) for v in value]
    return value


def plist(form):
    result=[];i=2
    while i<len(form):
        key=form[i]
        if not isinstance(key,str) or not key.startswith(':') or i+1>=len(form):
            raise ValueError('Not a literal make-instance keyword sequence')
        result.append([key,form[i+1]]);i+=2
    return result


def props(instance):return {key:literal(value) for key,value in instance['properties']}


def snapshot(path):
    forms=parse(Path(path).read_text());models=[f for f in forms if head(f,'define-cogtool-model')]
    if len(models)!=1:raise ValueError('Expected exactly one actual model definition')
    scenes=[f for f in forms if head(f,'defun') and (f[1]=='define-design' or str(f[1]).startswith('cogtool-frame-fn-'))]
    instances=[]
    for scene in scenes:
        for f in walk(scene):
            if head(f,'make-instance') and len(f)>1 and literal(f[1]) in ('cogtool-widget','cogtool-frame','cogtool-transition'):
                instances.append({'class':literal(f[1]),'properties':plist(f),'definition_function':scene[1]})
    model=models[0]
    return {'file':str(path),'sha256':sha(path),'reader_kind':'bounded_syntax_only_not_lisp_evaluation',
        'model_options':model[1],'ordered_model_forms':model[2:],
        'ordered_productions':[f for f in model[2:] if head(f,'p')],
        'ordered_spp':[f for f in model[2:] if head(f,'spp')],
        'ordered_scene_instances':instances,
        'ordered_model_parameter_forms':[f for f in forms if isinstance(f,list) and f and f[0] in ('setq','setf','defparameter') and any(isinstance(x,str) and 'parameter' in x for x in f[1:2])],
        'run_wrapper_calls':[f for f in forms if any(head(x,'cogtool-run-model') for x in walk(f))],
        'normalization':'comments/whitespace, symbol case, quote syntax, exact decimal representation only; no global sorting or rule deletion'}


def group_map(left,right):
    def signatures(data):
        allwidgets=[props(x) for x in data['ordered_scene_instances'] if x['class']=='cogtool-widget']
        groups=[x for x in allwidgets if x.get(':wtype')=='cogtool-group'];result={}
        for group in groups:
            members=[w.get(':name') for w in allwidgets if group[':name'] in (w.get(':member-of-groups') or [])]
            signature=json.dumps([[group.get(k) for k in (':x',':y',':width',':height')],members])
            result.setdefault(signature,[]).append(group[':name'])
        return result
    l,r=signatures(left),signatures(right);mapping={};evidence=[]
    for signature,names in l.items():
        rightnames=r.get(signature,[])
        if len(names)==len(rightnames)==1:
            mapping[names[0]]=rightnames[0];evidence.append({'java':names[0],'python':rightnames[0],'basis':json.loads(signature),'status':'unique_geometry_and_ordered_members'})
        else:evidence.append({'java':names,'python':rightnames,'basis':json.loads(signature),'status':'unmapped_or_ambiguous'})
    return mapping,evidence


def rename(value,mapping):
    if isinstance(value,dict) and set(value)=={'string'}:return {'string':mapping.get(value['string'],value['string'])}
    if isinstance(value,list):return [rename(v,mapping) for v in value]
    if isinstance(value,dict):return {k:rename(v,mapping) for k,v in value.items()}
    return value


def differences(a,b,path='$'):
    if type(a)!=type(b):return [{'path':path,'java':a,'python':b}]
    if isinstance(a,dict):
        out=[]
        for k in dict.fromkeys([*a,*b]):
            if k not in a or k not in b:out.append({'path':path+'.'+k,'java':a.get(k),'python':b.get(k),'missing_side':'java' if k not in a else 'python'})
            else:out.extend(differences(a[k],b[k],path+'.'+k))
        return out
    if isinstance(a,list):
        out=[]
        for i in range(max(len(a),len(b))):
            if i>=len(a) or i>=len(b):out.append({'path':f'{path}[{i}]','java':a[i] if i<len(a) else None,'python':b[i] if i<len(b) else None,'missing_side':'java' if i>=len(a) else 'python'})
            else:out.extend(differences(a[i],b[i],f'{path}[{i}]'))
        return out
    return [] if a==b else [{'path':path,'java':a,'python':b}]


def compare(java,python,out):
    out=Path(out)
    if out.exists():raise FileExistsError('Preserve first comparison; choose a new directory')
    left,right=snapshot(java),snapshot(python);mapping,witness=group_map(left,right);normalized=rename(left,mapping)
    # Function organization differs; compare actual instance order and properties,
    # retaining transition exports separately so absent Java data stays visible.
    def scene(data,kind):return [dict(properties=x['properties'],class_name=x['class']) for x in data['ordered_scene_instances'] if x['class']==kind]
    # Comparing the two filtered subsequences alone loses their interleaving:
    # an SPP before its production must remain distinguishable from one after it.
    # Keep every body form, including initialization and non-production forms.
    compared={'ordered_model_forms':(normalized['ordered_model_forms'],right['ordered_model_forms']),
              'productions':(normalized['ordered_productions'],right['ordered_productions']),
              'spp':(normalized['ordered_spp'],right['ordered_spp']),
              'model_options':(normalized['model_options'],right['model_options']),
              'scene_widgets_and_groups':(scene(normalized,'cogtool-widget'),scene(right,'cogtool-widget')),
              'scene_frames':(scene(normalized,'cogtool-frame'),scene(right,'cogtool-frame')),
              'exported_transitions':(scene(normalized,'cogtool-transition'),scene(right,'cogtool-transition'))}
    diff={k:differences(*v) for k,v in compared.items()}
    def named_properties(data):
        result={}
        for instance in data['ordered_scene_instances']:
            if instance['class']!='cogtool-widget':continue
            name=props(instance).get(':name');fields={}
            if name in result:raise ValueError('Ambiguous scene instance name '+str(name))
            for key,value in instance['properties']:fields.setdefault(key,[]).append(value)
            result[name]=fields
        return result
    named_java,named_python=named_properties(normalized),named_properties(right)
    named_diffs=[]
    for name in dict.fromkeys([*named_java,*named_python]):
        named_diffs.append({'name':name,'java_present':name in named_java,'python_present':name in named_python,
            'field_differences':differences(named_java.get(name),named_python.get(name))})
    summary={'comparison_kind':'ordered_structure_diagnostic','java_sha256':left['sha256'],'python_sha256':right['sha256'],
        'layers':{k:{'status':'structurally_equal' if not d else 'different','difference_count':len(d),'first_difference':d[0] if d else None} for k,d in diff.items()},
        'groups_mapping':witness,'all_semantic_model_equivalence':None,'parameter_equivalence':'requires actual runtime parameter printouts; explicit assignment vs inherited default not blindly normalized',
        'named_scene_comparison':'matched by exact display name after witnessed group-only bijection; duplicate property values retained; separate definition-order comparison remains authoritative',
        'definition_order_preserved':True,'reader_and_comparator_sha256':sha(__file__)}
    out.mkdir(parents=True);write(out/'java_structure.json',left);write(out/'python_structure.json',right);write(out/'group_mapping.json',witness);write(out/'differences.json',diff);write(out/'named_scene_field_differences.json',named_diffs);write(out/'summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--java',type=Path,required=True);p.add_argument('--python',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(compare(a.java,a.python,a.out),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
