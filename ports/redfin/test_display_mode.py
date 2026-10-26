"""Native timestamp packing/current-mode chunks and physical cutout geometry."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class Rect(C.Structure):_fields_=[(n,C.c_double) for n in ('x','y','w','h')]


class DisplayModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);root=Path(cls.temp.name)
        (root/'mode.c').write_text('''
#include "gui-profile.h"
#include "display-mode.h"
#include "statusbar-geometry.h"
#include "graphics-exec-scope.h"
void notify(uint64_t now,uint64_t count,uint64_t out[6]){redfin_display_notification(now,count,out);}
int mode(uint64_t block,uint64_t offset,void *out,size_t bytes){return redfin_display_current_mode(block,offset,out,bytes);}
int shift(struct redfin_ui_rect t,struct redfin_ui_rect c,struct redfin_ui_rect w,double *out){return redfin_ui_time_shift(t,c,w,out);}
int scope(const char *path){return redfin_ui_executable(path);}
int refresh(uint32_t hz,uint64_t clock_hz,struct redfin_display_refresh_parameters *p){return redfin_display_refresh_parameters(hz,clock_hz,p);}
''')
        r=subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Wall','-Wextra','-Werror','-I',str(HERE),
            str(root/'mode.c'),'-o',str(root/'mode.so')],capture_output=True,text=True)
        if r.returncode:raise RuntimeError(r.stderr)
        cls.lib=C.CDLL(str(root/'mode.so'));cls.lib.notify.argtypes=[C.c_uint64,C.c_uint64,C.POINTER(C.c_uint64)]
        cls.lib.mode.argtypes=[C.c_uint64,C.c_uint64,C.c_void_p,C.c_size_t]
        cls.lib.shift.argtypes=[Rect,Rect,Rect,C.POINTER(C.c_double)]
        cls.lib.scope.argtypes=[C.c_char_p]
        cls.lib.refresh.argtypes=[C.c_uint32,C.c_uint64,C.POINTER(C.c_uint32)]

    def test_native_clcd_interval_is_fixed32_32_seconds_and_step_uses_actual_mach_clock(self):
        for hz in (60,90):
            for clock in (19200000,24000000,1000000000):
                out=(C.c_uint32*2)()
                self.assertTrue(self.lib.refresh(hz,clock,out))
                self.assertLessEqual(abs(out[0]/2**32-1/hz),0.5/2**32)
                self.assertLessEqual(abs(out[1]/clock-1/hz),0.5/clock+1e-15)
                self.assertLess(out[0],2**31);self.assertLess(out[1],2**31)
        for hz,clock in [(0,19200000),(30,19200000),(120,19200000),(90,0),(90,999999),(90,2**64-1)]:
            out=(C.c_uint32*2)(0xabcdef01,0x12345678)
            self.assertFalse(self.lib.refresh(hz,clock,out))
            self.assertEqual(list(out),[0xabcdef01,0x12345678])

    def test_actual20H392_callback_receives_time_time_counter_as_six_native_halves(self):
        out=(C.c_uint64*6)();now=0x173a345678;counter=0x1234567890
        self.lib.notify(now,counter,out)
        reconstructed=[out[2*i]|out[2*i+1]<<32 for i in range(3)]
        self.assertEqual(reconstructed,[now,now,counter])
        self.assertTrue(all(x<2**32 for x in out))

    def test_current_mode_ids_survive_native_partial_block_requests_and_reject_overflow(self):
        whole=(C.c_uint32*10)();self.assertTrue(self.lib.mode(0x40,0,whole,40))
        self.assertEqual(list(whole),[0,1,1,0,0,0,0,0,0,0])
        for offset,length in [(0,12),(4,8),(12,28),(39,1)]:
            part=C.create_string_buffer(length)
            self.assertTrue(self.lib.mode(0x40,offset,part,length))
            self.assertEqual(bytes(part),bytes(whole)[offset:offset+length])
        for block,offset,length in [(0x41,0,40),(0x40,2**64-1,40),(0x40,0,41),(0x40,1,40),(0x40,0,0)]:
            out=C.create_string_buffer(b'preserve',64)
            self.assertFalse(self.lib.mode(block,offset,out,length));self.assertEqual(out.value,b'preserve')

    def test_time_moves_outside_real_camera_without_shrinking_the_window_or_repeated_drift(self):
        camera=Rect(0,0,375*145/1080,812*136/2340);window=Rect(0,0,375,812)
        time=Rect(21,10,54,23);delta=C.c_double()
        self.assertTrue(self.lib.shift(time,camera,window,C.byref(delta)))
        self.assertGreater(delta.value,0);time.x+=delta.value
        self.assertAlmostEqual(time.x,camera.w+3)
        self.assertTrue(self.lib.shift(time,camera,window,C.byref(delta)));self.assertEqual(delta.value,0)
        # Rotated camera at the right of a landscape status bar.
        time=Rect(720,4,54,23);camera=Rect(760,0,52,50);window=Rect(0,0,812,375)
        self.assertTrue(self.lib.shift(time,camera,window,C.byref(delta)));self.assertLess(delta.value,0)
        self.assertLessEqual(time.x+time.w+delta.value,camera.x-3)
        for bad in [Rect(float('nan'),0,54,23),Rect(1,1,-1,23),Rect(1,1,40000,23)]:
            self.assertFalse(self.lib.shift(bad,camera,window,C.byref(delta)))

    def test_adapter_scope_rejects_renamed_jobs_extensions_and_writable_paths(self):
        self.assertTrue(self.lib.scope(b'/Applications/MobilePhone.app/MobilePhone'))
        self.assertTrue(self.lib.scope(b'/System/Library/CoreServices/SpringBoard.app/SpringBoard'))
        for path in [b'/tmp/SpringBoard',b'/Applications/MobilePhone.app/Other',
            b'/Applications/MobilePhone.app/PlugIns/extension',b'/private/var/mobile/Applications/AppStore.app/AppStore']:
            self.assertFalse(self.lib.scope(path))

    def test_late_native_clock_frames_restore_the_same_clearance_without_accumulating_offsets(self):
        camera=Rect(0,0,375*145/1080,812*136/2340);window=Rect(0,0,375,812)
        for width in (29,31.333333,54):
            for native_x in (20,camera.w-0.5,camera.w,camera.w+0.5,camera.w+2.99):
                clock=Rect(native_x,14,width,18);delta=C.c_double()
                for _ in range(6):
                    self.assertTrue(self.lib.shift(clock,camera,window,C.byref(delta)))
                    clock.x+=delta.value
                    self.assertAlmostEqual(clock.x,camera.w+3)
                    self.assertTrue(self.lib.shift(clock,camera,window,C.byref(delta)))
                    self.assertAlmostEqual(delta.value,0)
                    clock.x=native_x # an independent later native layout resets the frame
        # The physical exclusion is irrelevant to a clock on a different row.
        clock=Rect(21,100,54,23);delta=C.c_double()
        self.assertTrue(self.lib.shift(clock,camera,window,C.byref(delta)));self.assertEqual(delta.value,0)


if __name__=='__main__':unittest.main()
