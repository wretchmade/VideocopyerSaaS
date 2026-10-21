"""Public workflow relationships, derived from each immutable D build document.

Never infer a shot's output from its title, ordering, or a newer generation cache.
"""


def shot_outputs(task, files):
    by_id = {f['id']: f for f in files}
    nodes = {n['id']: n for n in task.get('nodes', [])}
    generations = {n['id']: n for n in task.get('document', {}).get('tasks', [])}
    outputs = []
    for layer in task.get('document', {}).get('layers', []):
        if layer.get('kind') not in {'image', 'video'}:
            continue
        source = layer.get('asset')
        generation = generations.get(source)
        node = nodes.get(source, {})
        if generation:
            digest = node.get('result', {}).get('sha256') if node.get('result') else None
            file = next((f for f in files if digest and f.get('sha256') == digest
                         and (f.get('generated_by') == task['id'] or source in task.get('execution',{}).get('reuse',{}))), None)
            state = node.get('status', 'pending')
        else:
            file = by_id.get(source)
            state = 'ready' if file else 'pending'
        outputs.append({
            'shot_id': layer['id'],
            'node_id': source if generation else None,
            'status': state,
            'output_file_id': file['id'] if file else None,
            'input_file_ids': generation.get('inputs', []) if generation else [],
            'reused': bool(file and file.get('generated_by') and file['generated_by'] != task['id']),
            'provider': generation.get('provider') if generation else None,
            'model': generation.get('model') if generation else None,
        })
    return outputs
