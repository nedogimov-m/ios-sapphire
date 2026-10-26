"""Reject partial native timing evidence and verify the independent logger cap."""
import unittest

from gpu_output_budget import analyze


class OutputBudgetTests(unittest.TestCase):
    records = (
        'REDFIN GPU OWNER: s=1024 k=R r=0 us=1,2,3,4,5,6,23 host=1\n'
        'REDFIN GPU OUTPUT: f=120 n=1 clear=0 us=2,3,4,5,6,7,27 scope=1\n'
        'REDFIN GPU OWNER ID: s=1024 name=backboardd pid=61 cf=7 pf=8\n'
        'REDFIN GPU OWNER ID: s=1025 name=kernel pid=0 cf=0 pf=0\n'
        'REDFIN GPU OWNER: s=1025 k=P r=0 us=2,3,4,5,6,7,32 host=1\n')

    def test_complete_interleaved_records_preserve_real_scopes_and_native_identity(self):
        result = analyze(self.records)
        self.assertTrue(result['valid'])
        self.assertEqual((result['owner_samples'], result['output_samples']), (2,1))
        self.assertFalse(result['gpu_execution_time_isolated'])
        self.assertEqual(result['owner_rows'][0]['physical_fence'], 8)
        self.assertEqual(result['summary']['present']['owner-execute-us']['median'], 4)
        self.assertEqual(result['summary']['output']['source-sync-us']['median'], 3)

    def test_truncation_bad_totals_duplicate_keys_and_missing_identity_never_validate(self):
        for text in (self.records.replace('23 host=1', '23 host='),
                     self.records.replace('5,6,23', '5,6,100'),
                     self.records.replace('7,27 scope=1', '7,99 scope=1'),
                     self.records+self.records.splitlines()[0]+'\n',
                     self.records.replace('REDFIN GPU OWNER ID: s=1024', 'ignored: s=1024')):
            with self.subTest(text=text):
                result = analyze(text)
                self.assertFalse(result['valid'])
                self.assertTrue(result['invalid'])

    def test_old_truncated_prefixes_or_absent_output_are_insufficient_evidence(self):
        self.assertFalse(analyze('REDFIN GPU OWNER PHASE: sequence=1 owner-execute-us=4203')['valid'])
        self.assertFalse(analyze('\n'.join(line for line in self.records.splitlines()
                                         if 'GPU OUTPUT:' not in line))['valid'])


if __name__ == '__main__':
    unittest.main()
