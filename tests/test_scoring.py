import unittest

from evaluation import scoring


def result(gold, prediction=None, status='ok'):
    return {'id': 'x', 'gold': gold, 'prediction': prediction, 'status': status}


class ScoreTestCase(unittest.TestCase):
    def test_perfect_run(self):
        results = [result('yes', 'yes'), result('no', 'no'), result('unknown', 'unknown')]
        s = scoring.score(results)
        self.assertEqual(3, s['total'])
        self.assertEqual(1.0, s['accuracy'])
        self.assertEqual(0.0, s['error_rate'])
        self.assertEqual(1, s['confusion']['yes']['yes'])
        self.assertEqual(1, s['confusion']['no']['no'])
        self.assertEqual(1, s['confusion']['unknown']['unknown'])

    def test_confusion_matrix_off_diagonal(self):
        s = scoring.score([result('yes', 'no'), result('unknown', 'yes')])
        self.assertEqual(0.0, s['accuracy'])
        self.assertEqual(1, s['confusion']['yes']['no'])
        self.assertEqual(1, s['confusion']['unknown']['yes'])

    def test_error_on_unknown_gold_is_not_counted_correct(self):
        # Regression test for the legacy aggregation (eacl2017exp.sh:107-113)
        # that scored crashes as correct whenever gold was unknown.
        s = scoring.score([result('unknown', None, status='timeout')])
        self.assertEqual(0, s['correct'])
        self.assertEqual(0.0, s['accuracy'])
        self.assertEqual(1.0, s['accuracy_errors_as_unknown'])
        self.assertEqual(1, s['confusion']['unknown']['error'])
        self.assertEqual(1.0, s['error_rate'])

    def test_status_counts(self):
        results = [
            result('yes', 'yes'),
            result('no', None, status='timeout'),
            result('no', None, status='semparse_error'),
        ]
        s = scoring.score(results)
        self.assertEqual({'ok': 1, 'timeout': 1, 'semparse_error': 1}, s['status_counts'])
        self.assertAlmostEqual(2 / 3, s['error_rate'])

    def test_empty_results(self):
        s = scoring.score([])
        self.assertEqual(0, s['total'])
        self.assertEqual(0.0, s['accuracy'])


if __name__ == '__main__':
    unittest.main()
