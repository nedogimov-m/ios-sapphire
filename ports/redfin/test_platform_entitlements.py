"""Execute the native AMFI signature hook without inventing permission keys."""
import ctypes
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_display_geometry import function
from test_smp_gui import compile_shared

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = 'bsd/kern/sweet_amfi.c'


class PlatformEntitlementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        patches = sorted((ROOT / 'xnu/patches').glob('*.patch'))
        patches += [HERE / Path(name).name for name in re.findall(
            r"['\"]([^'\"]+\.patch)['\"]", (HERE / 'prepare-xnu.py').read_text())]
        seen = set()
        for patch in patches:
            if patch in seen or not patch.is_file():
                continue
            seen.add(patch)
            if ('+++ b/' + NAME + '\n').encode() not in patch.read_bytes():
                continue
            subprocess.run(['git', 'apply', '--include=' + NAME, str(patch)], cwd=root,
                           check=True, capture_output=True)
        body = function((root / NAME).read_text(), 'static int\nsweet_amfi_vnode_check_signature(')
        prefix = r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stddef.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define CS_VALID 1u
#define CS_SIGNED 0x20000000u
#define CS_PLATFORM_BINARY 0x04000000u
#define CS_ENTITLEMENTS_VALIDATED 0x4000u
#define CS_KILL 0x200u
#define CS_ENFORCEMENT 0x1000u
#define MNT_ROOTFS 0x4000u
#define CS_VALIDATION_CATEGORY_INVALID 0u
#define CS_VALIDATION_CATEGORY_PLATFORM 1u
#define CS_VALIDATION_CATEGORY_NONE 10u
typedef int cpu_type_t;
struct mount {unsigned flags;};typedef struct mount *mount_t;
struct vnode {mount_t mount;};typedef struct vnode *vnode_t;
struct label {int unused;};
struct cs_blob {struct cs_blob *csb_ro_addr;void *csb_entitlements;unsigned csb_flags,category;};
static struct vnode root_node,node;static struct mount root_mount,other_mount;
vnode_t rootvnode;
static unsigned readable,attached,sets;
static int marker;
static mount_t vnode_mount(vnode_t p){return p->mount;}
static unsigned vfs_flags(mount_t p){return p->flags;}
static void sweet_amfi_attach_entitlements(struct cs_blob *b){attached++;if(readable)b->csb_entitlements=&marker;}
static void *csblob_os_entitlements_get(struct cs_blob *b){return b->csb_entitlements;}
static unsigned csblob_get_validation_category(struct cs_blob *b){return b->category;}
static int csblob_set_validation_category(struct cs_blob *b,unsigned category){sets++;b->category=category;return 0;}
static const char *csblob_get_identity(struct cs_blob *b){(void)b;return "com.apple.assetsd";}
static bool sweet_entitlements_string(void *ent,const char *key,const char *value){(void)key;(void)value;return ent==&marker;}
static void host_printf(const char *format,...){(void)format;}
#define printf host_printf
'''
        suffix = r'''
static unsigned category;
unsigned run(unsigned scenario,unsigned flags,unsigned before_category){
 root_mount.flags=other_mount.flags=0;node.mount=&other_mount;root_node.mount=&root_mount;rootvnode=&root_node;
 readable=1;attached=sets=0;struct cs_blob blob={NULL,NULL,CS_VALID,before_category};
 if(scenario==0){node.mount=&root_mount;root_mount.flags=MNT_ROOTFS;}
 if(scenario==1)node.mount=&root_mount;
 if(scenario==2){rootvnode=NULL;node.mount=&root_mount;root_mount.flags=MNT_ROOTFS;}
 if(scenario==4)node.mount=NULL;
 if(scenario==5){node.mount=&root_mount;readable=0;}
 if(scenario==6){node.mount=&root_mount;blob.csb_flags=0;}
 if(scenario==7){node.mount=&root_mount;blob.csb_ro_addr=&blob;blob.csb_entitlements=&marker;}
 if(sweet_amfi_vnode_check_signature(&node,NULL,0,&blob,&flags,NULL,0,0,NULL,NULL))return 0;
 category=blob.category;return flags;
}
unsigned metric(unsigned i){unsigned n[]={attached,sets,category};return i<3?n[i]:999;}
'''
        cls.lib = compile_shared(root, prefix + body + suffix, 'platform-entitlements')
        cls.lib.run.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        cls.lib.run.restype = ctypes.c_uint

    def test_actual_root_mount_and_native_root_flag_publish_consistent_restricted_status(self):
        for scenario in (0, 1, 2):
            self.assertEqual(self.lib.run(scenario, 0x12000001, 0), 0x36005201)
            self.assertEqual([self.lib.metric(i) for i in range(3)], [1, 1, 1])
            flags=self.lib.run(scenario,1,0)
            # Actual20H392 Security requires VALID|KILL|ENT_VALIDATED.
            self.assertEqual(flags&0x4201,0x4201)
            self.assertEqual(flags&0x1000,0x1000)
            self.assertEqual(flags&0x10000000,0)  # never manufacture DEBUGGED

    def test_outside_or_absent_mount_does_not_gain_platform_or_restricted_entitlements(self):
        for scenario in (3, 4):
            self.assertEqual(self.lib.run(scenario, 1, 0), 0x20000001)
            self.assertEqual([self.lib.metric(i) for i in range(3)], [1, 0, 0])

    def test_unreadable_or_invalid_entitlements_cannot_set_the_validated_bit(self):
        for scenario in (5, 6):
            self.assertEqual(self.lib.run(scenario, 1, 0), 0x24000001)
        self.assertEqual(self.lib.metric(1), 0)

    def test_existing_immutable_object_is_reused_and_other_validation_categories_are_preserved(self):
        self.assertEqual(self.lib.run(7, 1, 4), 0x24005201)
        self.assertEqual([self.lib.metric(i) for i in range(3)], [0, 0, 4])
        self.assertEqual(self.lib.run(7, 1, 10), 0x24005201)
        self.assertEqual([self.lib.metric(i) for i in range(3)], [0, 1, 1])


if __name__ == '__main__':
    unittest.main()
