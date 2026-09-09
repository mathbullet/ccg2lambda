import json
import os
import tempfile
import unittest

from evaluation import schema


def make_problem(**overrides):
    problem = {
        'id': 'sick_train_1',
        'premises': ['A man is walking.'],
        'hypothesis': 'A person is walking.',
        'gold': 'yes',
        'meta': {'source': 'SICK', 'split': 'train', 'pair_id': '1'},
    }
    problem.update(overrides)
    return problem


class ValidateProblemTestCase(unittest.TestCase):
    def test_accepts_valid_problem(self):
        self.assertEqual(make_problem(), schema.validate_problem(make_problem()))

    def test_accepts_multiple_premises(self):
        problem = make_problem(premises=['A.', 'B.'])
        self.assertEqual(problem, schema.validate_problem(problem))

    def test_rejects_invalid_id(self):
        for bad_id in (None, 42, '', 'has space', 'a/b'):
            with self.assertRaises(schema.SchemaError):
                schema.validate_problem(make_problem(id=bad_id))

    def test_rejects_bad_premises(self):
        for bad in (None, [], 'not a list', [''], ['ok.', 42]):
            with self.assertRaises(schema.SchemaError):
                schema.validate_problem(make_problem(premises=bad))

    def test_rejects_bad_hypothesis(self):
        for bad in (None, '', '   '):
            with self.assertRaises(schema.SchemaError):
                schema.validate_problem(make_problem(hypothesis=bad))

    def test_rejects_bad_gold(self):
        for bad in (None, 'YES', 'entailment', 1):
            with self.assertRaises(schema.SchemaError):
                schema.validate_problem(make_problem(gold=bad))


class ReadWriteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, 'problems.jsonl')

    def test_roundtrip(self):
        problems = [make_problem(), make_problem(id='sick_train_2', gold='unknown')]
        schema.write_problems(self.path, problems)
        self.assertEqual(problems, schema.read_problems(self.path))

    def test_read_rejects_duplicate_ids(self):
        with open(self.path, 'w') as fout:
            for _ in range(2):
                fout.write(json.dumps(make_problem()) + '\n')
        with self.assertRaises(schema.SchemaError):
            schema.read_problems(self.path)

    def test_read_reports_line_number_of_invalid_json(self):
        with open(self.path, 'w') as fout:
            fout.write(json.dumps(make_problem()) + '\n')
            fout.write('{broken\n')
        with self.assertRaises(schema.SchemaError) as ctx:
            schema.read_problems(self.path)
        self.assertIn('line 2', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
