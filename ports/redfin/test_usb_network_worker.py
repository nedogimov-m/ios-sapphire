"""Actual USB network/log handlers: revocation, bounded sockets and cleanup."""
import ctypes as C
import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin import test_usb_gadget as gadget
from ports.redfin.test_touch_events import function
from ports.redfin.test_usb_owned_route import added_file

HERE = Path(__file__).resolve().parent

PREFIX = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <setjmp.h>
#include <stdarg.h>
#define ETHER_ADDR_LEN 6
#define ETHER_HDR_LEN 14
#define ETHER_MAX_LEN 1518
#define ETHER_CRC_LEN 4
#define ETHERMTU 1500
#define UD_TXQ 32
#define MBUF_DONTWAIT 0
#define MBUF_TYPE_DATA 1
#define MBUF_EXT 1
#define LCK_GRP_ATTR_NULL 0
#define LCK_ATTR_NULL 0
#define IFNET_INIT_CURRENT_VERSION 1
#define IFNET_INIT_LEGACY 1
#define IFNET_FAMILY_ETHERNET 1
#define IFT_ETHER 1
#define IFF_UP 1
#define IFF_RUNNING 2
#define IFF_BROADCAST 4
#define IFF_SIMPLEX 8
#define IFF_MULTICAST 16
#define AF_INET 2
#define PF_INET 2
#define SOCK_DGRAM 2
#define IPPROTO_UDP 17
#define MSG_DONTWAIT 0x80
#define FIONBIO 0x8004667eu
#define SIOCSIFADDR 1
#define SIOCAIFADDR 2
#define SIOCSIFFLAGS 3
#define SIOCADDMULTI 4
#define SIOCDELMULTI 5
#define htons(v) ((uint16_t)(v))
#define htonl(v) ((uint32_t)(v))
#ifndef bzero
#define bzero(p,n) memset((p),0,(n))
#endif
typedef int errno_t,lck_grp_t,lck_mtx_t;
typedef struct model_ifnet { unsigned flags; } *ifnet_t;
typedef struct model_mbuf {
 unsigned id,freed,flags;size_t len,packet,offset;uint8_t data[2048];
} *mbuf_t;
typedef void *socket_t;
struct in_addr { uint32_t s_addr; };
struct sockaddr { uint8_t sa_len,sa_family;char data[14]; };
struct sockaddr_in { uint8_t sin_len,sin_family;uint16_t sin_port;struct in_addr sin_addr;char zero[8]; };
struct ifaliasreq { char ifra_name[16];struct sockaddr ifra_addr,ifra_mask,ifra_broadaddr; };
struct ether_header { uint8_t bytes[14]; };
struct iovec { void *iov_base;size_t iov_len; };
struct msghdr { void *msg_name;unsigned msg_namelen;struct iovec *msg_iov;unsigned msg_iovlen; };
struct ifnet_stat_increment_param { uint64_t packets_in,bytes_in; };
struct ifnet_init_eparams {
 unsigned ver,len,flags,uniqueid_len,unit,family,type,broadcast_len;
 const char *uniqueid,*name;const void *broadcast_addr;
 errno_t (*output)(ifnet_t,mbuf_t);
 errno_t (*ioctl)(ifnet_t,unsigned long,void *);
 void (*detach)(ifnet_t);
 void *demux,*add_proto,*del_proto,*check_multi,*framer_extended;
};
static void *ether_demux,*ether_add_proto,*ether_del_proto,*ether_check_multi,*ether_frameout_extended;
static const uint8_t etherbroadcastaddr[6]={255,255,255,255,255,255};
static struct model_ifnet model_interface;
static struct model_mbuf pool[128];
static lck_grp_t model_group;static lck_mtx_t model_mutex;
static unsigned worker_fault,lock_depth,group_allocs,lock_allocs,interface_allocs,interface_attaches;
static unsigned interface_down,interface_up,packet_allocs,packet_frees,packet_copies,packet_deliveries;
static unsigned socket_opens,socket_closes,socket_sends,last_send_flags,sync_expire_at;
static unsigned socket_nb_calls,socket_nb_state,last_send_nb;
static unsigned tx_expire_on_lock,log_expire_on_copy,log_bytes,log_copies,legacy_abort;
static unsigned dma_frees,if_releases,expired_delivery,failed_data_access;
static void ud_log_thread(void *,int);
static void ud_if_create(void);
'''

KPI = r'''
static lck_grp_t *lck_grp_alloc_init(const char *name,unsigned attr){
 (void)name;(void)attr;group_allocs++;return worker_fault==1?NULL:&model_group;
}
static lck_mtx_t *lck_mtx_alloc_init(lck_grp_t *group,unsigned attr){
 (void)attr;lock_allocs++;if(!group)violations++;
 return worker_fault==2?NULL:&model_mutex;
}
static void lck_mtx_lock(lck_mtx_t *lock){
 if(!lock || lock_depth++)violations++;
 if(tx_expire_on_lock){tx_expire_on_lock=0;now=ud.guard.deadline;}
}
static void lck_mtx_unlock(lck_mtx_t *lock){if(!lock || !lock_depth)violations++;else lock_depth--;}
static int ifnet_allocate_extended(const struct ifnet_init_eparams *init,ifnet_t *out){
 interface_allocs++;
 if(!ud.lock || init->output==NULL || init->ioctl==NULL || init->detach==NULL)violations++;
 if(worker_fault==3)return ENOMEM;*out=&model_interface;return 0;
}
static int ifnet_attach(ifnet_t ifp,void *arg){
 (void)arg;interface_attaches++;if(!ifp || !ud.lock)violations++;
 return worker_fault==4?EIO:0;
}
static __attribute__((unused)) void ifnet_release(ifnet_t ifp){(void)ifp;if_releases++;}
static void ifnet_set_flags(ifnet_t ifp,unsigned flags,unsigned mask){
 if(!ifp){violations++;return;}
 if((mask&IFF_RUNNING) && !(flags&IFF_RUNNING))interface_down++;
 if((flags&(IFF_UP|IFF_RUNNING))==(IFF_UP|IFF_RUNNING))interface_up++;
 ifp->flags=(ifp->flags&~mask)|(flags&mask);
}
static void ifnet_set_addrlen(ifnet_t p,unsigned n){(void)p;(void)n;}
static void ifnet_set_hdrlen(ifnet_t p,unsigned n){(void)p;(void)n;}
static void ifnet_set_mtu(ifnet_t p,unsigned n){(void)p;(void)n;}
static void ifnet_set_baudrate(ifnet_t p,uint64_t n){(void)p;(void)n;}
static void ifnet_set_lladdr(ifnet_t p,const void *a,unsigned n){(void)p;(void)a;(void)n;}
static int proto_plumb(unsigned family,ifnet_t p){(void)family;(void)p;return worker_fault==8?ENXIO:0;}
static int sock_socket(unsigned family,unsigned type,unsigned proto,void *a,void *b,socket_t *out){
 (void)a;(void)b;if(family!=PF_INET || type!=SOCK_DGRAM)violations++;
 socket_opens++;if(worker_fault==5)return EAGAIN;
 if(proto==IPPROTO_UDP)socket_nb_state=0;
 *out=proto==IPPROTO_UDP?(void *)2:(void *)1;return 0;
}
static int sock_ioctl(socket_t so,unsigned command,void *arg){
 if(command==FIONBIO){
  socket_nb_calls++;
  if(so!=(void *)2 || !arg || *(int *)arg!=1)violations++;
  if(worker_fault==10)return ENOTSUP;
  socket_nb_state=1;return 0;
 }
 if(command!=SIOCAIFADDR || so!=(void *)1 || !arg)violations++;
 return worker_fault==9?EINVAL:0;
}
static int sock_close(socket_t so){if(!so)violations++;socket_closes++;return 0;}
static int sock_send(socket_t so,const struct msghdr *msg,int flags,size_t *sent){
 if(!so || !msg || msg->msg_iovlen!=1 || msg->msg_iov[0].iov_len>1400)violations++;
 socket_sends++;last_send_flags=(unsigned)flags;last_send_nb=socket_nb_state;
 if(ud.guard.redfin && (now>=ud.guard.deadline || ud.guard.error))violations++;
 if(ud.guard.redfin && (flags!=MSG_DONTWAIT || !socket_nb_state))violations++;
 *sent=worker_fault==6?0:msg->msg_iov[0].iov_len;
 if(legacy_abort)longjmp(finished,1);
 return worker_fault==6?EWOULDBLOCK:0;
}
uint64_t sweet_log_position(void){return log_bytes;}
uint32_t sweet_log_copy(uint64_t *position,char *out,uint32_t max){
 log_copies++;unsigned n=*position>=log_bytes?0:log_bytes-(unsigned)*position;
 if(n>max)n=max;memset(out,'L',n);*position+=n;
 if(n && log_expire_on_copy)now=ud.guard.deadline;
 return n;
}
static mbuf_t new_packet(size_t bytes){
 if(packet_allocs>=128 || bytes>2048){violations++;return NULL;}
 mbuf_t m=&pool[packet_allocs];memset(m,0,sizeof(*m));m->id=++packet_allocs;
 m->len=m->packet=bytes;m->flags=MBUF_EXT;memset(m->data,0x5a,bytes);return m;
}
static void mbuf_freem(mbuf_t m){
 if(!m || m->freed){violations++;return;}m->freed=1;packet_frees++;
}
static int mbuf_gethdr(unsigned wait,unsigned type,mbuf_t *out){
 (void)wait;(void)type;*out=new_packet(0);
 if(worker_fault==7)now=ud.guard.deadline;
 return *out?0:ENOMEM;
}
static int mbuf_mclget(unsigned wait,unsigned type,mbuf_t *out){(void)wait;(void)type;return *out?0:ENOMEM;}
static unsigned mbuf_flags(mbuf_t m){return m->flags;}
static size_t mbuf_maxlen(mbuf_t m){return sizeof(m->data)-m->offset;}
static void *mbuf_data(mbuf_t m){return m->data+m->offset;}
static size_t mbuf_len(mbuf_t m){return m->len;}
static size_t mbuf_pkthdr_len(mbuf_t m){return m->packet;}
static void mbuf_setlen(mbuf_t m,size_t n){m->len=n;}
static void mbuf_pkthdr_setlen(mbuf_t m,size_t n){m->packet=n;}
static void mbuf_pkthdr_setrcvif(mbuf_t m,ifnet_t p){(void)m;(void)p;}
static void mbuf_pkthdr_setheader(mbuf_t m,void *p){(void)m;(void)p;}
static void mbuf_pkthdr_adjustlen(mbuf_t m,int n){m->packet=(size_t)((int)m->packet+n);}
static int mbuf_setdata(mbuf_t m,void *p,size_t n){
 m->offset=(uint8_t *)p-m->data;m->len=n;
 if(m->offset+n>sizeof(m->data))violations++;return 0;
}
static int mbuf_copydata(mbuf_t m,size_t off,size_t n,void *out){
 packet_copies++;
 if(ud.guard.redfin && (now>=ud.guard.deadline || ud.guard.error))failed_data_access++;
 if(m->freed || off+n>m->len || out!=(void *)(ud.dma+0x2800) || n>0x800)violations++;
 memcpy(out,m->data+m->offset+off,n);return 0;
}
static void ifnet_input(ifnet_t ifp,mbuf_t m,struct ifnet_stat_increment_param *stats){
 if(ifp!=ud.ifp || stats->packets_in!=1 || stats->bytes_in>1518)violations++;
 if(ud.guard.redfin && (now>=ud.guard.deadline || ud.guard.error))expired_delivery++;
 packet_deliveries++;mbuf_freem(m);
}
static void ifnet_stat_increment_out(ifnet_t p,unsigned a,size_t b,unsigned c){(void)p;(void)a;(void)b;(void)c;}
static __attribute__((unused)) void kmem_free(void *map,uintptr_t address,size_t size){
 (void)map;(void)address;(void)size;dma_frees++;
}
'''

HARNESS = r'''
void worker_reset(unsigned fault,unsigned redfin){
 worker_fault=fault;issue=0;now=0;physical=0xb3000000;
 reads=stores=cache_ops=allocs=violations=core_reads=cmd_reads=threads=0;
 warm_calls=active_calls=quiesce_calls=delays=0;
 lock_depth=group_allocs=lock_allocs=interface_allocs=interface_attaches=interface_down=interface_up=0;
 packet_allocs=packet_frees=packet_copies=packet_deliveries=0;
 socket_opens=socket_closes=socket_sends=last_send_flags=sync_expire_at=0;
 socket_nb_calls=socket_nb_state=last_send_nb=0;
 tx_expire_on_lock=log_expire_on_copy=log_copies=legacy_abort=0;
 dma_frees=if_releases=expired_delivery=failed_data_access=0;log_bytes=1400;
 memset(&ud,0,sizeof(ud));memset(pool,0,sizeof(pool));memset(&model_interface,0,sizeof(model_interface));
 memset(core_regs,0,sizeof(core_regs));memset(dma_memory,0,sizeof(dma_memory));
 ud.guard=(struct rf_usb_gadget_guard){.redfin=redfin,.active=true,.caller=&token,
  .policy={authorize,&context_token},.deadline=350000000ull,
  .ram_base=0x80000000,.ram_size=0x200000000ull};
 ud.dma=(uintptr_t)dma_memory;ud.dma_pa=physical;ud.dwc=(uintptr_t)core_regs-0xc000;
 ud.ifp=&model_interface;ud.lock=&model_mutex;ud.configured=true;
 model_interface.flags=IFF_UP|IFF_RUNNING;run_seen=1;
 core_regs[0x704/4]=1u<<31;core_regs[0x70c/4]=0;
}
void worker_create(void){ud.ifp=NULL;ud.lock=NULL;ud_if_create();}
unsigned worker_start(void){
 ud.ifp=NULL;ud.lock=NULL;sweet_usb_gadget_start(ud.dwc);return (unsigned)ud.guard.error;
}
unsigned worker_log(unsigned expire_after_copy){
 log_expire_on_copy=expire_after_copy;legacy_abort=!ud.guard.redfin;
 if(!setjmp(finished))ud_log_thread(NULL,0);
 return (unsigned)ud.guard.error;
}
void worker_rx(unsigned expire_after_sync){
 sync_expire_at=expire_after_sync;
 ((uint32_t *)(dma_memory+0x1020))[2]=0x800-64;
 memset(dma_memory+0x2000,0xa5,64);ud_rx_done();
}
int worker_output(unsigned expire_on_lock,unsigned bytes){
 tx_expire_on_lock=expire_on_lock;
 return ud_if_output(ud.ifp,new_packet(bytes));
}
void worker_kick_expired(void){
 ud.txq[0]=new_packet(64);ud.txq_count=1;ud.tx_busy=false;
 now=ud.guard.deadline;lck_mtx_lock(ud.lock);ud_tx_kick_locked();lck_mtx_unlock(ud.lock);
}
void worker_queue(unsigned count){
 ud.tx_busy=true;ud.txq_head=29;
 for(unsigned i=0;i<count;i++){mbuf_t m=new_packet(64);(void)ud_if_output(ud.ifp,m);}
}
unsigned worker_stop(unsigned expire){
 if(expire){now=ud.guard.deadline;(void)ud_redfin_proof();}
 return ud_redfin_stop();
}
void worker_deny_halt(void){issue=3;}
void worker_enum_only(void){ud.guard.enum_only=true;ud.ifp=NULL;ud.lock=NULL;}
unsigned worker_stat(unsigned key){
 const unsigned values[]={violations,stores,reads,cache_ops,group_allocs,lock_allocs,
  interface_allocs,interface_attaches,interface_down,packet_allocs,packet_frees,
  packet_copies,packet_deliveries,socket_opens,socket_closes,socket_sends,last_send_flags,
  (unsigned)(now/1000000),ud.txq_count,ud.tx_busy,ud.configured,lock_depth,dma_frees,
  expired_delivery,failed_data_access,ud.guard.error,ud.ifp!=NULL,ud.lock!=NULL,if_releases,
  interface_up,core_reads,threads,socket_nb_calls,last_send_nb};
 return key<sizeof(values)/sizeof(values[0])?values[key]:0;
}
'''


class USBNetworkWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler required')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        before = gadget.patched_source(root)
        subprocess.run(['git', 'apply', str(HERE / 'usb-network-worker.patch')], cwd=root, check=True)
        after = (root / 'bsd/dev/sweet_usb.c').read_text()
        patch = (HERE / 'usb-gadget.patch').read_text()
        for name in ('redfin_usb_gadget.h', 'redfin_usb_gadget_guard.h'):
            (root / name).write_text(added_file(patch, 'bsd/dev/' + name))
        cls.libs = []
        for name, source in (('base', before), ('worker', after)):
            stub = gadget.STUB
            actual_ud = re.search(r'static struct \{.*?\n\} ud;', source, re.S).group()
            stub = re.sub(r'static struct \{.*?\n\} ud;', lambda _: actual_ud, stub, count=1, flags=re.S)
            stub = stub.replace('enum {EP0_SETUP};', '')
            stub = stub.replace('static void ud_if_create(void){netifs++;ud.ifp=(void *)1;ud.lock=(void *)1;}\n', '')
            stub = stub.replace('static void ud_log_thread(void *arg,int result){(void)arg;(void)result;logs++;}\n', '')
            stub = stub.replace('cache_ops++;if(!phys',
                                'cache_ops++;if(sync_expire_at==cache_ops)now=ud.guard.deadline;\n if(!phys')
            signatures = ['static bool\nud_redfin_proof(', 'static inline void\ndwc_wr(',
                          'static inline uint32_t\ndwc_rd(', 'static void\nud_sync(',
                          'static int\nud_epcmd(', 'static void\nud_start_trb(',
                          'static void\nud_start(', 'static void\nud_start_setup(',
                          'static void\nud_rx_arm(', 'static void\nud_rx_done(',
                          'static void\nud_tx_kick_locked(', 'static errno_t\nud_if_output(',
                          'static errno_t\nud_if_ioctl(', 'static void\nud_if_detach(',
                          'static void\nud_if_create(', 'static bool\nud_redfin_stop(',
                          'static void\nud_thread(', 'static void\nud_log_thread(',
                          'static void\nsweet_usb_gadget_start(']
            # Include runtime cleanup helpers added by the overlay, in source order.
            selected = [(source.index(signature), function(source, signature)) for signature in signatures]
            for match in re.finditer(r'static (?:void|bool)\n(ud_redfin_[a-z_]+)\(', source):
                signature = match.group()
                if match.group(1) != 'ud_redfin_proof':
                    body = function(source, signature)
                    if all(body != existing for _, existing in selected):
                        selected.append((match.start(), body))
            actual = '\n'.join(body for _, body in sorted(selected))
            actual = re.sub(r'__asm__ volatile\s*\([^;]*;', '(void)0;', actual)
            actual = actual.replace('*(volatile uint32_t *)(ud.dwc + off) = v;', 'model_write(ud.dwc,off,v);')
            actual = actual.replace('*(volatile uint32_t *)(ud.dwc+DCTL)=control&~DCTL_RUN_STOP;',
                                    'model_write(ud.dwc,DCTL,control&~DCTL_RUN_STOP);')
            macros = '\n'.join(line for line in source.splitlines() if line.startswith('#define'))
            data = re.search(r'static const uint8_t ud_phone_mac\[.*?\n', source).group()
            work = root / name
            work.mkdir()
            model = work / 'model.c'
            model.write_text(PREFIX + stub + '\n' + macros + '\n' + data + KPI + actual + HARNESS)
            library = work / 'model.so'
            result = subprocess.run([compiler, '-std=c11', '-shared', '-fPIC', '-O0',
                                     '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                                     '-Wno-unused-variable', '-I', str(root),
                                     str(model), '-o', str(library)], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            lib = C.CDLL(str(library))
            lib.worker_stat.restype = C.c_uint
            cls.libs.append(lib)
        cls.baseline, cls.lib = cls.libs

    def reset(self, fault=0, redfin=1, lib=None):
        lib = lib or self.lib
        lib.worker_reset(fault, redfin)
        return lib

    def clean(self, lib=None):
        lib = lib or self.lib
        self.assertEqual(lib.worker_stat(0), 0, 'invalid environment, MMIO, allocation or double free')
        self.assertEqual(lib.worker_stat(21), 0, 'network lock leaked')
        self.assertEqual(lib.worker_stat(22), 0, 'permanent DMA must never be freed')
        self.assertEqual(lib.worker_stat(23), 0, 'expired RX packet delivered')
        self.assertEqual(lib.worker_stat(24), 0, 'expired TX copied into DMA')

    def test_real_log_worker_nonblocking_send_deadline_and_socket_close(self):
        lib = self.reset()
        self.assertEqual(lib.worker_log(0), errno.ETIMEDOUT)
        self.assertEqual([lib.worker_stat(i) for i in (13, 14, 15, 16)], [1, 1, 1, 0x80])
        self.assertEqual([lib.worker_stat(i) for i in (32, 33)], [1, 1])
        self.assertLessEqual(lib.worker_stat(17), 450)
        self.clean()

    def test_would_block_socket_error_and_expiry_after_log_copy_are_bounded(self):
        for fault, expire, sends, closes in ((6, 0, 1, 1), (0, 1, 0, 1), (5, 0, 0, 0)):
            with self.subTest(fault=fault, expire=expire):
                lib = self.reset(fault)
                self.assertEqual(lib.worker_log(expire), errno.ETIMEDOUT)
                self.assertEqual(lib.worker_stat(15), sends)
                self.assertEqual(lib.worker_stat(14), closes)
                self.assertLessEqual(lib.worker_stat(17), 450)
                self.clean()

    def test_failed_fionbio_closes_socket_once_without_send_and_keeps_exact_errno(self):
        lib = self.reset(10)
        self.assertEqual(lib.worker_log(0), errno.ENOTSUP)
        self.assertEqual([lib.worker_stat(i) for i in (13, 14, 15, 32)], [1, 1, 0, 1])
        self.assertEqual(lib.worker_stat(25), errno.ENOTSUP)
        self.clean()

    def test_null_group_or_mutex_never_publishes_interface(self):
        for fault, allocations in ((1, 0), (2, 1)):
            with self.subTest(fault=fault):
                lib = self.reset(fault)
                lib.worker_create()
                self.assertEqual(lib.worker_stat(5), allocations)
                self.assertEqual(lib.worker_stat(6), 0)
                self.assertEqual(lib.worker_stat(7), 0)
                self.assertEqual(lib.worker_stat(26), 0)
                self.clean()

    def test_constructor_failures_latch_exact_errno_and_prevent_controller_start(self):
        failures = ((1, errno.ENOMEM), (2, errno.ENOMEM), (3, errno.ENOMEM),
                    (4, errno.EIO), (8, errno.ENXIO), (5, errno.EAGAIN), (9, errno.EINVAL))
        for fault, error in failures:
            for start in (False, True):
                with self.subTest(fault=fault, start=start):
                    lib = self.reset(fault)
                    if start:
                        self.assertEqual(lib.worker_start(), error)
                    else:
                        lib.worker_create()
                    self.assertEqual(lib.worker_stat(25), error)
                    self.assertEqual([lib.worker_stat(i) for i in (29, 1, 30, 31)], [0] * 4)
                    self.clean()

    def test_sapphire_constructor_failure_operations_and_flags_match_baseline(self):
        for fault in (3, 4, 8, 5, 9):
            snapshots = []
            for lib in self.libs:
                self.reset(fault, redfin=0, lib=lib)
                lib.worker_create()
                self.assertEqual(lib.worker_stat(25), 0)
                self.assertEqual(lib.worker_stat(29), 0 if fault in (3, 4) else 1)
                snapshots.append(tuple(lib.worker_stat(i) for i in range(32)))
                self.clean(lib)
            self.assertEqual(snapshots[0], snapshots[1])

    def test_real_interface_setup_and_rx_tx_paths_use_bounded_dma(self):
        lib = self.reset()
        lib.worker_create()
        self.assertEqual([lib.worker_stat(i) for i in (4, 5, 6, 7, 26, 27)], [1] * 6)
        lib.worker_rx(0)
        self.assertEqual(lib.worker_stat(12), 1)
        self.assertEqual(lib.worker_output(0, 512), 0)
        self.assertEqual(lib.worker_stat(11), 1)
        self.assertGreater(lib.worker_stat(1), 0)
        self.clean()

    def test_expiry_inside_either_real_rx_sync_never_delivers_or_rearms(self):
        for fault, sync in ((0, 1), (0, 2), (7, 0)):
            with self.subTest(fault=fault, sync=sync):
                lib = self.reset(fault)
                lib.worker_rx(sync)
                self.assertEqual(lib.worker_stat(12), 0)
                self.assertEqual(lib.worker_stat(1), 0)
                self.assertEqual(lib.worker_stat(3), sync if sync else 2)
                self.assertEqual(lib.worker_stat(10), 1 if fault == 7 else 0)
                self.assertEqual(lib.worker_stat(25), errno.ETIMEDOUT)
                self.clean()

    def test_expiry_while_waiting_for_tx_lock_never_queues_or_writes_dma(self):
        lib = self.reset()
        self.assertEqual(lib.worker_output(1, 64), errno.ENXIO)
        self.assertEqual([lib.worker_stat(i) for i in (10, 11, 18, 1)], [1, 0, 0, 0])
        self.clean()
        lib = self.reset()
        lib.worker_kick_expired()
        self.assertEqual([lib.worker_stat(i) for i in (11, 18, 1)], [0, 1, 0])
        self.clean()

    def test_stop_drains_wrapped_queue_once_lowers_interface_and_retains_dma(self):
        lib = self.reset()
        lib.worker_queue(32)
        self.assertEqual(lib.worker_stat(18), 32)
        self.assertEqual(lib.worker_stop(1), 1)
        self.assertEqual([lib.worker_stat(i) for i in (10, 18, 20, 8)], [32, 0, 0, 1])
        self.assertEqual(lib.worker_stop(0), 1)
        self.assertEqual([lib.worker_stat(i) for i in (10, 8)], [32, 1])
        self.assertEqual(lib.worker_output(0, 64), errno.ENXIO)
        self.assertEqual(lib.worker_stat(10), 33)
        self.clean()

    def test_software_stop_before_deadline_blocks_future_output_and_log_worker(self):
        lib = self.reset()
        self.assertEqual(lib.worker_stop(0), 1)
        self.assertEqual(lib.worker_stat(25), 0)
        self.assertEqual(lib.worker_output(0, 64), errno.ENXIO)
        self.assertEqual(lib.worker_log(0), 0)
        self.assertEqual(lib.worker_stat(15), 0)
        self.assertEqual(lib.worker_stat(10), 1)
        self.clean()

    def test_software_cleanup_precedes_refused_hardware_halt(self):
        lib = self.reset()
        lib.worker_queue(32)
        lib.worker_deny_halt()
        self.assertEqual(lib.worker_stop(1), 0)
        self.assertEqual([lib.worker_stat(i) for i in (10, 18, 20, 8, 1, 2)], [32, 0, 0, 1, 0, 0])
        self.assertEqual(lib.worker_stop(0), 0)
        self.assertEqual(lib.worker_stat(10), 32)
        self.clean()

    def test_enumeration_only_stop_preserves_every_original_operation(self):
        snapshots = []
        for lib in self.libs:
            self.reset(lib=lib)
            lib.worker_enum_only()
            self.assertEqual(lib.worker_stop(1), 1)
            snapshots.append(tuple(lib.worker_stat(i) for i in range(29)))
            self.clean(lib)
        self.assertEqual(snapshots[0], snapshots[1])

    def test_original_handlers_reproduce_expired_rx_delivery_and_tx_dma_copy(self):
        lib = self.reset(lib=self.baseline)
        lib.worker_rx(1)
        self.assertEqual(lib.worker_stat(23), 1)
        self.assertEqual(lib.worker_stat(1), 0)
        lib = self.reset(lib=self.baseline)
        self.assertEqual(lib.worker_output(1, 64), 0)
        self.assertEqual(lib.worker_stat(24), 1)
        self.assertEqual(lib.worker_stat(1), 0)

    def test_legacy_log_worker_preserves_original_send_flags(self):
        for lib in self.libs:
            self.reset(redfin=0, lib=lib)
            lib.worker_log(0)
            self.assertEqual(lib.worker_stat(15), 1)
            self.assertEqual(lib.worker_stat(16), 0)
            self.assertEqual(lib.worker_stat(32), 0)
            self.clean(lib)


if __name__ == '__main__':
    unittest.main()
