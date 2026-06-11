"""Aggregate per-problem results into accuracy, a confusion matrix and error stats.

Evaluation failures (status != 'ok') are first-class outcomes: they occupy a
dedicated 'error' column in the confusion matrix and are never silently
conflated with an 'unknown' prediction. The primary accuracy treats them as
incorrect; accuracy_errors_as_unknown is reported only as a reference point
comparable with the legacy shell aggregation.
"""

LABELS = ('yes', 'no', 'unknown')
STATUS_OK = 'ok'


def score(results):
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
    return {
        'total': total,
        'correct': correct,
        'accuracy': correct / total if total else 0.0,
        'accuracy_errors_as_unknown':
            correct_errors_as_unknown / total if total else 0.0,
        'error_rate': errors / total if total else 0.0,
        'status_counts': status_counts,
        'confusion': confusion,
    }
