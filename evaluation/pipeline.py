"""Per-problem evaluation pipeline inside an isolated run directory.

Stage commands mirror en/rte_en_mp.sh and en/rte_en_mp_any.sh
(tokenizer.sed, C&C, EasyCCG, depccg, semparse.py, prove.py). Every parser
in the preference order runs on every problem and its outcome is recorded;
the aggregated system answer follows the de-facto rule of the legacy
select_answer: the first parser in preference order with a definite answer
(yes/no) wins, otherwise unknown if any parser succeeded.

Isolation: semparse.py and prove.py read several resources relative to the
process working directory (coqlib.v / coqlib.vo / tactics_coq.txt /
replacement.txt / data/interim/verbocean.json). prepare_theory() materialises
all of them in <run_dir>/theory and every stage runs with that directory as
cwd, so runs never touch tracked files and can use different theories
concurrently.
"""
import hashlib
import os
import shutil
import subprocess
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STATUS_OK = 'ok'
STATUS_TOKENIZE_ERROR = 'tokenize_error'
STATUS_PARSE_ERROR = 'parse_error'
STATUS_SEMPARSE_ERROR = 'semparse_error'
STATUS_PROVE_ERROR = 'prove_error'
STATUS_TIMEOUT = 'timeout'

VALID_PREDICTIONS = ('yes', 'no', 'unknown')

TOKENIZE_TIMEOUT = 60
PARSE_TIMEOUT = 300
SEMPARSE_TIMEOUT = 300


class SetupError(RuntimeError):
    """A run could not be prepared; this always aborts the whole run."""


class RunEnvironment(object):
    def __init__(self, run_dir, templates, coqlib, tactics, abduction,
                 timeout, hard_timeout, parsers):
        self.run_dir = os.path.abspath(run_dir)
        self.templates = os.path.abspath(templates)
        self.coqlib = os.path.abspath(coqlib)
        self.tactics = os.path.abspath(tactics)
        self.abduction = abduction
        self.timeout = timeout
        self.hard_timeout = hard_timeout
        self.parsers = tuple(parsers)
        self.theory_dir = os.path.join(self.run_dir, 'theory')
        self.artifacts_dir = os.path.join(self.run_dir, 'artifacts')
        self.cache_dir = os.path.join(REPO_ROOT, 'data', 'interim', 'ccg_cache')
        self.parser_dirs = read_parser_locations(self.parsers)


def read_parser_locations(parsers):
    locations = {}
    for parser in parsers:
        if parser == 'depccg':
            if shutil.which('depccg_en') is None:
                raise SetupError(
                    'depccg_en not found on PATH;'
                    ' is this running inside the container?')
            locations[parser] = ''
            continue
        location_file = os.path.join(REPO_ROOT, 'en', '{0}_location.txt'.format(parser))
        if not os.path.isfile(location_file):
            raise SetupError(
                '{0} not found; in a worktree run infra/setup_worktree.sh,'
                ' in the main checkout create it to point at the parser'
                ' directory inside the container (e.g. /opt/candc-1.00)'
                .format(location_file))
        with open(location_file) as fin:
            parser_dir = fin.read().strip()
        binary = {'candc': os.path.join(parser_dir, 'bin', 'candc'),
                  'easyccg': os.path.join(parser_dir, 'easyccg.jar')}.get(parser)
        if binary is None:
            raise SetupError('unsupported parser: {0}'.format(parser))
        if not os.path.exists(binary):
            raise SetupError(
                '{0} does not exist; is this running inside the container?'.format(binary))
        locations[parser] = parser_dir
    return locations


