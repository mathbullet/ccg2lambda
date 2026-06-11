import tempfile
import types
import unittest
from unittest import mock

from evaluation import pipeline


def make_env(tmpdir):
    return types.SimpleNamespace(parsers=('candc', 'easyccg'), artifacts_dir=tmpdir)


def branch(prediction=None, status='ok', stage=None):
    return {'prediction': prediction, 'status': status, 'stage': stage, 'times': {}}


PROBLEM = {'id': 'p1', 'gold': 'yes',
           'premises': ['A man walks.'], 'hypothesis': 'A person walks.'}


class ParserAggregationPolicyTestCase(unittest.TestCase):
    """Every parser runs on every problem; the aggregated answer follows the
    de-facto rule of rte_en_mp.sh select_answer: the first parser in
    preference order with a definite answer (yes/no) wins."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env = make_env(self.tmpdir.name)
        patcher = mock.patch.object(pipeline, '_tokenize', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with_branches(self, branches):
        calls = []

        def fake_branch(env, parser, tok_path, artifact_dir, problem_id):
            calls.append(parser)
            return branches[parser]

        with mock.patch.object(pipeline, '_run_parser_branch', fake_branch):
            result = pipeline.evaluate_problem(self.env, PROBLEM)
        return result, calls

    def test_all_parsers_run_and_candc_definite_answer_wins(self):
        result, calls = self.run_with_branches(
            {'candc': branch('yes'), 'easyccg': branch('no')})
        self.assertEqual(('yes', 'ok', 'candc'),
                         (result['prediction'], result['status'], result['parser']))
        self.assertEqual(['candc', 'easyccg'], calls)

    def test_candc_unknown_falls_back_to_easyccg(self):
        result, calls = self.run_with_branches(
            {'candc': branch('unknown'), 'easyccg': branch('no')})
        self.assertEqual(('no', 'ok', 'easyccg'),
                         (result['prediction'], result['status'], result['parser']))
        self.assertEqual(['candc', 'easyccg'], calls)

    def test_both_unknown_reports_candc_unknown(self):
        result, _ = self.run_with_branches(
            {'candc': branch('unknown'), 'easyccg': branch('unknown')})
        self.assertEqual(('unknown', 'ok', 'candc'),
                         (result['prediction'], result['status'], result['parser']))

    def test_candc_failure_with_easyccg_unknown_is_ok_unknown(self):
        result, _ = self.run_with_branches(
            {'candc': branch(None, status='parse_error', stage='ccg'),
             'easyccg': branch('unknown')})
        self.assertEqual(('unknown', 'ok', 'easyccg'),
                         (result['prediction'], result['status'], result['parser']))

    def test_total_failure_propagates_status_and_stage(self):
        result, _ = self.run_with_branches(
            {'candc': branch(None, status='timeout', stage='prove'),
             'easyccg': branch(None, status='semparse_error', stage='semparse')})
        self.assertIsNone(result['prediction'])
        self.assertNotEqual('ok', result['status'])
        self.assertIsNotNone(result['stage'])

    def test_per_parser_outcomes_are_recorded(self):
        result, _ = self.run_with_branches(
            {'candc': branch('unknown'), 'easyccg': branch('yes')})
        self.assertEqual('unknown', result['parsers']['candc']['prediction'])
        self.assertEqual('yes', result['parsers']['easyccg']['prediction'])

    def test_three_parser_preference_order(self):
        self.env.parsers = ('candc', 'easyccg', 'depccg')
        result, calls = self.run_with_branches(
            {'candc': branch('unknown'),
             'easyccg': branch(None, status='parse_error', stage='ccg'),
             'depccg': branch('yes')})
        self.assertEqual(('yes', 'ok', 'depccg'),
                         (result['prediction'], result['status'], result['parser']))
        self.assertEqual(['candc', 'easyccg', 'depccg'], calls)


if __name__ == '__main__':
    unittest.main()
