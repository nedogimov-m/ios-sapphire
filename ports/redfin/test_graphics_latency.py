"""Do not confuse host retirement waits, nested frontend work or stale boots."""
import unittest
from ports.redfin.graphics_latency import analyze


class GraphicsLatencyTests(unittest.TestCase):
    boot='0123456789abcdef'

    def rows(self,pid=61,boot=None,native=1):
        prefix=f'redwoodmetal[backboardd {pid}]: REDFIN METAL '
        common=f'boot={boot or self.boot} sequence=120 actual-finish=1 '
        return [prefix+'FENCE: '+common+'draws=37 final-fence-us=80',
                prefix+'RETIREMENT: '+common+f'native-ticket={native} completion-queue-us=2 native-wait-us=7 '
                'predecessor-us=1 retire-gate-us=68 bookkeeping-us=2 resources-us=3 slot-us=1 submit-to-ready-us=84',
                prefix+'FRONTEND: '+common+'draw-us=10 stage-us=8 constant-copy-us=3 nested-scopes=1']

    def test_real_native_wait_is_separate_from_gate_and_overlapping_frontend(self):
        result=analyze(self.rows(),self.boot)
        self.assertEqual(result['complete_samples'],1);self.assertFalse(result['invalid_samples'])
        self.assertEqual(result['retirement_us']['native-wait-us']['median'],7)
        self.assertEqual(result['retirement_us']['retire-gate-us']['median'],68)
        self.assertTrue(result['frontend_scopes_overlap']);self.assertFalse(result['gpu_execution_time_measured'])

    def test_pid_and_boot_cannot_complete_another_runs_missing_sample(self):
        lines=self.rows()[:1]+self.rows(pid=62)[1:]+self.rows(boot='ffffffffffffffff')[1:]
        result=analyze(lines,self.boot)
        self.assertEqual(result['complete_samples'],0);self.assertEqual(result['incomplete_samples'],2)

    def test_false_completion_or_inconsistent_partition_is_rejected(self):
        for rows in (self.rows(native=0),[r.replace('submit-to-ready-us=84','submit-to-ready-us=183') for r in self.rows()]):
            result=analyze(rows,self.boot)
            self.assertFalse(result['complete_samples']);self.assertTrue(result['invalid_samples'])
        rows=self.rows();rows.append(rows[1].replace('native-wait-us=7','native-wait-us=8'))
        self.assertTrue(analyze(rows,self.boot)['invalid_samples'])

    def test_native_raster_routes_are_per_command_counts_and_require_actual_retirement(self):
        row=f'redwoodmetal[backboardd 61]: REDFIN METAL ROUTES: boot={self.boot} sequence=120 actual-finish=1 gmem-batches=3 sysmem-batches=2 command-delta=1'
        result=analyze(self.rows()+[row],self.boot)
        self.assertEqual(result['complete_samples'],1)
        self.assertEqual(result['raster_routes']['gmem-batches']['median'],3)
        self.assertEqual(result['raster_routes']['sysmem-batches']['median'],2)
        self.assertTrue(analyze(self.rows()+[row.replace('command-delta=1','command-delta=0')],self.boot)['invalid_samples'])
        self.assertFalse(analyze([row],self.boot)['complete_samples'])


if __name__=='__main__':unittest.main()
