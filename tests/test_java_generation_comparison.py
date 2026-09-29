"""Ordered export diagnostics: do not turn parsing conveniences into equivalence."""
import json

from scripts.compare_java_generation import compare, parse, differences, group_map


def test_reader_ignores_comments_but_preserves_display_strings_and_order():
    a=parse('; comment\n(p A ; another\n "Mixed ; (Text)" 1.0) #| outer #| nested |# |# (p B 2)')
    b=parse('(p a "Mixed ; (Text)" 1) (p b 2.0)')
    assert a==b
    assert differences(a,list(reversed(b)))
    assert differences(a,parse('(p a "mixed ; (text)" 1) (p b 2)'))


def test_missing_rule_or_changed_numeric_value_cannot_disappear():
    source=parse('(p start 0) (p move 0.05) (p stop 0)')
    assert differences(source,parse('(p start 0) (p move 0.051) (p stop 0)'))
    assert differences(source,parse('(p start 0) (p stop 0)'))
    assert not differences(source,parse('(p START 0.0) (p MOVE 5e-2) (p STOP 0)'))


def test_group_bijection_requires_unique_geometry_and_membership_witness():
    def scene(group_names):
        def field(k,v):return [k,{'string':v}]
        objects=[{'class':'cogtool-widget','properties':[field(':name','Visible item'),[':member-of-groups',['quote',[{'string':group_names[0]}]]]]}]
        objects += [{'class':'cogtool-widget','properties':[field(':name',name),[':wtype',['quote','cogtool-group']],*[field(k,v) for k,v in zip((':x',':y',':width',':height'),('0','0','10','10'))]]} for name in group_names]
        return {'ordered_scene_instances':objects}
    mapping,evidence=group_map(scene(['GROUP [i1]']),scene(['saved_group']))
    assert mapping=={'GROUP [i1]':'saved_group'}
    assert evidence[0]['status']=='unique_geometry_and_ordered_members'
    left=scene(['A','B','C']);right=scene(['X','Y','Z'])
    mapping,evidence=group_map(left,right)
    assert mapping=={'A':'X'}
    assert any(e['status']=='unmapped_or_ambiguous' for e in evidence)


def test_production_spp_interleaving_is_compared_without_sorting(tmp_path):
    source = '''(define-cogtool-model (:start-with-mouse t :timeout 10)
      (p find-1 =goal> isa klm state 1 ==> =goal> state 2)
      (spp find-1 :u -1.0)
      (p move-2 =goal> isa klm state 2 ==> =goal> state 3))'''
    moved = source.replace('(spp find-1 :u -1.0)', '').replace(
        '(p find-1', '(spp find-1 :u -1.0)\n(p find-1', 1)
    java = tmp_path / 'java.lisp'
    python = tmp_path / 'python.lisp'
    java.write_text(source)
    python.write_text(source)
    equal = compare(java, python, tmp_path / 'equal')
    assert equal['layers']['ordered_model_forms']['status'] == 'structurally_equal'

    python.write_text(moved)
    result = compare(java, python, tmp_path / 'reordered')
    assert result['layers']['productions']['status'] == 'structurally_equal'
    assert result['layers']['spp']['status'] == 'structurally_equal'
    assert result['layers']['ordered_model_forms']['status'] == 'different'
    differences_saved = json.loads((tmp_path / 'reordered/differences.json').read_text())
    assert differences_saved['ordered_model_forms'][0] == {
        'path': '$[0][0]', 'java': 'p', 'python': 'spp'}
    assert result['all_semantic_model_equivalence'] is None


def test_nonproduction_model_initialization_is_not_omitted(tmp_path):
    java = tmp_path / 'java.lisp'
    python = tmp_path / 'python.lisp'
    java.write_text('''(define-cogtool-model (:timeout 10)
      (sgp :dat 0.05) (p stop =goal> isa klm ==> +goal> isa stop))''')
    python.write_text(java.read_text().replace(':dat 0.05', ':dat 0.10'))
    result = compare(java, python, tmp_path / 'comparison')
    assert result['layers']['productions']['status'] == 'structurally_equal'
    assert result['layers']['spp']['status'] == 'structurally_equal'
    assert result['layers']['ordered_model_forms']['status'] == 'different'
