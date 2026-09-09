"""Canonical problem schema shared by dataset adapters and the evaluation driver.

A problem set is a JSON Lines file; each line is one problem:

    {"id": "sick_train_23",
     "premises": ["A man is walking."],
     "hypothesis": "A person is walking.",
     "gold": "yes",
     "meta": {"source": "SICK", "split": "train", "pair_id": "23"}}

The driver consumes only this format and never knows dataset names.
"""
import json
import re

GOLD_LABELS = ('yes', 'no', 'unknown')

_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]+$')


class SchemaError(ValueError):
    pass


def validate_problem(obj, lineno=None):
    where = ' (line {0})'.format(lineno) if lineno is not None else ''
    if not isinstance(obj, dict):
        raise SchemaError('problem must be a JSON object{0}'.format(where))
    pid = obj.get('id')
    if not isinstance(pid, str) or not _ID_PATTERN.match(pid):
        raise SchemaError(
            'invalid id {0!r}; ids must match {1}{2}'.format(
                pid, _ID_PATTERN.pattern, where))
    premises = obj.get('premises')
    if (not isinstance(premises, list) or not premises
            or not all(isinstance(p, str) and p.strip() for p in premises)):
        raise SchemaError(
            'premises of {0} must be a non-empty list of non-empty strings{1}'.format(
                pid, where))
    hypothesis = obj.get('hypothesis')
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise SchemaError(
            'hypothesis of {0} must be a non-empty string{1}'.format(pid, where))
    if obj.get('gold') not in GOLD_LABELS:
        raise SchemaError(
            'gold of {0} must be one of {1}, got {2!r}{3}'.format(
                pid, '/'.join(GOLD_LABELS), obj.get('gold'), where))
    if not isinstance(obj.get('meta', {}), dict):
        raise SchemaError('meta of {0} must be an object{1}'.format(pid, where))
    return obj


def read_problems(path):
    problems = []
    seen = set()
    with open(path, encoding='utf-8') as fin:
        for lineno, line in enumerate(fin, start=1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SchemaError(
                    '{0}: invalid JSON at line {1}: {2}'.format(path, lineno, exc))
            validate_problem(obj, lineno)
            if obj['id'] in seen:
                raise SchemaError(
                    '{0}: duplicate id {1} at line {2}'.format(path, obj['id'], lineno))
            seen.add(obj['id'])
            problems.append(obj)
    return problems


def write_problems(path, problems):
    with open(path, 'w', encoding='utf-8') as fout:
        for problem in problems:
            validate_problem(problem)
            fout.write(json.dumps(problem, ensure_ascii=False) + '\n')
