"""Workflow lineage must never present another revision's output as this build's."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from local.workflow import shot_outputs


def test_generated_output_requires_same_task_and_digest():
    task = {'id': 'build1', 'document': {
        'tasks': [{'id': 'gen_s1', 'inputs': ['reference'], 'provider': 'ark', 'model': 'seedance-2'}],
        'layers': [{'id': 's1', 'kind': 'video', 'asset': 'gen_s1'},
                   {'id': 'sub_s1', 'kind': 'text', 'text': 'subtitle'}]},
        'nodes': [{'id': 'gen_s1', 'status': 'succeeded', 'result': {'sha256': 'abc', 'path': 'private'}}]}
    files = [{'id': 'wrong-build', 'sha256': 'abc', 'generated_by': 'build2'},
             {'id': 'wrong-bytes', 'sha256': 'xyz', 'generated_by': 'build1'},
             {'id': 'right', 'sha256': 'abc', 'generated_by': 'build1'}]
    row, = shot_outputs(task, files)
    assert row['output_file_id'] == 'right'
    assert row['input_file_ids'] == ['reference']
    assert row['status'] == 'succeeded'
    assert row['reused'] is False
    assert 'private' not in str(row)
    assert shot_outputs(task, files[:2])[0]['output_file_id'] is None


def test_reused_output_comes_from_bound_document_not_newer_cache():
    task = {'id': 'build2', 'document': {'tasks': [], 'layers': [
        {'id': 's1', 'kind': 'video', 'asset': 'old-file'}]}}
    files = [{'id': 'old-file', 'generated_by': 'build1'}, {'id': 'new-file', 'generated_by': 'build3'}]
    row, = shot_outputs(task, files)
    assert row['output_file_id'] == 'old-file'
    assert row['reused'] is True
    assert row['node_id'] is None


def test_pending_generation_does_not_show_reference_as_output():
    task = {'id': 'build1', 'document': {
        'tasks': [{'id': 'gen_s1', 'inputs': ['reference']}],
        'layers': [{'id': 's1', 'kind': 'video', 'asset': 'gen_s1'}]}}
    row, = shot_outputs(task, [{'id': 'reference', 'sha256': 'abc'}])
    assert row['output_file_id'] is None
    assert row['status'] == 'pending'


def test_uploaded_asset_is_ready_without_a_generation_node():
    task = {'id': 'build1', 'document': {'layers': [{'id': 's1', 'kind': 'image', 'asset': 'upload'}]}}
    row, = shot_outputs(task, [{'id': 'upload'}])
    assert row['output_file_id'] == 'upload'
    assert row['status'] == 'ready'
    assert row['reused'] is False
