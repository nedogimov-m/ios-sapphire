"""Test actual query ABI, interrupted cookies, busy bounds and ownership."""
import ctypes as C
import errno
from pathlib import Path
import tempfile
import unittest

from test_smp_gui import compile_shared

HERE = Path(__file__).resolve().parent
MODEL = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "include/redfin_scm_query.h"
static unsigned fault,calls,valids,bad,delays;
static uint64_t now;
static struct rf_sq_regs first;
static struct rf_sq_report report;
static bool valid(void *p){if(p)bad++;valids++;return fault!=1 && !(fault==3&&calls);}
static uint64_t time_ns(void *p){if(p)bad++;now+=fault==7?100000001:100;return fault==8&&calls?0:now;}
static void delay_us(void *p,unsigned us){if(p||us!=30000)bad++;now+=(uint64_t)us*1000;delays++;}
static int invoke(void *p,struct rf_sq_regs *r){
 if(p)bad++;calls++;
 if(calls==1)first=*r;
 if(r->x[7])bad++;
 if(fault==2)return ENXIO;
 if(fault==4 || (fault==9&&calls==1)){
  if(calls>1 && (r->x[0]!=1 || r->x[6]!=0xdeadbeef || r->x[1]!=0x123))bad++;
  r->x[0]=1;r->x[6]=0xdeadbeef;r->x[1]=0x123;return 0;
 }
 if(fault==9 && (r->x[0]!=1 || r->x[6]!=0xdeadbeef || r->x[1]!=0x123))bad++;
 if(fault==5 || (fault==10&&calls<3)){
  if(memcmp(r,&first,sizeof(first)))bad++;
  for(unsigned i=0;i<8;i++)r->x[i]=UINT64_MAX;
  r->x[0]=report.convention==32?0xfffffff4u:UINT64_MAX-11;return 0;
 }
 if(fault==10 && memcmp(r,&first,sizeof(first)))bad++;
 r->x[0]=fault==6?(report.convention==32?0xffffffffu:UINT64_MAX):0;
 r->x[1]=1;r->x[2]=2;r->x[3]=3;return 0;
}
int run(unsigned convention,unsigned kind,uint32_t arg,unsigned issue){
 fault=issue;calls=valids=bad=delays=0;now=0;memset(&report,0,sizeof(report));memset(&first,0,sizeof(first));
 const struct rf_sq_ops ops={NULL,valid,invoke,delay_us,time_ns};
 int rc=rf_sq_run(&ops,convention,kind,arg,&report);
 return bad?-100-(int)bad:rc;
}
uint64_t stat(unsigned n){uint64_t v[]={calls,delays,report.resumes,report.busy_retries,
 report.completed,report.value[0],report.value[1],report.value[2],first.x[0],first.x[1],first.x[2],report.elapsed_ns};return n<12?v[n]:0;}
int plan(unsigned width,unsigned kind,uint32_t arg,uint64_t *words){
 struct rf_sq_regs r;int result=rf_sq_request(width,kind,arg,&r);if(result)memcpy(words,r.x,sizeof(r.x));return result;
}
'''


class SCMQueryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.lib = compile_shared(Path(cls.temp.name), MODEL, 'scm-query')
        cls.lib.run.argtypes = [C.c_uint] * 4
        cls.lib.stat.argtypes = [C.c_uint]
        cls.lib.stat.restype = C.c_uint64
        cls.lib.plan.argtypes = [C.c_uint, C.c_uint, C.c_uint32, C.POINTER(C.c_uint64)]

    def test_exact_native_detection_and_standard_query_registers(self):
        for width, mask in ((32, 0), (64, 0x40000000)):
            for kind, argument, function, operand in ((1, 0, 0x82000601, 0x82000601),
                    (2, 0x02000207, 0x02000601, 0x02000207), (3, 4, 0x02000207, 4),
                    (3, 13, 0x02000207, 13)):
                words = (C.c_uint64 * 8)()
                self.assertEqual(self.lib.plan(width, kind, argument, words), 1)
                self.assertEqual(list(words), [function | mask, 1, operand, 0, 0, 0, 0, 0])
                self.assertEqual(self.lib.run(width, kind, argument, 0), 0)
                self.assertEqual([self.lib.stat(i) for i in (0, 4, 5, 6, 7)], [1, 1, 1, 2, 3])

    def test_mutating_functions_unknown_targets_and_widths_reach_no_callback(self):
        for width, kind, arg in ((0, 1, 0), (65, 1, 0), (64, 0, 0), (64, 1, 1),
                                (64, 2, 0x42000207), (64, 2, 0x02000502),
                                (64, 3, 0), (64, 3, 6), (64, 4, 4)):
            self.assertEqual(self.lib.run(width, kind, arg, 0), errno.EINVAL)
            self.assertEqual(self.lib.stat(0), 0)

    def test_resume_preserves_cookie_and_registers_and_is_bounded(self):
        for width in (32, 64):
            self.assertEqual(self.lib.run(width, 3, 13, 9), 0)
            self.assertEqual([self.lib.stat(i) for i in (0, 2, 4)], [2, 1, 1])
            self.assertEqual(self.lib.run(width, 3, 13, 4), errno.ETIMEDOUT)
            self.assertEqual([self.lib.stat(i) for i in (0, 2, 4)], [17, 17, 0])

    def test_busy_restarts_original_query_and_handles_smc32_sign_extension(self):
        for width in (32, 64):
            self.assertEqual(self.lib.run(width, 3, 4, 10), 0)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 3, 4)], [3, 2, 2, 1])
            self.assertEqual(self.lib.run(width, 3, 4, 5), errno.EBUSY)
            self.assertEqual([self.lib.stat(i) for i in (0, 1, 3, 4)], [4, 3, 3, 0])

    def test_platform_and_lifetime_failures_stop_without_claiming_completion(self):
        for fault, result, calls in ((1, errno.ECANCELED, 0), (2, errno.ENXIO, 1),
                                    (3, errno.ECANCELED, 1), (7, errno.ETIMEDOUT, 1),
                                    (8, errno.ETIMEDOUT, 1)):
            self.assertEqual(self.lib.run(64, 3, 4, fault), result)
            self.assertEqual(self.lib.stat(0), calls)
            self.assertEqual(self.lib.stat(4), 0)
        for width in (32, 64):
            self.assertEqual(self.lib.run(width, 3, 4, 6), errno.EIO)
            self.assertEqual(self.lib.stat(4), 1)


if __name__ == '__main__':
    unittest.main()
