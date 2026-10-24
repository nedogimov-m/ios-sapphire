"""Host-only tests for the unapplied RW overlay; never run device commands."""
import ctypes
import errno
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
BLOCK, BOUNCE, FIRST, IMAGE_BLOCKS = 4096, 1 << 20, 4096, 0x400000
DISK, PARTITION = 0x1000000, 0x800000


def additions():
    return "\n".join(line[1:] for line in (HERE / "ufs-root-rw.patch").read_text().splitlines()
                     if line.startswith("+") and not line.startswith("+++"))


def section(text, name):
    return "/* " + name + "_BEGIN" + text.split("/* " + name + "_BEGIN", 1)[1].split(
        "/* " + name + "_END */", 1)[0]


def function(text, name):
    signature = text.index(name + "(")
    start = text.rfind("\nstatic ", 0, signature) + 1
    opening = text.index("{", signature)
    depth = 0
    for end in range(opening, len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if depth == 0:
            return text[start:end + 1]
    raise ValueError("unterminated function: " + name)


def patched_source():
    """Apply only to a temporary copy; the current RO kernel stays untouched."""
    source = HERE.parents[1] / "research/redfin-build/dxb/xnu/bsd/dev/sweet_ufs.c"
    if not source.is_file():
        raise unittest.SkipTest("prepared RO kernel source required for actual I/O body tests")
    original = source.read_text()
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "bsd/dev/sweet_ufs.c"
        target.parent.mkdir(parents=True)
        target.write_text(original)
        later = HERE / 'graphics-journal.patch'
        if '#include "redfin_graphics_journal.inc"' in original:
            # Exercise the original strict RW contract independently of the
            # separate GUI3/native-journal preflight, which has its own cases.
            shutil.copy2(source.parent/'redfin_graphics_journal.inc',target.parent/'redfin_graphics_journal.inc')
            subprocess.run(['git','apply','--reverse',str(later)],cwd=directory,check=True,capture_output=True)
            original = target.read_text()
        command = ["git", "apply", "--check", str(HERE / "ufs-root-rw.patch")]
        checked = subprocess.run(command, cwd=directory, capture_output=True)
        if checked.returncode:
            # Also support deliberate later activation of this exact overlay.
            subprocess.run(["git", "apply", "--reverse", "--check", str(HERE / "ufs-root-rw.patch")],
                           cwd=directory, check=True, capture_output=True)
            return original
        subprocess.run(["git", "apply", str(HERE / "ufs-root-rw.patch")],
                       cwd=directory, check=True, capture_output=True)
        return target.read_text()


def header(clean=True):
    out = bytearray(512)
    out[:4] = b"HX\0\5"
    struct.pack_into(">I", out, 4, 0x2000 | (0x100 if clean else 0))
    struct.pack_into(">I", out, 12, 129)
    struct.pack_into(">II", out, 40, BLOCK, IMAGE_BLOCKS)
    return out


PREFIX = "#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <errno.h>\n"
PREFIX += "#define UFS_BLOCK 4096u\n#define BOUNCE_SIZE (1u << 20)\n"


class RWGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host compiler unavailable")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        wrappers = r'''
int flags(uint32_t a,uint32_t b,uint32_t c,bool *out){return redfin_rw_flags(a,b,c,out);}
int window(uint64_t f,uint64_t p,uint64_t e,uint64_t d){return redfin_rw_window(f,p,e,d);}
int command(const uint8_t *c,unsigned n,uint32_t l,bool w,uint8_t lun,bool arm,
    uint64_t f,uint64_t p,uint64_t e,uint64_t d){return redfin_rw_command(c,n,l,w,lun,arm,f,p,e,d);}
int hfs(const uint8_t *p,unsigned pn,const uint8_t *a,unsigned an){return redfin_rw_hfs(p,pn,a,an);}
int response(const uint8_t *r,unsigned n,uint32_t o,uint8_t l,uint8_t t){return redfin_rw_response(r,n,o,l,t);}
'''
        path, library = Path(cls.tmp.name) / "guards.c", Path(cls.tmp.name) / "guards.so"
        path.write_text(PREFIX + section(additions(), "REDFIN_RW_TEST") + wrappers)
        subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(path), "-o", str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.flags.argtypes = [ctypes.c_uint32] * 3 + [ctypes.POINTER(ctypes.c_bool)]
        cls.lib.window.argtypes = [ctypes.c_uint64] * 4
        cls.lib.command.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint32,
                                   ctypes.c_bool, ctypes.c_uint8, ctypes.c_bool] + [ctypes.c_uint64] * 4
        cls.lib.hfs.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        cls.lib.response.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint32,
                                    ctypes.c_uint8, ctypes.c_uint8]

    def test_both_exact_flags_and_no_legacy_log_are_required(self):
        for a in (0, 1, 2, 0xffffffff):
            for b in (0, 1, 2, 0xffffffff):
                for log in (0, 1):
                    requested = ctypes.c_bool(True)
                    status = self.lib.flags(a, b, log, ctypes.byref(requested))
                    valid = a == b and a in (0, 1) and not log
                    self.assertEqual(status, 0 if valid else errno.EROFS)
                    self.assertEqual(requested.value, valid and a == 1)
        self.assertEqual(self.lib.flags(1, 1, 0, None), errno.EINVAL)

    def test_window_is_exactly_16_gib_inside_the_validated_partition(self):
        self.assertEqual(self.lib.window(FIRST, PARTITION, IMAGE_BLOCKS, DISK), 1)
        for args in ((5, PARTITION, IMAGE_BLOCKS, DISK), (FIRST, IMAGE_BLOCKS-1, IMAGE_BLOCKS, DISK),
                     (FIRST, PARTITION, IMAGE_BLOCKS+1, DISK), (FIRST, PARTITION, PARTITION, DISK),
                     (DISK, PARTITION, IMAGE_BLOCKS, DISK), (FIRST, DISK, IMAGE_BLOCKS, DISK),
                     (FIRST, PARTITION, IMAGE_BLOCKS, 1 << 32)):
            self.assertEqual(self.lib.window(*args), 0, args)

    def test_both_real_hfsx_headers_and_clean_primary_are_required(self):
        primary, alternate = header(), header(False)
        self.assertEqual(self.lib.hfs(bytes(primary), 512, bytes(alternate), 512), 1)
        self.assertEqual(self.lib.hfs(None, 512, bytes(alternate), 512), 0)
        self.assertEqual(self.lib.hfs(bytes(primary), 511, bytes(alternate), 512), 0)
        for which, offset, value in ((0, 0, b"H+\0\4"), (1, 0, b"HX\0\4"),
                (0, 4, struct.pack(">I", 0x2000)), (0, 4, struct.pack(">I", 0x2900)),
                (0, 4, struct.pack(">I", 0xa100)), (1, 4, struct.pack(">I", 0x2080)),
                (0, 12, bytes(4)), (1, 12, struct.pack(">I", 130)),
                (0, 40, struct.pack(">I", 2048)), (1, 44, struct.pack(">I", IMAGE_BLOCKS-1))):
            items = [primary.copy(), alternate.copy()]
            items[which][offset:offset+len(value)] = value
            self.assertEqual(self.lib.hfs(bytes(items[0]), 512, bytes(items[1]), 512), 0)

    def test_exact_write10_and_flush_allowlist_cannot_escape_the_image(self):
        def cdb(lba, count):
            return b"\x2a\0" + struct.pack(">I", lba) + b"\0" + struct.pack(">H", count) + b"\0"
        def allowed(c, length, write=True, armed=True, lun=0):
            return self.lib.command(c, len(c), length, write, lun, armed,
                                    FIRST, PARTITION, IMAGE_BLOCKS, DISK)
        for lba, count in ((FIRST, 1), (FIRST+IMAGE_BLOCKS-1, 1), (FIRST+IMAGE_BLOCKS-256, 256)):
            self.assertEqual(allowed(cdb(lba, count), count*BLOCK), 1)
        for lba, count in ((FIRST-1, 1), (FIRST+IMAGE_BLOCKS-1, 2),
                           (FIRST+IMAGE_BLOCKS, 1), (FIRST, 0), (FIRST, 257), (0xffffffff, 1)):
            self.assertEqual(allowed(cdb(lba, count), count*BLOCK), 0)
        good = cdb(FIRST, 1)
        for args in ((good, BLOCK, False), (good, BLOCK, True, False), (good, BLOCK, True, True, 1),
                     (good, 512), (good[:-1], BLOCK)):
            self.assertEqual(allowed(*args), 0)
        for position in (0, 1, 6, 9):
            bad = bytearray(good); bad[position] ^= 1
            self.assertEqual(allowed(bytes(bad), BLOCK), 0)
        sync = b"\x35" + bytes(9)
        self.assertEqual(allowed(sync, 0, False), 1)
        self.assertEqual(allowed(sync, 0, True), 0)
        self.assertEqual(allowed(sync, BLOCK, False), 0)
        for position in range(1, 10):
            bad = bytearray(sync); bad[position] = 1
            self.assertEqual(allowed(bytes(bad), 0, False), 0)

    def test_exact_response_rejects_partial_wrong_or_error_completions(self):
        packet = bytearray(512)
        packet[0], packet[3] = 0x21, 42
        for exception in (0, 1):
            for segment in (0, 2):
                packet[9], packet[11] = exception, segment
                self.assertEqual(self.lib.response(bytes(packet), 512, 0, 0, 42), 1)
        packet[9] = packet[11] = 0
        for position in list(range(0, 9)) + list(range(10, 34)):
            bad = packet.copy(); bad[position] ^= 0xff
            self.assertEqual(self.lib.response(bytes(bad), 512, 0, 0, 42), 0, position)
        for flags in (0x20, 0x40, 0x60):
            bad = packet.copy(); bad[1] = flags
            self.assertEqual(self.lib.response(bytes(bad), 512, 0, 0, 42), 0)
        self.assertEqual(self.lib.response(bytes(packet), 512, 1, 0, 42), 0)
        self.assertEqual(self.lib.response(bytes(packet), 33, 0, 0, 42), 0)
        self.assertEqual(self.lib.response(None, 512, 0, 0, 42), 0)


HARNESS = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <assert.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define MIN(a,b) ((a)<(b)?(a):(b))
#define TRUE 1
typedef uintptr_t vm_offset_t;
typedef uint64_t addr64_t;
typedef unsigned dev_t;
typedef unsigned long u_long;
typedef char *caddr_t;
typedef uintptr_t event_t;
struct proc { int unused; };
struct uio { int unused; };
#define NSEC_PER_SEC 1000000000ULL
#define NSEC_PER_USEC 1000ULL
#define THREAD_UNINT 0
#define THREAD_WAITING 1
#define THREAD_CONTINUE_NULL 0
#define TIMEOUT_URGENCY_SYS_CRITICAL 0
#define B_READ 1
#define B_WRITE 0
#define B_FUA 2
#define DEV_BSIZE 512
#define INT_MAX 2147483647
#define DKIOCGETBLOCKSIZE 1
#define DKIOCSETBLOCKSIZE 2
#define DKIOCGETPHYSICALBLOCKSIZE 3
#define DKIOCGETBLOCKCOUNT 4
#define DKIOCISWRITABLE 5
#define DKIOCSYNCHRONIZE 6
#define DKIOCSYNCHRONIZECACHE 7
#define DKIOCGETMAXBLOCKCOUNTREAD 8
#define DKIOCGETMAXBLOCKCOUNTWRITE 9
#define DKIOCGETMAXSEGMENTCOUNTREAD 10
#define DKIOCGETMAXSEGMENTCOUNTWRITE 11
ACTUAL_DEFINES
ACTUAL_STRUCTS
static struct {
    uintptr_t regs,dma; uint64_t dma_pa,nblocks,first_block;
    uint32_t secsize; uint8_t lun,tag; bool writable,cache,wait,ready;
} su;
static bool redfin_ufs_root_read_only,redfin_ufs_read_only,redfin_ufs_wake_active;
static bool redfin_ufs_capacity_valid,redfin_ufs_rw_armed,redfin_ufs_rw_preparing;
static bool redfin_ufs_submit_poisoned;
static uint64_t redfin_ufs_root_blocks,redfin_ufs_partition_blocks,gpt_alt;
static int sweet_ufs_lock;
struct buffer { unsigned flags,count,resid; int error,done; char *data; };
typedef struct buffer *buf_t;
static unsigned char dma[DMA_SIZE],disk[2*BOUNCE_SIZE+2*UFS_BLOCK],input[sizeof(disk)];
static unsigned char primary[512],alternate[512];
static uint32_t regs[64];
struct result { int error,poison,armed,preparing,ready,writable,commands,reads,writes,flushes,
    invalid,locks,unlocks,depth,cleans,barriers,physios; uint32_t resid; uint64_t nblocks; };
static struct result result;
static int mode,prepare_mode;
static unsigned clean_mask;
static unsigned cache_generation,barrier_generation;
static uint64_t ticks;
static int mock_printf(const char *format,...) { (void)format; return 0; }
#define printf mock_printf
#undef bzero
#define bzero(p,n) memset((p),0,(n))
static unsigned buf_flags(buf_t b){return b->flags;}
static int64_t buf_blkno(buf_t b){return (int64_t)(uintptr_t)b->data;}
static unsigned buf_count(buf_t b){return b->count;}
static void buf_setresid(buf_t b,unsigned n){b->resid=n;}
static int buf_map(buf_t b,char **out){(void)b; *out=(char *)input; return 0;}
static void buf_unmap(buf_t b){(void)b;}
static void buf_seterror(buf_t b,int error){b->error=error;}
static void buf_biodone(buf_t b){b->done++;}
static int buf_fua(buf_t b){return !!(b->flags & B_FUA);}
static void redfin_rw_poison(void);
static void lck_mtx_lock(int *lock){
    (void)lock;if(result.depth)result.invalid++;result.depth++;result.locks++;
    /* Another request can fail while this writer is waiting for the lock,
     * after its initial su.writable check has already succeeded. */
    if(mode==13)redfin_rw_poison();
}
static void lck_mtx_unlock(int *lock){(void)lock; if(result.depth!=1)result.invalid++;result.depth--;result.unlocks++;}
static void flush_dcache64(uint64_t address,unsigned n,int physical) {
    if (!physical || address<su.dma_pa || n>DMA_SIZE || address-su.dma_pa>DMA_SIZE-n ||
        redfin_ufs_submit_poisoned) result.invalid++;
    unsigned off=(unsigned)(address-su.dma_pa);
    if(off==DMA_UTRL)clean_mask|=1;
    if(off==DMA_UCD)clean_mask|=2;
    if(off==DMA_BOUNCE)clean_mask|=4;
    result.cleans++;
    cache_generation++;
}
static void clean_dcache64(uint64_t a,unsigned n,int p){flush_dcache64(a,n,p);}
static void host_dsb(unsigned kind){(void)kind;result.barriers++;barrier_generation=cache_generation;}
#define __builtin_arm_dsb(x) host_dsb(x)
static uint32_t ufs_rd(uint32_t off){return regs[off/4];}
static uint32_t get_be32(const uint8_t *p){return (uint32_t)p[0]<<24|(uint32_t)p[1]<<16|(uint32_t)p[2]<<8|p[3];}
static void ufs_wr(uint32_t off,uint32_t value) {
    if(off==REG_IS){regs[off/4]=0;return;}
    if(off!=REG_UTRLDBR){regs[off/4]=value;return;}
    if(result.depth!=1 || redfin_ufs_submit_poisoned || value!=1)result.invalid++;
    struct utrd *t=(struct utrd *)(dma+DMA_UTRL);
    struct ucd *c=(struct ucd *)(dma+DMA_UCD);
    unsigned len=get_be32(c->cmd+12),opcode=c->cmd[16];
    uint64_t lba=get_be32(c->cmd+18), address=su.dma_pa+DMA_BOUNCE;
    unsigned blocks=(unsigned)c->cmd[23]<<8|c->cmd[24];
    if((clean_mask & (len?7:3))!=(len?7u:3u) || !result.barriers || barrier_generation!=cache_generation ||
        ((uint64_t)t->ucdbau<<32|t->ucdba)!=su.dma_pa+DMA_UCD)result.invalid++;
    unsigned transferred=0;
    for(unsigned i=0;i<(t->prdt&0xffff);i++){
        unsigned chunk=c->prdt[i].dbc+1;
        if(((uint64_t)c->prdt[i].addr_hi<<32|c->prdt[i].addr_lo)!=address+transferred ||
            !chunk || chunk>PRDT_CHUNK)result.invalid++;
        transferred+=chunk;
    }
    if(transferred!=len)result.invalid++;
    result.commands++;
    if(opcode==0x28)result.reads++;else if(opcode==0x2a)result.writes++;
    else if(opcode==0x35)result.flushes++;else result.invalid++;
    if(opcode!=0x35){
        if(lba<su.first_block || blocks*UFS_BLOCK!=len)result.invalid++;
        uint64_t offset=(lba-su.first_block)*UFS_BLOCK;
        if(prepare_mode && opcode==0x28){
            memset(dma+DMA_BOUNCE,0,len);
            if(lba==su.first_block)memcpy(dma+DMA_BOUNCE+1024,primary,512);
            else if(lba==su.first_block+REDFIN_RW_BLOCKS-1)memcpy(dma+DMA_BOUNCE+UFS_BLOCK-1024,alternate,512);
            else result.invalid++;
        } else if(offset>sizeof(disk) || len>sizeof(disk)-offset)result.invalid++;
        else if(opcode==0x28){
            if(c->cmd[1]!=0x40 || ((t->dw0>>25)&3)!=2)result.invalid++;
            memcpy(dma+DMA_BOUNCE,disk+offset,len);
        } else {
            if(c->cmd[1]!=0x20 || ((t->dw0>>25)&3)!=1)result.invalid++;
            memcpy(disk+offset,dma+DMA_BOUNCE,len);
        }
    }else if(len || c->cmd[1] || ((t->dw0>>25)&3))result.invalid++;
    memset(c->resp,0,sizeof(c->resp));c->resp[0]=0x21;c->resp[2]=su.lun;c->resp[3]=su.tag;
    c->resp[9]=1;c->resp[11]=2; /* Valid EE flag and empty sense-length segment. */
    t->dw2=0;regs[REG_UTRLDBR/4]=0;
    if(mode==1 && opcode==0x2a)regs[REG_UTRLDBR/4]=1;
    if(mode==2 && (opcode==0x2a || prepare_mode))c->resp[3]^=1;
    if(mode==3 && (opcode==0x2a || prepare_mode))c->resp[15]=1;
    if(mode==4 && opcode==0x2a)t->dw2=1;
    if(mode==5 && opcode==0x35)c->resp[7]=2;
    if(mode==6 && opcode==0x28)c->resp[2]=1;
    if(mode==9)regs[0x78/4]=1;
    clean_mask=0;
}
static void delay(unsigned n){(void)n;}
static void nanoseconds_to_absolutetime(uint64_t ns,uint64_t *out){(void)ns;*out=10;}
static uint64_t mach_absolute_time(void){return ++ticks;}
static int ml_get_interrupts_enabled(void){return 1;}
static int ml_at_interrupt_context(void){return 0;}
static int get_preemption_level(void){return 0;}
static int assert_wait_deadline_with_leeway(event_t e,int a,int b,uint64_t d,int l){
    (void)e;(void)a;(void)b;(void)d;(void)l;result.invalid++;return 0;
}
static void thread_block(int n){(void)n;result.invalid++;}
static void redfin_ufs_response_metadata(const uint8_t *p,unsigned n){(void)p;(void)n;}
static void minphys(buf_t b){(void)b;}
static int physio(void (*fn)(buf_t),void *p,dev_t d,int f,void (*m)(buf_t),struct uio *u,int s){
    (void)fn;(void)p;(void)d;(void)f;(void)m;(void)u;(void)s;result.physios++;return 0;
}
ACTUAL_FUNCTIONS
static void snapshot(void){
    result.poison=redfin_ufs_submit_poisoned;result.armed=redfin_ufs_rw_armed;
    result.preparing=redfin_ufs_rw_preparing;result.ready=su.ready;result.writable=su.writable;
    result.nblocks=su.nblocks;
}
static void reset(int failure){
    memset(&su,0,sizeof(su));memset(&result,0,sizeof(result));memset(regs,0,sizeof(regs));
    memset(dma,0xa5,sizeof(dma));
    for(unsigned i=0;i<sizeof(disk);i++){disk[i]=(uint8_t)((i*17)^(i>>8));input[i]=(uint8_t)(disk[i]+83);}
    su.dma=(uintptr_t)dma;su.dma_pa=0x180000000ULL;su.nblocks=REDFIN_RW_BLOCKS;
    su.first_block=4096;su.secsize=1;su.ready=su.writable=true;
    redfin_ufs_root_read_only=redfin_ufs_read_only=redfin_ufs_rw_armed=true;
    redfin_ufs_wake_active=redfin_ufs_capacity_valid=false;
    redfin_ufs_rw_preparing=redfin_ufs_submit_poisoned=false;
    redfin_ufs_partition_blocks=0x800000;redfin_ufs_root_blocks=0x1000000;gpt_alt=redfin_ufs_root_blocks-1;
    regs[REG_HCE/4]=regs[REG_UTRLRSR/4]=1;regs[REG_HCS/4]=0xf;
    regs[REG_UTRLBA/4]=(uint32_t)su.dma_pa;regs[REG_UTRLBAU/4]=(uint32_t)(su.dma_pa>>32);
    mode=failure;prepare_mode=0;clean_mask=cache_generation=barrier_generation=0;ticks=0;
    if(mode==7)regs[REG_UTRLDBR/4]=1;
    if(mode==8)regs[REG_UTRLBAU/4]^=1;
    if(mode==10)regs[REG_HCE/4]=0;
    if(mode==11)regs[REG_UTRLRSR/4]=0;
    if(mode==12)regs[REG_HCS/4]=0;
}
int host_run(uint64_t offset,unsigned count,int read,int fua,int failure,struct result *out){
    reset(failure);
    struct buffer b={(read?B_READ:0)|(fua?B_FUA:0),count,0,0,0,(char *)(uintptr_t)offset};
    sweet_ufs_strategy(&b);result.error=b.error;result.resid=b.resid;
    if(!result.commands)for(unsigned i=0;i<sizeof(dma);i++)if(dma[i]!=0xa5){result.invalid++;break;}
    if(b.done!=1)result.invalid++;
    snapshot();*out=result;return b.error;
}
int host_copy_disk(unsigned off,unsigned n,uint8_t *out){
    if(off>sizeof(disk)||n>sizeof(disk)-off)return EINVAL;
    memcpy(out,disk+off,n);return 0;
}
int host_bad_geometry(uint64_t block,unsigned sector,struct result *out){
    reset(0);su.secsize=sector;
    struct buffer b={0,512,0,0,0,(char *)(uintptr_t)block};
    sweet_ufs_strategy(&b);result.error=b.error;result.resid=b.resid;
    snapshot();*out=result;return b.error;
}
int host_sync(void){return sweet_ufs_ioctl(0,DKIOCSYNCHRONIZECACHE,NULL,0,NULL,0);}
int host_raw_write(void){struct uio u;return sweet_ufs_write(0,&u,0);}
int host_ro_write(struct result *out){
    reset(0);redfin_ufs_rw_armed=su.writable=false;
    uint8_t cdb[10]={0x2a,0,0,0,0x10,0,0,0,1,0};
    lck_mtx_lock(&sweet_ufs_lock);int error=ufs_scsi(cdb,10,UFS_BLOCK,true);lck_mtx_unlock(&sweet_ufs_lock);
    snapshot();*out=result;return error;
}
int host_retry(struct result *out){
    unsigned char old[DMA_SIZE];memcpy(old,dma,sizeof(old));int cleans=result.cleans;
    regs[REG_UTRLDBR/4]=regs[0x78/4]=0;mode=0;
    struct buffer b={B_READ,512,0,0,0,NULL};sweet_ufs_strategy(&b);
    if(memcmp(old,dma,sizeof(old)) || cleans!=result.cleans)result.invalid++;
    snapshot();*out=result;return b.error;
}
int host_prepare(const uint8_t *p,const uint8_t *a,int failure,struct result *out){
    reset(failure);su.writable=su.ready=false;su.nblocks=redfin_ufs_partition_blocks;
    redfin_ufs_rw_armed=false;prepare_mode=1;memcpy(primary,p,512);memcpy(alternate,a,512);
    lck_mtx_lock(&sweet_ufs_lock);int error=redfin_rw_prepare();lck_mtx_unlock(&sweet_ufs_lock);
    result.error=error;snapshot();*out=result;return error;
}
'''


class Result(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int) for name in (
        "error", "poison", "armed", "preparing", "ready", "writable", "commands", "reads", "writes",
        "flushes", "invalid", "locks", "unlocks", "depth", "cleans", "barriers", "physios")]
    _fields_ += [("resid", ctypes.c_uint32), ("nblocks", ctypes.c_uint64)]


class ActualRWPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which("cc")
        if not cc:
            raise unittest.SkipTest("host compiler unavailable")
        source = patched_source()
        defines = "\n".join(line for line in source.splitlines() if line.startswith("#define ") and
                            line.split()[1] in {"UFS_BLOCK", "BOUNCE_SIZE", "PRDT_CHUNK", "PRDT_MAX",
                                "DMA_UTRL", "DMA_UCD", "DMA_BOUNCE", "DMA_SIZE", "CMD_TIMEOUT_NS",
                                "CMD_SPIN_NS", "CMD_SLEEP_NS", "REG_IS", "REG_UTRLBA", "REG_UTRLBAU",
                                "REG_UTRLDBR", "REG_UTRLCLR", "REG_UTRLRSR", "REG_HCE", "REG_HCS",
                                "REDFIN_RW_BLOCKS"})
        structs = source.split("struct utrd {", 1)[1].split("/* Layout of the contiguous", 1)[0]
        functions = section(source, "REDFIN_RW_TEST") + "\n" + function(source, "redfin_root_read_allowed")
        functions += "\n" + section(source, "REDFIN_RW_IO_TEST")
        for name in ("dma_sync", "dma_clean", "ufs_scsi", "ufs_read_blocks", "ufs_write_blocks",
                     "ufs_sync_cache", "sweet_ufs_strategy", "sweet_ufs_ioctl", "sweet_ufs_write",
                     "redfin_rw_prepare"):
            functions += "\n" + function(source, name)
        # The production flag helper is tested separately; the real I/O body
        # never calls it and would otherwise trigger -Wunused-function.
        functions += "\nint host_flags(uint32_t a,uint32_t b,uint32_t c,bool *o){return redfin_rw_flags(a,b,c,o);}\n"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        path, library = Path(cls.tmp.name) / "pipeline.c", Path(cls.tmp.name) / "pipeline.so"
        path.write_text(HARNESS.replace("ACTUAL_DEFINES", defines).replace(
            "ACTUAL_STRUCTS", "struct utrd {" + structs).replace("ACTUAL_FUNCTIONS", functions))
        subprocess.run([cc, "-shared", "-fPIC", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(path), "-o", str(library)], check=True)
        cls.lib = ctypes.CDLL(str(library))
        cls.lib.host_run.argtypes = [ctypes.c_uint64, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.POINTER(Result)]
        cls.lib.host_prepare.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                        ctypes.POINTER(Result)]
        cls.lib.host_retry.argtypes = [ctypes.POINTER(Result)]
        cls.lib.host_ro_write.argtypes = [ctypes.POINTER(Result)]
        cls.lib.host_copy_disk.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
        cls.lib.host_bad_geometry.argtypes = [ctypes.c_uint64, ctypes.c_uint, ctypes.POINTER(Result)]

    def run_io(self, offset, count, read=False, fua=False, failure=0):
        result = Result()
        error = self.lib.host_run(offset, count, read, fua, failure, ctypes.byref(result))
        self.assertEqual(result.invalid, 0, "MMIO/DMA/cache ordering or buffer invariant failed")
        self.assertEqual(result.depth, 0)
        self.assertEqual(result.locks, result.unlocks)
        return error, result

    def disk(self, offset, count):
        out = ctypes.create_string_buffer(count)
        self.assertEqual(self.lib.host_copy_disk(offset, count, out), 0)
        return out.raw

    def test_partial_block_write_preserves_neighbours_and_flushes_fua(self):
        error, result = self.run_io(3, 4096, fua=True)
        self.assertEqual((error, result.resid, result.reads, result.writes, result.flushes), (0, 0, 1, 1, 1))
        original = bytes(((i*17)^(i>>8)) & 255 for i in range(2*BLOCK))
        expected = original[:3] + bytes((x+83) & 255 for x in original[:4096]) + original[4099:]
        self.assertEqual(self.disk(0, 2*BLOCK), expected)

    def test_multiple_chunks_keep_high_pa_prdt_and_write_flush_order(self):
        error, result = self.run_io(0, BOUNCE+BLOCK, fua=True)
        self.assertEqual((error, result.resid, result.reads, result.writes, result.flushes), (0, 0, 0, 2, 2))
        self.assertEqual(result.commands, 4)
        self.assertEqual(self.lib.host_raw_write(), errno.EROFS)

    def test_default_read_only_fence_still_rejects_writes_and_sync_is_a_noop(self):
        result = Result()
        self.assertEqual(self.lib.host_ro_write(ctypes.byref(result)), errno.EROFS)
        self.assertEqual((result.commands, result.armed, result.writable, result.invalid), (0, 0, 0, 0))
        self.assertEqual(self.lib.host_sync(), 0)
        self.assertEqual(self.lib.host_raw_write(), errno.EROFS)

    def test_exact_image_end_and_empty_requests_never_submit_out_of_bounds(self):
        for offset, count in ((IMAGE_BLOCKS*BLOCK, 1), (IMAGE_BLOCKS*BLOCK-1, 2)):
            error, result = self.run_io(offset, count)
            self.assertEqual(error, errno.EINVAL)
            self.assertEqual(result.commands, 0)
        error, result = self.run_io(0, 0)
        self.assertEqual((error, result.commands), (0, 0))

    def test_negative_and_overflowing_block_offsets_cannot_wrap_into_the_image(self):
        for block, sector in ((1 << 63, 512), (1 << 55, 512), (1, 0)):
            result = Result()
            self.assertEqual(self.lib.host_bad_geometry(block, sector, ctypes.byref(result)), errno.EINVAL)
            self.assertEqual((result.commands, result.invalid, result.resid), (0, 0, 512))

    def test_uncertain_or_wrong_completion_poison_all_reuse_and_flush(self):
        for mode in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13):
            with self.subTest(mode=mode):
                # Unaligned writes include an initial READ, exercising failed
                # RMW reads as well as write and durability failures.
                error, result = self.run_io(0 if mode in (1, 2, 3, 4, 5) else 3,
                                             BLOCK, fua=True, failure=mode)
                self.assertNotEqual(error, 0)
                self.assertEqual((result.poison, result.armed, result.ready, result.writable), (1, 0, 0, 0))
                self.assertEqual(result.resid, BLOCK)
                self.assertEqual(self.lib.host_sync(), errno.EIO)
                again = Result()
                self.assertEqual(self.lib.host_retry(ctypes.byref(again)), errno.EIO)
                self.assertEqual(again.commands, result.commands)
                self.assertEqual(again.invalid, 0, "poisoned DMA/bounce memory was reused")

    def test_hfs_proof_reads_are_strict_before_rw_is_armed(self):
        for mode in (0, 2, 3, 6):
            result = Result()
            error = self.lib.host_prepare(bytes(header()), bytes(header(False)), mode, ctypes.byref(result))
            self.assertEqual(result.invalid, 0)
            self.assertEqual((result.armed, result.preparing, result.writable, result.writes), (0, 0, 0, 0))
            if mode == 0:
                self.assertEqual((error, result.reads, result.nblocks), (0, 2, IMAGE_BLOCKS))
            else:
                self.assertNotEqual(error, 0)
                self.assertEqual((result.poison, result.reads), (1, 1))
        result = Result()
        error = self.lib.host_prepare(bytes(header(False)), bytes(header(False)), 0, ctypes.byref(result))
        self.assertEqual(error, errno.EINVAL)
        self.assertEqual(result.nblocks, PARTITION)


if __name__ == "__main__":
    unittest.main()