def prepare_theory(env):
    """Materialise every cwd-relative resource of the legacy pipeline."""
    os.makedirs(env.theory_dir)
    os.makedirs(env.artifacts_dir, exist_ok=True)
    for path, label in ((env.templates, 'templates'), (env.coqlib, 'coqlib'),
                        (env.tactics, 'tactics')):
        if not os.path.isfile(path):
            raise SetupError('{0} file not found: {1}'.format(label, path))
    shutil.copy(env.coqlib, os.path.join(env.theory_dir, 'coqlib.v'))
    shutil.copy(env.tactics, os.path.join(env.theory_dir, 'tactics_coq.txt'))
    replacement = os.path.join(REPO_ROOT, 'replacement.txt')
    if not os.path.isfile(replacement):
        raise SetupError('replacement.txt not found in the repository root')
    shutil.copy(replacement, env.theory_dir)
    verbocean = os.path.join(REPO_ROOT, 'data', 'interim', 'verbocean.json')
    if not os.path.isfile(verbocean):
        raise SetupError(
            '{0} not found; run en/download_dependencies.sh first'.format(verbocean))
    interim = os.path.join(env.theory_dir, 'data', 'interim')
    os.makedirs(interim)
    shutil.copy(verbocean, interim)
    proc = subprocess.run(
        ['coqc', 'coqlib.v'], cwd=env.theory_dir,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise SetupError('coqc failed on {0}:\n{1}'.format(env.coqlib, proc.stdout))


def evaluate_problem(env, problem):
    """Run one problem through the pipeline and return a result record."""
    artifact_dir = os.path.join(env.artifacts_dir, problem['id'])
    os.makedirs(artifact_dir, exist_ok=True)
    result = {
        'id': problem['id'],
        'gold': problem['gold'],
        'prediction': None,
        'status': None,
        'stage': None,
        'parser': None,
        'parsers': {},
        'times': {},
    }

    tok_path = os.path.join(artifact_dir, 'input.tok')
    started = time.monotonic()
    error = _tokenize(problem, artifact_dir, tok_path)
    result['times']['tokenize'] = round(time.monotonic() - started, 3)
    if error:
        result.update(status=error, stage='tokenize')
        return result

    branches = {}
    for parser in env.parsers:
        branch = _run_parser_branch(env, parser, tok_path, artifact_dir, problem['id'])
        branches[parser] = branch
        result['parsers'][parser] = {
            'prediction': branch['prediction'], 'status': branch['status']}
        result['times'][parser] = branch['times']

    chosen = None
    for parser in env.parsers:
        branch = branches[parser]
        if branch['status'] == STATUS_OK and branch['prediction'] in ('yes', 'no'):
            chosen = parser
            break
    if chosen is None:
        for parser in env.parsers:
            if branches[parser]['status'] == STATUS_OK:
                chosen = parser
                break
    if chosen is None:
        chosen = env.parsers[0]
    branch = branches[chosen]
    result.update(prediction=branch['prediction'], status=branch['status'],
                  stage=branch.get('stage'), parser=chosen)
    return result


def _tokenize(problem, artifact_dir, tok_path):
    input_path = os.path.join(artifact_dir, 'input.txt')
    with open(input_path, 'w', encoding='utf-8') as fout:
        for sentence in problem['premises'] + [problem['hypothesis']]:
            fout.write(sentence + '\n')
    tokenizer = os.path.join(REPO_ROOT, 'en', 'tokenizer.sed')
    command = (
        "sed -f '{0}' '{1}' | sed 's/ _ /_/g' | sed 's/[[:space:]]*$//' > '{2}'"
        .format(tokenizer, input_path, tok_path))
    try:
        proc = subprocess.run(['bash', '-c', command], timeout=TOKENIZE_TIMEOUT,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        return STATUS_TIMEOUT
    if proc.returncode != 0 or not os.path.getsize(tok_path):
        return STATUS_TOKENIZE_ERROR
    return None


def _run_parser_branch(env, parser, tok_path, artifact_dir, problem_id):
    branch = {'prediction': None, 'status': None, 'stage': None, 'times': {}}

    started = time.monotonic()
    jigg_path, error = _parse_ccg(env, parser, tok_path, artifact_dir)
    branch['times']['ccg'] = round(time.monotonic() - started, 3)
    if error:
        branch.update(status=error, stage='ccg')
        return branch

    sem_path = os.path.join(artifact_dir, '{0}.sem.xml'.format(parser))
    sem_err = os.path.join(artifact_dir, '{0}.sem.err'.format(parser))
    started = time.monotonic()
    error = _semparse(env, jigg_path, sem_path, sem_err)
    branch['times']['semparse'] = round(time.monotonic() - started, 3)
    if error:
        branch.update(status=error, stage='semparse')
        return branch

    started = time.monotonic()
    prediction, error = _prove(env, sem_path, artifact_dir, parser)
    branch['times']['prove'] = round(time.monotonic() - started, 3)
    if error:
        branch.update(status=error, stage='prove')
        return branch
    branch.update(prediction=prediction, status=STATUS_OK)
    return branch


def _parse_ccg(env, parser, tok_path, artifact_dir):
    """Parse into jigg XML, with a content-addressed cache shared per worktree."""
    with open(tok_path, 'rb') as fin:
        digest = hashlib.sha1(fin.read()).hexdigest()
    cache_dir = os.path.join(env.cache_dir, parser)
    cache_path = os.path.join(cache_dir, '{0}.jigg.xml'.format(digest))
    jigg_path = os.path.join(artifact_dir, '{0}.jigg.xml'.format(parser))
    if os.path.isfile(cache_path) and os.path.getsize(cache_path):
        shutil.copy(cache_path, jigg_path)
        return jigg_path, None

    parser_dir = env.parser_dirs[parser]
    log_path = os.path.join(artifact_dir, '{0}.parse.log'.format(parser))
    if parser == 'candc':
        raw_path = os.path.join(artifact_dir, 'candc.xml')
        command = (
            "'{candc}/bin/candc' --models '{candc}/models' --candc-printer xml"
            " --input '{tok}' > '{raw}' 2> '{log}'"
            " && python '{conv}' '{raw}' > '{jigg}' 2>> '{log}'"
        ).format(candc=parser_dir, tok=tok_path, raw=raw_path, log=log_path,
                 conv=os.path.join(REPO_ROOT, 'en', 'candc2transccg.py'),
                 jigg=jigg_path)
    elif parser == 'easyccg':
        candc_dir = env.parser_dirs.get('candc')
        if candc_dir is None:
            candc_dir = read_parser_locations(('candc',))['candc']
        raw_path = os.path.join(artifact_dir, 'easyccg.out')
        command = (
            "cat '{tok}'"
            " | '{candc}/bin/pos' --model '{candc}/models/pos' 2>/dev/null"
            " | '{candc}/bin/ner' -model '{candc}/models/ner'"
            " -ofmt \"%w|%p|%n \\n\" 2>/dev/null"
            " | java -jar '{easyccg}/easyccg.jar' --model '{easyccg}/model'"
            " -i POSandNERtagged -o extended --nbest 2 > '{raw}' 2> '{log}'"
            " && python '{conv}' '{raw}' '{jigg}' 2>> '{log}'"
        ).format(tok=tok_path, candc=candc_dir, easyccg=parser_dir,
                 raw=raw_path, log=log_path,
                 conv=os.path.join(REPO_ROOT, 'en', 'easyccg2jigg.py'),
                 jigg=jigg_path)
    elif parser == 'depccg':
        candc_dir = env.parser_dirs.get('candc')
        if candc_dir is None:
            candc_dir = read_parser_locations(('candc',))['candc']
        command = (
            "cat '{tok}' | env CANDC='{candc}' depccg_en --input-format raw"
            " --annotator candc --format jigg_xml > '{jigg}' 2> '{log}'"
        ).format(tok=tok_path, candc=candc_dir, jigg=jigg_path, log=log_path)
    else:
        raise SetupError('unsupported parser: {0}'.format(parser))

    try:
        proc = subprocess.run(['bash', '-c', command], timeout=PARSE_TIMEOUT,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        return None, STATUS_TIMEOUT
    if proc.returncode != 0 or not (os.path.isfile(jigg_path)
                                    and os.path.getsize(jigg_path)):
        return None, STATUS_PARSE_ERROR
    os.makedirs(cache_dir, exist_ok=True)
    tmp_path = cache_path + '.tmp.{0}'.format(os.getpid())
    shutil.copy(jigg_path, tmp_path)
    os.replace(tmp_path, cache_path)
    return jigg_path, None


def _semparse(env, jigg_path, sem_path, sem_err):
    command = ['python', os.path.join(REPO_ROOT, 'scripts', 'semparse.py'),
               jigg_path, env.templates, sem_path, '--arbi-types']
    try:
        with open(sem_err, 'w') as errfile:
            proc = subprocess.run(command, cwd=env.theory_dir,
                                  timeout=SEMPARSE_TIMEOUT,
                                  stdout=errfile, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        return STATUS_TIMEOUT
    if proc.returncode != 0 or not (os.path.isfile(sem_path)
                                    and os.path.getsize(sem_path)):
        return STATUS_SEMPARSE_ERROR
    return None


def _prove(env, sem_path, artifact_dir, parser):
    proof_path = os.path.join(artifact_dir, '{0}.proof.xml'.format(parser))
    err_path = os.path.join(artifact_dir, '{0}.prove.err'.format(parser))
    command = ['python', os.path.join(REPO_ROOT, 'scripts', 'prove.py'),
               sem_path,
               '--abduction', env.abduction,
               '--timeout', str(env.timeout),
               '--proof', proof_path]
    try:
        with open(err_path, 'w') as errfile:
            proc = subprocess.run(command, cwd=env.theory_dir,
                                  timeout=env.hard_timeout,
                                  stdout=subprocess.PIPE, stderr=errfile,
                                  text=True)
    except subprocess.TimeoutExpired:
        return None, STATUS_TIMEOUT
    if proc.returncode != 0:
        return None, STATUS_PROVE_ERROR
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    prediction = lines[0] if lines else ''
    if prediction not in VALID_PREDICTIONS:
        with open(os.path.join(artifact_dir, '{0}.prove.out'.format(parser)),
                  'w') as fout:
            fout.write(proc.stdout)
        return None, STATUS_PROVE_ERROR
    return prediction, None
