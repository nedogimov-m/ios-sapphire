"""Compile the overlay's actual pure guards; no kernel or device access."""
import ctypes
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


class Plan(ctypes.Structure):
    _fields_ = [("channel_offset", ctypes.c_uint32),
                ("command", ctypes.c_uint32), ("value", ctypes.c_uint8)]


class SPMIReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host cc unavailable")
        patch = Path(__file__).with_name("spmi-return.patch").read_text()
        added = "\n".join(line[1:] for line in patch.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        pure = added.split("/* REDFIN_RETURN_TEST_BEGIN", 1)[1].split(
            "/* REDFIN_RETURN_TEST_END */", 1)[0]
        source = "#include <stdint.h>\n#include <stdbool.h>\n#include <errno.h>\n"
        source += "/* REDFIN_RETURN_TEST_BEGIN" + pure
        source += """
int ranges(const uint64_t *r,unsigned n){return redfin_return_ranges(r,n);}
int plan(uint32_t v,unsigned a,unsigned o,uint32_t m,uint8_t s,uint8_t b,
    struct redfin_return_plan *p){return redfin_return_plan(v,a,o,m,s,b,p);}
"""
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cfile, lib = Path(cls.tmp.name) / "guard.c", Path(cls.tmp.name) / "guard.so"
        cfile.write_text(source)
        subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra",
                        "-Werror", str(cfile), "-o", str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.ranges.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint]
        cls.lib.ranges.restype = ctypes.c_int
        cls.lib.plan.argtypes = [ctypes.c_uint32, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8,
                                ctypes.POINTER(Plan)]
        cls.lib.plan.restype = ctypes.c_int

    def call(self, version=0x50000000, apid=0, owner=0, mapping=0x800,
             subtype=4, spare=0):
        out = Plan(0x12345678, 0x87654321, 0x55)
        result = self.lib.plan(version, apid, owner, mapping, subtype, spare,
                               ctypes.byref(out))
        return result, (out.channel_offset, out.command, out.value)

    def test_only_explicit_write_channel_and_imem_ranges(self):
        expected = (0x0c600000, 0x2000000, 0x146ab65c, 4)
        reg = (ctypes.c_uint64 * 4)(*expected)
        self.assertEqual(self.lib.ranges(reg, 32), 1)
        self.assertEqual(self.lib.ranges(None, 32), 0)
        for size in (0, 16, 24, 31, 33, 40):
            self.assertEqual(self.lib.ranges(reg, size), 0)
        for index in range(4):
            for delta in (-1, 1):
                changed = list(expected)
                changed[index] += delta
                self.assertEqual(self.lib.ranges((ctypes.c_uint64 * 4)(*changed), 32), 0)

    def test_supported_versions_and_bounded_channel_offsets(self):
        for version in (0x50000000, 0x5fffffff, 0x60000000, 0x6fffffff):
            for apid in (0, 1, 511):
                result, (offset, command, value) = self.call(version=version, apid=apid)
                self.assertEqual(result, 0)
                self.assertEqual((offset, command, value), (apid * 0x10000, 0x8f0, 4))
                self.assertLessEqual(offset + 0x20, 0x2000000)

    def test_fail_closed_without_changing_plan(self):
        cases = [dict(version=v) for v in (0, 0x4fffffff, 0x70000000, 0xffffffff)]
        cases += [dict(apid=a) for a in (512, 0xffffffff)]
        cases += [dict(owner=o) for o in range(1, 8)]
        cases += [dict(mapping=m) for m in (0, 0x700, 0x900, 0x10800, 0xfff00)]
        cases += [dict(subtype=s) for s in (0, 1, 3, 5, 255)]
        for args in cases:
            with self.subTest(**args):
                result, out = self.call(**args)
                self.assertEqual(result, errno.EINVAL)
                self.assertEqual(out, (0x12345678, 0x87654321, 0x55))
        self.assertEqual(self.lib.plan(0x50000000, 0, 0, 0x800, 4, 0, None), errno.EINVAL)

    def test_all_spare_values_preserve_bit_zero_only(self):
        for spare in range(256):
            result, (_, command, value) = self.call(spare=spare)
            self.assertEqual(result, 0)
            self.assertEqual(value & 0xfe, 0x04)
            self.assertEqual(value & 1, spare & 1)
            self.assertEqual(command, 0x8f0)  # opcode0, register0x8f, one byte.


class SPMIReturnIRQTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host cc unavailable")
        patch = Path(__file__).with_name("spmi-return.patch").read_text()
        added = "\n".join(line[1:] for line in patch.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        pure = "/* REDFIN_RETURN_TEST_BEGIN" + added.split(
            "/* REDFIN_RETURN_TEST_BEGIN", 1)[1].split("/* REDFIN_RETURN_TEST_END */", 1)[0]
        function = added.split("int redfin_spmi_arm_return(void);", 1)[1].split(
            "\n}\n", 1)[0] + "\n}\n"
        # Host execution replaces only AArch64 barriers; control flow and all
        # accesses in the actual arm function remain intact. MMIO uses arrays.
        function = re.sub(r'__asm__ volatile\([^;]*;', '(void)0;', function)
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *DTEntry;
#define kSuccess 0
static struct {
    bool ready; vm_offset_t core,observer,config; uint32_t version;
    unsigned apid,owner; uint8_t subtype;
} redfin_spmi_proof = {true,1,2,3,0x50000000,1,0,4};
static int mode,violations,off_count,on_count,read_count,delay_count;
static bool irqs = true;
static uint32_t channel[8],reason;
static const uint64_t regs[] = {0x0c600000,0x2000000,0x146ab65c,4};
static int PE_parse_boot_argn(const char *name,void *value,int size) {
    (void)size; *(uint32_t *)value = (name[0]=='r' || name[0]=='c'); return 1;
}
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *out) {
    (void)root; (void)path; *out = (void *)1; return kSuccess;
}
static int SecureDTGetProperty(DTEntry node,const char *name,const void **p,unsigned *n) {
    (void)node; (void)name; *p=regs; *n=sizeof(regs); return kSuccess;
}
static vm_offset_t ml_io_map(vm_offset_t address,vm_size_t size) {
    (void)size;
    return address==0x146ab65c ? (vm_offset_t)&reason : (vm_offset_t)channel;
}
static bool ml_set_interrupts_enabled(bool enabled) {
    bool old=irqs;
    if (enabled) on_count++; else { off_count++; if (!irqs) violations++; }
    irqs=enabled; return old;
}
static int test_printf(const char *format,...) {
    (void)format; if (!irqs) violations++; return 0;
}
static void delay(unsigned usec) {
    (void)usec; delay_count++; if (irqs) violations++;
}
static uint32_t redfin_spmi_rd(vm_offset_t base,unsigned offset) {
    if (base==redfin_spmi_proof.core)
        return offset ? (mode==10 ? 0x900 : 0x800) : (mode==1 ? 0x40000000 : 0x50000000);
    if (base==redfin_spmi_proof.config) return mode==11 ? 1 : 0;
    if (base==(vm_offset_t)channel) {
        if (irqs || offset!=8) violations++;
        return mode==5 ? 9 : mode==6 ? 0 : 1;
    }
    if (!irqs) violations++;
    return mode==9 ? 0 : reason;
}
static int redfin_spmi_read(vm_offset_t observer,unsigned apid,unsigned address,uint8_t *out) {
    (void)observer; (void)apid; (void)address;
    if (!irqs) violations++;
    unsigned index=read_count++;
    if ((mode==2 && index==0) || (mode==3 && index==1) || (mode==7 && index==2)) {
        test_printf("observer diagnostic"); return EIO;
    }
    *out=index==0 ? (mode==4 ? 5 : 4) : index==1 ? 1 : (mode==8 ? 0 : 5);
    return 0;
}
#define printf test_printf
'''
        suffix = r'''
#undef printf
int main(int argc,char **argv) {
    if (argc!=2) return 2;
    mode=atoi(argv[1]);
    int result=redfin_spmi_arm_return();
    printf("%d %d %d %d %d %u %u %u %d\n",result,irqs,violations,off_count,on_count,
        channel[0],channel[4],reason,delay_count);
    return 0;
}
'''
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        source, cls.binary = Path(cls.tmp.name) / "irq.c", Path(cls.tmp.name) / "irq"
        source.write_text(prefix + pure + function + suffix)
        subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(source), "-o", str(cls.binary)], check=True)

    def test_actual_arm_body_preserves_irq_state_across_all_failure_routes(self):
        # Each fresh process also exercises the function's original one-shot
        # static flag; no production declaration or branch is changed.
        expected = (0, errno.ENXIO, errno.EIO, errno.EIO, errno.EINVAL,
                    errno.EIO, errno.ETIMEDOUT, errno.EIO, errno.EIO,
                    errno.EIO, errno.ENXIO, errno.ENXIO)
        for mode, error in enumerate(expected):
            with self.subTest(mode=mode):
                values = [int(x) for x in subprocess.check_output(
                    [str(self.binary), str(mode)], text=True).split()]
                result, irqs, violations, off, on, command, data, imem, delays = values
                self.assertEqual((result, irqs, violations), (error, 1, 0))
                writes = mode in (0, 5, 6, 7, 8, 9)
                self.assertEqual((off, on), (int(writes), int(writes)))
                self.assertEqual((command, data), (0x8f0, 5) if writes else (0, 0))
                self.assertEqual(imem, 0x77665500 if mode in (0, 9) else 0)
                self.assertEqual(delays, 1000 if mode==6 else 0)


if __name__ == "__main__":
    unittest.main()
