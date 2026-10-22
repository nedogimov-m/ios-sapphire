"""RAM-only cutout checks, including blank frames and malformed/mixed logs."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

from ports.redfin.test_decode_screen import capture

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('redfin_check_display_fit', HERE / 'check-display-fit.py')
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def content():
    rgb = bytearray(120 * 260 * 3)
    # Exercise all four content boundaries and a visible central landmark.
    for x, y in ((3,15),(115,15),(3,259),(115,259),(60,137)):
        offset = (y*120+x)*3
        rgb[offset:offset+3] = b'\x10\x80\xff'
    return rgb


def log(frames, fit_lines=None):
    lines = [b'unrelated kernel output', *(fit_lines if fit_lines is not None else
              (checker.HID_LINE, checker.FB_LINE))]
    for number, rgb in enumerate(frames, 1):
        lines += capture(rgb, number, number * 7)
    return b'\r\n'.join(lines) + b'\r\n'


class CheckDisplayFitTests(unittest.TestCase):
    def test_exact_cutout_footprint_content_and_blank_final_frame(self):
        result = checker.inspect(log((content(), bytes(93600))))
        self.assertEqual(result['evidence'], 'RAM presentation')
        self.assertEqual(result['viewport'], dict(x=31,y=136,width=1017,height=2204))
        self.assertEqual(result['frames'][0]['black_margin_samples'],3515)
        self.assertEqual(result['frames'][0]['nonblack_content_samples'],5)
        self.assertEqual(result['frames'][0]['nonblack_content_bounds'],
                         dict(left=3,top=15,right=116,bottom=260))
        self.assertEqual(result['frames'][1]['nonblack_content_samples'],0)
        self.assertIsNone(result['frames'][1]['nonblack_content_bounds'])

    def test_nonblack_camera_top_side_or_last_frame_margin_fails(self):
        for x,y in ((0,0),(119,14),(3,14),(2,15),(116,15),(0,259),(119,259)):
            rgb=content();offset=(y*120+x)*3;rgb[offset]=1
            with self.subTest(x=x,y=y),self.assertRaisesRegex(ValueError,'nonblack margin'):
                checker.inspect(log((content(),rgb)))

    def test_missing_duplicate_wrong_or_prefixed_fit_log_fails(self):
        for lines in ((checker.FB_LINE,), (checker.HID_LINE,),
                      (checker.FB_LINE,checker.FB_LINE,checker.HID_LINE),
                      (checker.FB_LINE,checker.HID_LINE,checker.HID_LINE),
                      (checker.FB_LINE.replace(b'31,136',b'31,135'),checker.HID_LINE),
                      (checker.FB_LINE,checker.HID_LINE.replace(b'fit 2',b'fit 1')),
                      (b'other boot '+checker.FB_LINE,checker.HID_LINE)):
            with self.subTest(lines=lines),self.assertRaisesRegex(ValueError,'fit line'):
                checker.inspect(log((content(),),lines))

    def test_blank_missing_corrupt_or_truncated_capture_never_passes(self):
        with self.assertRaisesRegex(ValueError,'no rendered content'):
            checker.inspect(log((bytes(93600),bytes(93600))))
        with self.assertRaisesRegex(ValueError,'no complete screen captures'):
            checker.inspect(log(()))
        good=log((content(),))
        bad_checksum=good.rsplit(b'crc32=',1)[0]+b'crc32=00000000]\r\n'
        with self.assertRaisesRegex(ValueError,'CRC32 mismatch'):
            checker.inspect(bad_checksum)
        for data in (good.rsplit(b'\r\n',2)[0],b'X'*(checker.decoder.MAX_LOG_BYTES+1)):
            with self.assertRaises(ValueError):
                checker.inspect(data)

    def test_cli_reads_only_and_reports_failure_without_writing_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);path=directory/'console.txt';path.write_bytes(log((content(),)))
            before=path.read_bytes();stdout=io.StringIO();stderr=io.StringIO()
            with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
                self.assertEqual(checker.main([str(path)]),0)
            self.assertEqual(json.loads(stdout.getvalue())['mode'],'cutout')
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list(directory.iterdir()),[path])
            path.write_bytes(log((bytes(93600),)))
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(checker.main([str(path)]),1)
            self.assertIn('no rendered content',stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
