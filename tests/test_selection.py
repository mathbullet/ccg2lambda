import unittest

from evaluation import selection


def problems(n):
    return [{'id': 'p{0}'.format(i)} for i in range(n)]


class SelectTestCase(unittest.TestCase):
    def test_no_filter_returns_all(self):
        ps = problems(5)
        self.assertEqual(ps, selection.select(ps))

    def test_ids_filter_preserves_requested_order(self):
        ps = problems(5)
        selected = selection.select(ps, ids=['p3', 'p1'])
        self.assertEqual(['p3', 'p1'], [p['id'] for p in selected])

    def test_unknown_id_raises(self):
        with self.assertRaises(selection.SelectionError):
            selection.select(problems(3), ids=['p9'])

    def test_duplicate_ids_raise(self):
        with self.assertRaises(selection.SelectionError):
            selection.select(problems(3), ids=['p1', 'p1'])

    def test_sample_is_reproducible_for_fixed_seed(self):
        ps = problems(100)
        first = selection.select(ps, sample=10, seed=7)
        second = selection.select(ps, sample=10, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(10, len(first))

    def test_different_seeds_differ(self):
        ps = problems(100)
        self.assertNotEqual(
            selection.select(ps, sample=10, seed=1),
            selection.select(ps, sample=10, seed=2))

    def test_sample_requires_seed(self):
        with self.assertRaises(selection.SelectionError):
            selection.select(problems(10), sample=3)

    def test_sample_larger_than_population_raises(self):
        with self.assertRaises(selection.SelectionError):
            selection.select(problems(3), sample=4, seed=0)

    def test_ids_then_sample_composes(self):
        ps = problems(10)
        selected = selection.select(ps, ids=['p1', 'p2', 'p3'], sample=2, seed=0)
        self.assertEqual(2, len(selected))
        self.assertTrue(all(p['id'] in ('p1', 'p2', 'p3') for p in selected))


if __name__ == '__main__':
    unittest.main()
