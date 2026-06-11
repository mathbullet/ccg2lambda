"""SICK dataset adapter: convert the SemEval TSV into canonical problem sets.

Usage:
    python -m evaluation.datasets.sick \
        [--input data/raw/SICK.semeval.txt] [--outdir data/processed/sick]

Label mapping and sentence normalisation follow the awk extraction that
en/eacl2017exp.sh embedded (lines 48-66 at the time this adapter was written):
ENTAILMENT->yes, CONTRADICTION->no, NEUTRAL->unknown; sentences carry exactly
one trailing period.
"""
import argparse
import os

from evaluation import schema

LABEL_MAP = {'ENTAILMENT': 'yes', 'CONTRADICTION': 'no', 'NEUTRAL': 'unknown'}
SPLITS = ('train', 'trial', 'test')
REQUIRED_COLUMNS = (
    'pair_ID', 'sentence_A', 'sentence_B', 'entailment_judgment', 'SemEval_set')


class SickFormatError(ValueError):
    pass


def normalize_sentence(text):
    text = text.strip()
    if text.endswith('.'):
        text = text[:-1]
    return text + '.'


def convert(lines):
    """Yield (split, problem) pairs from SICK.semeval.txt lines, header first."""
    try:
        header = next(iter(lines)) if not hasattr(lines, '__next__') else next(lines)
    except StopIteration:
        raise SickFormatError('input is empty')
    columns = header.rstrip('\n').split('\t')
    indices = {}
    for name in REQUIRED_COLUMNS:
        if name not in columns:
            raise SickFormatError('missing column in header: {0}'.format(name))
        indices[name] = columns.index(name)
    for lineno, line in enumerate(lines, start=2):
        if not line.strip():
            continue
        fields = line.rstrip('\n').split('\t')
        if len(fields) < len(columns):
            raise SickFormatError(
                'line {0}: expected {1} columns, got {2}'.format(
                    lineno, len(columns), len(fields)))
        judgment = fields[indices['entailment_judgment']]
        if judgment not in LABEL_MAP:
            raise SickFormatError(
                'line {0}: unknown entailment judgment {1!r}'.format(lineno, judgment))
        split = fields[indices['SemEval_set']].lower()
        if split not in SPLITS:
            raise SickFormatError(
                'line {0}: unknown SemEval_set {1!r}'.format(lineno, split))
        pair_id = fields[indices['pair_ID']]
        yield split, {
            'id': 'sick_{0}_{1}'.format(split, pair_id),
            'premises': [normalize_sentence(fields[indices['sentence_A']])],
            'hypothesis': normalize_sentence(fields[indices['sentence_B']]),
            'gold': LABEL_MAP[judgment],
            'meta': {'source': 'SICK', 'split': split, 'pair_id': pair_id},
        }


def convert_file(input_path):
    problems = {split: [] for split in SPLITS}
    with open(input_path, encoding='utf-8') as fin:
        for split, problem in convert(fin):
            problems[split].append(problem)
    for split in SPLITS:
        problems[split].sort(key=lambda p: int(p['meta']['pair_id']))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Convert SICK.semeval.txt into canonical problem sets.')
    parser.add_argument('--input', default='data/raw/SICK.semeval.txt')
    parser.add_argument('--outdir', default='data/processed/sick')
    args = parser.parse_args(argv)
    if not os.path.isfile(args.input):
        parser.error(
            '{0} not found; run en/download_dependencies.sh first'.format(args.input))
    problems = convert_file(args.input)
    os.makedirs(args.outdir, exist_ok=True)
    for split in SPLITS:
        out_path = os.path.join(args.outdir, '{0}.jsonl'.format(split))
        schema.write_problems(out_path, problems[split])
        print('{0}: {1} problems -> {2}'.format(split, len(problems[split]), out_path))


if __name__ == '__main__':
    main()
