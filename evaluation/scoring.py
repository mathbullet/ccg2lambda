"""Aggregate per-problem results into accuracy, a confusion matrix and error stats.

Evaluation failures (status != 'ok') are first-class outcomes: they occupy a
dedicated 'error' column in the confusion matrix and are never silently
conflated with an 'unknown' prediction. The primary accuracy treats them as
incorrect; accuracy_errors_as_unknown is reported only as a reference point
comparable with the legacy shell aggregation.

Besides the accuracy of the aggregated system answer, score() reports the
accuracy of each parser on its own and the oracle (ensemble upper bound)
accuracy: a problem counts as oracle-correct when at least one parser
predicted the gold label.
"""

LABELS = ('yes', 'no', 'unknown')
STATUS_OK = 'ok'


def score(results, parsers=None):
    confusion = {gold: {col: 0 for col in LABELS + ('error',)} for gold in LABELS}
    status_counts = {}
    correct = 0
    correct_errors_as_unknown = 0
    for result in results:
        gold = result['gold']
        status = result['status']
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == STATUS_OK:
            prediction = result['prediction']
            confusion[gold][prediction] += 1
            if prediction == gold:
                correct += 1
                correct_errors_as_unknown += 1
        else:
            confusion[gold]['error'] += 1
            if gold == 'unknown':
                correct_errors_as_unknown += 1
    total = len(results)
    errors = total - status_counts.get(STATUS_OK, 0)

    if parsers is None:
        parsers = sorted({name for result in results
                          for name in result.get('parsers', {})})
    parser_stats = {name: {'correct': 0, 'errors': 0} for name in parsers}
    oracle_correct = 0
    for result in results:
        gold = result['gold']
        any_correct = False
        for name in parsers:
            branch = result.get('parsers', {}).get(name)
            if branch is None or branch['status'] != STATUS_OK:
                parser_stats[name]['errors'] += 1
                continue
            if branch['prediction'] == gold:
                parser_stats[name]['correct'] += 1
                any_correct = True
        if any_correct:
            oracle_correct += 1

    return {
        'total': total,
        'correct': correct,
        'accuracy': correct / total if total else 0.0,
        'accuracy_errors_as_unknown':
            correct_errors_as_unknown / total if total else 0.0,
        'error_rate': errors / total if total else 0.0,
        'status_counts': status_counts,
        'confusion': confusion,
        'parser_accuracy': {
            name: {
                'accuracy': stats['correct'] / total if total else 0.0,
                'correct': stats['correct'],
                'error_rate': stats['errors'] / total if total else 0.0,
            }
            for name, stats in parser_stats.items()},
        'oracle': {
            'accuracy': oracle_correct / total if total else 0.0,
            'correct': oracle_correct,
        },
    }
