import os
import unittest

from evaluation.datasets import sick

HEADER = '\t'.join([
    'pair_ID', 'sentence_A', 'sentence_B', 'relatedness_score',
    'entailment_judgment', 'SemEval_set'])


def line(pair_id, sent_a, sent_b, judgment, split):
    return '\t'.join([pair_id, sent_a, sent_b, '4.5', judgment, split]) + '\n'


class ConvertTestCase(unittest.TestCase):
    def convert(self, *lines):
        return list(sick.convert(iter([HEADER + '\n'] + list(lines))))

    def test_label_mapping_covers_three_classes(self):
        rows = self.convert(
            line('1', 'A man walks.', 'A person walks.', 'ENTAILMENT', 'TRAIN'),
            line('2', 'A man walks.', 'Nobody walks.', 'CONTRADICTION', 'TRIAL'),
            line('3', 'A man walks.', 'A dog barks.', 'NEUTRAL', 'TEST'),
        )
        self.assertEqual(
            [('train', 'yes'), ('trial', 'no'), ('test', 'unknown')],
            [(split, p['gold']) for split, p in rows])

    def test_problem_shape(self):
        ((split, problem),) = self.convert(
            line('23', 'A man walks.', 'A person walks.', 'ENTAILMENT', 'TRAIN'))
        self.assertEqual('sick_train_23', problem['id'])
        self.assertEqual(['A man walks.'], problem['premises'])
        self.assertEqual('A person walks.', problem['hypothesis'])
        self.assertEqual(
            {'source': 'SICK', 'split': 'train', 'pair_id': '23'}, problem['meta'])

    def test_sentences_get_exactly_one_trailing_period(self):
        ((_, problem),) = self.convert(
            line('1', 'No period here', 'Already has one.', 'NEUTRAL', 'TRAIN'))
        self.assertEqual('No period here.', problem['premises'][0])
        self.assertEqual('Already has one.', problem['hypothesis'])

    def test_unknown_judgment_raises(self):
        with self.assertRaises(sick.SickFormatError):
            self.convert(line('1', 'A.', 'B.', 'MAYBE', 'TRAIN'))

    def test_unknown_split_raises(self):
        with self.assertRaises(sick.SickFormatError):
            self.convert(line('1', 'A.', 'B.', 'NEUTRAL', 'DEV'))

    def test_missing_column_raises(self):
        with self.assertRaises(sick.SickFormatError):
            list(sick.convert(iter(['pair_ID\tsentence_A\n'])))


@unittest.skipUnless(
    os.path.isfile('data/raw/SICK.semeval.txt'),
    'real SICK dataset not available')
class RealDatasetTestCase(unittest.TestCase):
    def test_split_sizes_and_determinism(self):
        first = sick.convert_file('data/raw/SICK.semeval.txt')
        self.assertEqual(4439, len(first['train']))
        self.assertEqual(495, len(first['trial']))
        self.assertEqual(4906, len(first['test']))
        second = sick.convert_file('data/raw/SICK.semeval.txt')
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
