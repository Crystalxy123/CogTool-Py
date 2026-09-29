"""Re-execute frozen Python input conversion for the two bounded phone tasks.

This is only the P-P/P-L path. The independent Java process never consumes these
files. Existing extractors are reused unchanged; no cached steps/results read.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.convert_phone_case import MODEL_PATH, read_phone, extract_case, construct_candidate
from scripts.convert_phone_additional import InputGraph, scene, extract
from cogtool_py.io import load_project, input_hash, implementation_fingerprint


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def prepare(source_model,policy_input,out):
    source_model,policy_input,out=map(lambda p:Path(p).resolve(),(source_model,policy_input,out))
    if out.exists():raise FileExistsError('Input extraction evidence already exists')
    # The preserved NP-B2 extractor intentionally has a fixed official source.
    # Require exact input bytes, and disclose that concrete read path; never
    # silently substitute a different supplied model.
    if sha(source_model)!=sha(MODEL_PATH):raise ValueError('Frozen NP-B2 extractor supports only the byte-identical official phone archive')
    policy=json.loads(policy_input.read_text());before=implementation_fingerprint()
    if policy['engine']!='cogtool_control_prefix_experimental' or policy['control']['execution_scope']!='integrated_task':raise ValueError('Explicit frozen integrated policy required')
    graph,source=read_phone(source_model);extraction=extract_case(graph,'NP-B1')
    candidate,mappings,blockers=construct_candidate(graph,extraction,deepcopy(policy['parameters']))
    if blockers:raise ValueError('Frozen NP-B1 conversion has blockers')
    guard=InputGraph(graph.root)
    frame,aux,groups,scene_map=scene(guard,guard.index[extraction['start_frame_object_id']])
    candidate['engine']=policy['engine'];candidate['control']=deepcopy(policy['control']);candidate['control']['auxiliary_locations']=aux
    if candidate['design']['frames']!=[frame]:raise ValueError('Frozen extractor scene paths disagree')
    additional,additional_extraction,additional_mappings,accesses=extract(policy_input)
    out.mkdir(parents=True)
    for case,data,e,m,a in [('NP-B1',candidate,extraction,mappings+scene_map,guard.accesses),('NP-B2',additional,additional_extraction,additional_mappings,accesses)]:
        folder=out/case;folder.mkdir();write(folder/'input.json',data);write(folder/'extraction.json',e);write(folder/'field_mapping.json',m);write(folder/'field_accesses.json',a)
    summary={'source_model_requested':str(source_model),'source_model_sha256':sha(source_model),'source_model_read_by_frozen_np_b2':str(MODEL_PATH),'same_source_bytes':True,'policy_input':str(policy_input),'policy_sha256':sha(policy_input),'inputs':{case:{'file_sha256':sha(out/case/'input.json'),'content_sha256':input_hash(load_project(out/case/'input.json'))} for case in ('NP-B1','NP-B2')},'implementation':before,'implementation_unchanged':before==implementation_fingerprint(),'reference_answers_read':False,'not_part_of_Java_input_path':True,'wrapper_sha256':sha(__file__)}
    write(out/'summary.json',summary);return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-model',type=Path,required=True);p.add_argument('--policy-input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(prepare(a.source_model,a.policy_input,a.out),indent=2))
if __name__=='__main__':main()
