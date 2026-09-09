"""Subset selection over a problem set: explicit ids or seeded random sampling."""
import random


class SelectionError(ValueError):
    pass


def select(problems, ids=None, sample=None, seed=None):
    """Return the selected subset of problems.

    ids: iterable of problem ids; the result follows the order of `ids`.
    sample: draw this many problems uniformly; requires an explicit seed so
    that every run is reproducible by construction.
    """
    selected = list(problems)
    if ids is not None:
        ids = list(ids)
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise SelectionError('duplicate ids requested: {0}'.format(', '.join(duplicates)))
        by_id = {p['id']: p for p in selected}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise SelectionError('unknown problem ids: {0}'.format(', '.join(missing)))
        selected = [by_id[i] for i in ids]
    if sample is not None:
        if seed is None:
            raise SelectionError('sampling requires an explicit seed for reproducibility')
        if sample > len(selected):
            raise SelectionError(
                'sample size {0} exceeds the {1} available problems'.format(
                    sample, len(selected)))
        selected = random.Random(seed).sample(selected, sample)
    return selected
