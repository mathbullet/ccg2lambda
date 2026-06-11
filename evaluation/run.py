"""Evaluation driver: select problems, evaluate them in an isolated run
directory, and write machine-readable results.

Usage (inside the container):
    python -m evaluation.run \
        --problems data/processed/sick/trial.jsonl \
        --sample 50 --seed 7 \
        --templates en/semantic_templates_en_event.yaml

Outputs under results/runs/<run_id>/:
    run.json        config, resource hashes, git state, timings
    problems.jsonl  the evaluated subset (for exact epoch-to-epoch comparison)
    results.jsonl   one record per problem (prediction, gold, status, times)
    score.json      accuracy, confusion matrix with an explicit error column
    artifacts/<id>/ sem.xml, proof.xml, stderr of every stage
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import subprocess
import sys
import threading
import time

from evaluation import pipeline, schema, scoring, selection


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fin:
        for chunk in iter(lambda: fin.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def git_state():
    try:
        commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=pipeline.REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(
            ['git', 'status', '--porcelain'], cwd=pipeline.REPO_ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=True).stdout.strip())
        return {'commit': commit, 'dirty': dirty}
    except (OSError, subprocess.CalledProcessError):
        return {'commit': None, 'dirty': None}


def make_run_dir(output_root, git):
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    commit = (git['commit'] or 'nogit')[:8]
    base = os.path.join(output_root, '{0}-{1}'.format(stamp, commit))
    run_dir = base
    suffix = 2
    while os.path.exists(run_dir):
        run_dir = '{0}-{1}'.format(base, suffix)
        suffix += 1
    os.makedirs(run_dir)
    return run_dir


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Evaluate a problem set with the ccg2lambda pipeline.')
    parser.add_argument('--problems', required=True,
                        help='canonical problem set (JSONL)')
    parser.add_argument('--ids', help='comma-separated problem ids to evaluate')
    parser.add_argument('--ids-file', help='file with one problem id per line')
    parser.add_argument('--sample', type=int,
                        help='random subset size (requires --seed)')
    parser.add_argument('--seed', type=int, help='random seed for --sample')
    parser.add_argument('--templates', required=True,
                        help='semantic templates YAML')
    parser.add_argument('--coqlib', default='en/coqlib_sick.v',
                        help='Coq static library source')
    parser.add_argument('--tactics', default='en/tactics_coq_sick.txt',
                        help='Coq tactics file')
    parser.add_argument('--abduction', choices=['no', 'spsa'], default='spsa',
                        help="axiom abduction ('naive' is broken upstream and"
                             ' not offered)')
    parser.add_argument('--timeout', type=int, default=100,
                        help='timeout in seconds for each coqtop call')
    parser.add_argument('--hard-timeout', type=int, default=None,
                        help='wall-clock cap per prove stage'
                             ' (default: 3x --timeout)')
    parser.add_argument('--jobs', type=int, default=1,
                        help='number of problems evaluated in parallel')
    parser.add_argument('--parsers', default='candc,easyccg,depccg',
                        help='comma-separated parser preference order;'
                             ' every parser runs on every problem')
    parser.add_argument('--output-root', default='results/runs')
    args = parser.parse_args(argv)
    if args.ids and args.ids_file:
        parser.error('--ids and --ids-file are mutually exclusive')
    if args.hard_timeout is None:
        args.hard_timeout = 3 * args.timeout
    return args


def main(argv=None):
    args = parse_args(argv)

    problems = schema.read_problems(args.problems)
    ids = None
    if args.ids:
        ids = [i.strip() for i in args.ids.split(',') if i.strip()]
    elif args.ids_file:
        with open(args.ids_file) as fin:
            ids = [line.strip() for line in fin if line.strip()]
    try:
        selected = selection.select(problems, ids=ids, sample=args.sample,
                                    seed=args.seed)
    except selection.SelectionError as exc:
        print('ERROR: {0}'.format(exc), file=sys.stderr)
        return 2
    if not selected:
        print('ERROR: no problems selected', file=sys.stderr)
        return 2

    git = git_state()
    run_dir = make_run_dir(args.output_root, git)
    try:
        env = pipeline.RunEnvironment(
            run_dir=run_dir, templates=args.templates, coqlib=args.coqlib,
            tactics=args.tactics, abduction=args.abduction, timeout=args.timeout,
            hard_timeout=args.hard_timeout,
            parsers=[p.strip() for p in args.parsers.split(',') if p.strip()])
        pipeline.prepare_theory(env)
    except pipeline.SetupError as exc:
        print('ERROR: {0}'.format(exc), file=sys.stderr)
        return 2

    schema.write_problems(os.path.join(run_dir, 'problems.jsonl'), selected)
    manifest = {
        'started_at': datetime.datetime.utcnow().isoformat() + 'Z',
        'argv': argv if argv is not None else sys.argv[1:],
        'git': git,
        'problems_file': {'path': args.problems, 'sha256': sha256(args.problems)},
        'resources': {
            'templates': {'path': args.templates, 'sha256': sha256(env.templates)},
            'coqlib': {'path': args.coqlib, 'sha256': sha256(env.coqlib)},
            'tactics': {'path': args.tactics, 'sha256': sha256(env.tactics)},
        },
        'config': {
            'abduction': args.abduction, 'timeout': args.timeout,
            'hard_timeout': args.hard_timeout, 'jobs': args.jobs,
            'parsers': list(env.parsers),
            'selection': {'ids': ids, 'sample': args.sample, 'seed': args.seed},
        },
    }
    with open(os.path.join(run_dir, 'run.json'), 'w') as fout:
        json.dump(manifest, fout, indent=2)

    print('run directory: {0}'.format(run_dir))
    results = []
    write_lock = threading.Lock()
    results_path = os.path.join(run_dir, 'results.jsonl')
    started = time.monotonic()

    def evaluate_and_record(problem):
        result = pipeline.evaluate_problem(env, problem)
        with write_lock:
            results.append(result)
            with open(results_path, 'a') as fout:
                fout.write(json.dumps(result) + '\n')
            print('[{0}/{1}] {2}: {3} ({4})'.format(
                len(results), len(selected), result['id'],
                result['prediction'] or '-', result['status']))
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(evaluate_and_record, p) for p in selected]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    summary = scoring.score(results, parsers=env.parsers)
    summary['wall_clock_seconds'] = round(time.monotonic() - started, 1)
    with open(os.path.join(run_dir, 'score.json'), 'w') as fout:
        json.dump(summary, fout, indent=2)
    print('accuracy: {0:.4f} ({1}/{2}), error rate: {3:.4f}'.format(
        summary['accuracy'], summary['correct'], summary['total'],
        summary['error_rate']))
    for name in env.parsers:
        stats = summary['parser_accuracy'][name]
        print('  {0}: {1:.4f} ({2}/{3})'.format(
            name, stats['accuracy'], stats['correct'], summary['total']))
    print('  oracle (any parser correct): {0:.4f} ({1}/{2})'.format(
        summary['oracle']['accuracy'], summary['oracle']['correct'],
        summary['total']))
    print('score: {0}'.format(os.path.join(run_dir, 'score.json')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
