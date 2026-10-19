#!/usr/bin/env python3
"""Build the RSI dashboard with Python's standard library.

Refresh from a trusted viewer snapshot:
  python3 tools/build_rsi.py --snapshot /path/to/data.json
Reproduce from the committed public aggregate data:
  python3 tools/build_rsi.py
Build an isolated directory for local or static hosting:
  python3 tools/build_rsi.py --output-dir dist

Only explicitly selected numeric results and model identifiers are exported.
Raw transcripts, commands, workspaces and filesystem paths are not published.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def export(snapshot):
    raw = snapshot.read_bytes()
    source = json.loads(raw)
    episodes = source['episodes']
    complete = [e for e in episodes if e.get('test_nll') is not None]
    identity_fields = ['core_git', 'train_manifest_sha256', 'task_manifest_sha256',
                       'evaluator_sha256', 'hidden_evaluation']
    for key in identity_fields:
        identities = {json.dumps(e['artifact_identities'][key], sort_keys=True) for e in complete}
        if len(identities) != 1:
            raise ValueError(f'Mixed evaluation identities: {key}')
    # Budget extensions have distinct challenge manifests; enforce identity within each lane.
    lanes = {e['comparison_key']['track_config'] for e in complete}
    for lane in lanes:
        hashes = {e['artifact_identities']['challenge_manifest_sha256'] for e in complete
                  if e['comparison_key']['track_config'] == lane}
        if len(hashes) != 1:
            raise ValueError(f'Mixed challenge identities within {lane}')
    pairs = [(e['model_short'], e['track'], e['comparison_key']['track_config']) for e in episodes]
    if len(set(pairs)) != len(pairs):
        raise ValueError('Select one authorized attempt per model and Track configuration before exporting.')
    rows = []
    for e in episodes:
        candidates = {c['id']: c for c in e['candidates']}
        evaluations = {v['candidate_id']: v for v in e['events']
                       if v['type'] == 'ANALYSIS_EVALUATED'}
        ended = {v['lease_id']: v for v in e['events'] if v['type'] == 'LEASE_ENDED'}
        commits = sorted([v for v in e['events'] if v['type'] == 'CANDIDATE_COMMITTED'],
                         key=lambda v: v['commit_index'])
        points = []
        for event in commits:
            candidate = candidates[event['candidate_id']]
            if candidate.get('val_nll') is None:
                continue
            elapsed = event['elapsed_seconds']
            cost = evaluations.get(candidate['id'], {}).get('cost') or {}
            per_task = cost.get('time_per_task')
            points.append({
                'index': event['commit_index'],
                'candidate_id': candidate['id'].removeprefix('sha256:')[:12],
                'lease': event.get('lease_id', candidate.get('source_lease')),
                'hours': sum(v['used_seconds'] for v in ended.values() if v['elapsed_seconds'] <= elapsed) / 3600,
                'research_hours': elapsed / 3600,
                'nll': candidate['val_nll'],
                'score': candidate.get('analysis_score'),
                'ppl': math.exp(candidate['val_nll']),
                'seconds_per_task': per_task,
                'ms': None if per_task is None else 1000 * per_task,
                'evaluation_seconds': cost.get('candidate_wall_seconds'),
                'tasks_per_second': cost.get('tasks_per_second'),
                'input_tokens_per_second': cost.get('input_tokens_per_second'),
                'task_count': cost.get('task_count'),
                'final': candidate['id'] == e.get('final_candidate_id'),
            })
        ms = e.get('test_time_per_task')
        test_event = next((v for v in e['events'] if v['type'] == 'TEST_EVALUATED'), {})
        test_cost = test_event.get('cost') or {}
        budget = e.get('budget') or {}
        budget_seconds = budget.get('total_seconds')
        if budget_seconds is None and budget.get('max_leases') and budget.get('lease_seconds'):
            budget_seconds = budget['max_leases'] * budget['lease_seconds']
        rows.append({
            'model': e['model_short'], 'track': e['track'],
            'track_config': e['comparison_key']['track_config'],
            'comparison_key': e['comparison_key'],
            'challenge_manifest_sha256': e['artifact_identities']['challenge_manifest_sha256'],
            'max_leases': budget.get('max_leases'),
            'status': e['status'], 'outcome': e.get('outcome'),
            'test_nll': e.get('test_nll'), 'score': e.get('test_score'),
            'seconds_per_task': ms,
            'ms': None if ms is None else 1000 * ms,
            'ppl': None if e.get('test_nll') is None else math.exp(e['test_nll']),
            'evaluation_seconds': test_cost.get('candidate_wall_seconds'),
            'tasks_per_second': test_cost.get('tasks_per_second'),
            'input_tokens_per_second': test_cost.get('input_tokens_per_second'),
            'task_count': test_cost.get('task_count'),
            'budget_hours': None if budget_seconds is None else budget_seconds / 3600,
            'lease_hours': e['timing'].get('training_lease_seconds', 0) / 3600,
            'research_hours': e['timing'].get('official_elapsed_seconds', 0) / 3600,
            'leases': e['leases_used'], 'candidates': len(candidates),
            'first_analysis': e.get('first_val'), 'final_analysis': e.get('final_val'),
            'reasoning_effort': e.get('reasoning_effort'), 'points': points,
            'reasoning_tokens': (e.get('tokens') or {}).get('reasoning'),
            'output_tokens': (e.get('tokens') or {}).get('output'),
            'total_tokens': (e.get('tokens') or {}).get('total'),
            'agent_turns': (e.get('transcript_summary') or {}).get('turns'),
        })
    return {
        'schema_version': 3, 'generated_at': source['generated_at'],
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'core_revision': complete[0]['repo_commit'] if complete else None,
        'runtime': '1 × NVIDIA H200 SXM 141GB', 'task': 'lm-pretrain',
        'selection': 'Latest authorized attempt per model/Track configuration; B6 and B12 retained separately; previous failed attempts excluded.',
        'excluded_attempts': [
            {'model': v['model'], 'track': v['track'], 'outcome': v['outcome']}
            for v in source.get('excluded_attempts', [])
        ],
        'preview': True, 'rows': rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--output-dir', type=Path, default=ROOT,
                        help='Static output root (default: repository root).')
    args = parser.parse_args()
    site_root = args.output_dir.resolve()
    output = site_root / 'rsi'
    if args.snapshot:
        data = export(args.snapshot)
    else:
        data = json.loads((ROOT / 'rsi' / 'data.json').read_text())
    payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    # Catch accidental private paths before writing anything to the public site.
    for token in ['/mnt/', '/home/', '/media/', '/ibex/', 'api_key', 'Authorization', 'agent.stdout']:
        if token in payload:
            raise ValueError(f'Unexpected private information in public aggregates: {token}')
    template = (ROOT / 'tools' / 'rsi-template.html').read_text()
    if template.count('__RSI_DATA__') != 1:
        raise ValueError('The template must contain exactly one data placeholder.')
    if template.count('__I18N_DATA__') != 1:
        raise ValueError('The template must contain exactly one translation placeholder.')
    translations = json.loads((ROOT / 'tools' / 'translations.json').read_text())
    page = template.replace('__RSI_DATA__', payload.replace('<', '\\u003c'))
    page = page.replace('__I18N_DATA__', json.dumps(translations, ensure_ascii=False).replace('<', '\\u003c'))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'data.json').write_text(payload + '\n')
    (output / 'index.html').write_text(page.replace('__DATA_URL__', 'data.json'))
    (site_root / 'index.html').write_text(page.replace('__DATA_URL__', 'rsi/data.json'))
    (site_root / '.nojekyll').touch()
    print(f"Built latest-only dashboard: {len(data['rows'])} runs, snapshot {data['generated_at']}")


if __name__ == '__main__':
    main()
