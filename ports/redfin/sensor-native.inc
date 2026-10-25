/* SPDX-License-Identifier: MIT
 * Native Redfin ADSP/PAS1, included by the one established WLAN owner.
 * Preferred HackiOS8e611870 redwood_adsp.c startup/SMEM/QRTR was reviewed;
 * its64MiB/0x86700000 reservation and LPASS MMIO do not apply to Redfin.
 * All firmware/calibration comes from private source-backed resident assets.
 */
#include "sensor-assets.h"
#include "ssc-client.h"
#include "sensor-reason.h"
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <kern/task.h>
#include <sys/vnode.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <sys/kauth.h>
extern "C" int redfin_sensor_power_start(void *,int (*)(void *));
extern "C" void redfin_sensor_hid_sample(unsigned,const rf_ssc_sensor *);
extern "C" void redfin_sensor_hid_withdraw(unsigned);
extern "C" uint32_t redfin_sensor_hid_interval(unsigned);
enum {SN_SOURCE=1,SN_POWER,SN_RESET,SN_METADATA,SN_INIT,SN_SETUP,SN_SMP,SN_COPY,SN_AUTH,SN_READY,SN_LINK,SN_RUNNING};
struct sn_context {
    unsigned attempted,active,failed,phase,power,reset,initialized,setup,auth_attempted,authenticated;
    unsigned copies,stores,peer_seen,hello,announced,ssc_started,queue_head,queue_tail,queue_count;
    unsigned cold_witness;
    unsigned reason_before_valid;
    char reason_before[RF_SENSOR_REASON_BYTES];
    uint64_t source_bytes,nonce,started,report_at,function;
    uint8_t source_sha[32];
    uint8_t *source_data;
    IOBufferMemoryDescriptor *metadata;
    uint64_t metadata_physical;
    fw_start_map destination;
    rf_sensor_assets assets;rf_sensor_image image;
    rf_wifi_smp2p_session smp;rf_wifi_smp2p_ops smp_ops;
    rf_glink glink;rf_glink_ops glink_ops;
    rf_host host;rf_host_ops host_ops;
    rf_ssc_client ssc;rf_ssc_ops ssc_ops;
    uint32_t peer,ssc_node,ssc_port;
    uint8_t queue[32][RF_HOST_BLOCK+64];uint32_t queue_bytes[32];
    uint8_t transport[RF_HOST_BLOCK+128];
};
static sn_context sn;
static uint64_t sn_ns(void *)
{
    uint64_t ticks=__builtin_arm_rsr64("CNTPCT_EL0");
    return (ticks/19200000u)*1000000000u+(ticks%19200000u)*1000000000u/19200000u;
}
static bool sn_contract(bool capture)
{
    DTEntry node;uint64_t bytes=0,hardware[8]={};
    static const char expected_path[]="/redfin/firmware/native-sensors.bundle";
    char path[sizeof(expected_path)]={};
    uint32_t proof=0,witness[10]={};uint8_t digest[32]={};
    static const uint64_t expected[8]={RF_SENSOR_BASE,RF_SENSOR_MEMORY,0x80900000,0x200000,0x1f40000,0x20000,0x408000,0x1000};
    static const uint32_t contract[10]={1,1,2,443,429,3,0,2,384,384};
    if(SecureDTLookupEntry(NULL,"/redfin-sensors",&node)!=kSuccess||
        !fw_property(node,"source-path",path,sizeof(path))||memcmp(path,expected_path,sizeof(path))||
        !fw_property(node,"bundle-bytes",&bytes,sizeof(bytes))||
        !fw_property(node,"bundle-sha256",digest,sizeof(digest))||
        !fw_property(node,"live-fdt-verified",&proof,sizeof(proof))||proof!=1||
        !fw_property(node,"source-contract",witness,sizeof(witness))||memcmp(witness,contract,sizeof(contract))||
        !fw_property(node,"hardware-reg",hardware,sizeof(hardware))||memcmp(hardware,expected,sizeof(hardware))||
        bytes<64||bytes>32u*1024u*1024u)return false;
    if(capture){sn.source_bytes=bytes;memcpy(sn.source_sha,digest,32);}
    else if(sn.source_bytes!=bytes||memcmp(sn.source_sha,digest,32))return false;
    return true;
}
static int sn_check(void *opaque)
{
    if(opaque!=&sn||!sn.active||sn.failed||!redfin_wifi_gui_ready()||
        current_thread()!=fw_probe.owner||sn.nonce!=fw_probe.nonce||fw_start_glink_check(&fw_start))return EPERM;
    if(sn.destination.map&&(sn.destination.map->getVirtualAddress()!=sn.destination.base||sn.destination.map->getLength()!=RF_SENSOR_MEMORY))return EPERM;
    if(sn.metadata&&(sn.metadata->getLength()!=16384||!sn.metadata->getBytesNoCopy()||
        sn.metadata->getPhysicalSegment(0,NULL,kIOMemoryMapperNone)!=sn.metadata_physical))return EPERM;
    return 0;
}
static bool sn_valid(void *p){return !sn_check(p);}
static int sn_barrier(void *p){if(sn_check(p))return EPERM;__asm__ volatile("dsb osh":::"memory");return sn_check(p);}
static int sn_map(fw_start_map *m,uint64_t base,uint64_t bytes,bool write)
{
    if(sn_check(&sn)||m->map||!sn_contract(false))return EPERM;
    m->memory=IOMemoryDescriptor::withPhysicalAddress(base,bytes,write?kIODirectionInOut:kIODirectionIn);
    m->map=m->memory?m->memory->map(kIOMapWriteCombineCache|(write?0:kIOMapReadOnly)):NULL;
    if(!m->map||!m->map->getVirtualAddress()||m->map->getLength()!=bytes)return ENOMEM;
    m->base=(uintptr_t)m->map->getVirtualAddress();return sn_check(&sn);
}
static int sn_read_source(void)
{
    if(sn_check(&sn)||sn.source_data||!sn_contract(false))return EPERM;
    vfs_context_t context=vfs_context_kernel();vnode_t vnode=NULL;
    int error=vnode_lookup("/redfin/firmware/native-sensors.bundle",VNODE_LOOKUP_NOFOLLOW,&vnode,context);
    if(error)return error;
    struct vnode_attr attr;VATTR_INIT(&attr);VATTR_WANTED(&attr,va_data_size);VATTR_WANTED(&attr,va_uid);VATTR_WANTED(&attr,va_mode);
    error=vnode_getattr(vnode,&attr,context);
    if(!error&&(vnode_vtype(vnode)!=VREG||!VATTR_IS_SUPPORTED(&attr,va_data_size)||
        !VATTR_IS_SUPPORTED(&attr,va_uid)||!VATTR_IS_SUPPORTED(&attr,va_mode)||attr.va_data_size!=sn.source_bytes||
        attr.va_uid!=0||(attr.va_mode&022)))error=EPERM;
    if(!error){sn.source_data=(uint8_t *)IOMalloc((vm_size_t)sn.source_bytes);if(!sn.source_data)error=ENOMEM;}
    for(uint64_t at=0;!error&&at<sn.source_bytes;) {
        int n=(int)(sn.source_bytes-at);if(n>65536)n=65536;int residual=n;
        error=vn_rdwr(UIO_READ,vnode,(caddr_t)(sn.source_data+at),n,(off_t)at,UIO_SYSSPACE,0,
            vfs_context_ucred(context),&residual,vfs_context_proc(context));
        if(!error&&(residual||sn_check(&sn)))error=EIO;
        if(!error)at+=(unsigned)n;
    }
    vnode_put(vnode);
    /* Keep the bounded immutable copy for the DSP's later TFTP requests. Its
     * whole-container and per-record hashes are checked before any PAS call. */
    return error;
}
static void sn_delay(void *p,unsigned us)
{if(sn_check(p)||us>30000)return;if(us>=1000)IOSleep((us+999)/1000);else IODelay(us);}
static int sn_invoke(void *p,rf_sq_regs *r)
{
    if(!r||sn_check(p)||!sn.power||!sn.function||(r->x[0]!=sn.function&&r->x[0]!=1))return EPERM;
    register uint64_t x0 __asm__("x0")=r->x[0],x1 __asm__("x1")=r->x[1],x2 __asm__("x2")=r->x[2],
        x3 __asm__("x3")=r->x[3],x4 __asm__("x4")=r->x[4],x5 __asm__("x5")=r->x[5],x6 __asm__("x6")=r->x[6],x7 __asm__("x7")=0;
    __asm__ volatile("dsb sy\n\tsmc #0\n\tdsb sy": "+r"(x0),"+r"(x1),"+r"(x2),"+r"(x3),"+r"(x4),"+r"(x5),"+r"(x6),"+r"(x7):
        :"x8","x9","x10","x11","x12","x13","x14","x15","x16","x17","cc","memory");
    r->x[0]=x0;r->x[1]=x1;r->x[2]=x2;r->x[3]=x3;r->x[4]=x4;r->x[5]=x5;r->x[6]=x6;r->x[7]=x7;
    return sn_check(p);
}
static int sn_pas(unsigned command)
{
    IOLog("REDFIN SENSORS: PAS1 phase=%u command=%u preflight-entry cold-witness=%u destination-writes=%u\n",sn.phase,command,sn.cold_witness,sn.copies);
    if(sn_check(&sn)||!sn.power||!sn_contract(false)||redfin_wifi_power_audit()||
       (command!=1&&command!=2&&command!=5)||
       (command==1&&(sn.phase!=SN_INIT||!sn.cold_witness||!sn.metadata||!sn.metadata_physical||sn.initialized||sn.reset))||
       (command==2&&(sn.phase!=SN_SETUP||!sn.initialized||sn.setup))||
       (command==5&&(sn.phase!=SN_AUTH||!sn.setup||!sn.reset||!sn.auth_attempted||sn.authenticated||sn.smp.stage!=RF_WIFI_SMP2P_ARMED)))return EPERM;
    rf_sq_regs request={{0}},live;request.x[0]=UINT64_C(0x42000200)|command;
    request.x[1]=command==1?0x82:command==2?3:1;request.x[2]=1;
    request.x[3]=command==1?sn.metadata_physical:command==2?RF_SENSOR_BASE:0;request.x[4]=command==2?RF_SENSOR_MEMORY:0;
    live=request;sn.function=request.x[0];unsigned calls=0,busy=0,resumes=0;uint64_t first=sn_ns(NULL);
    int error=0;int64_t status=0;uint64_t value=0;
    do {
        if(sn_ns(NULL)-first>UINT64_C(10000000000)){error=ETIMEDOUT;break;}
        if(!calls)IOLog("REDFIN SENSORS: SMC enter fn=%#llx phase=%u PAS=1 metadata-in-owned-wired-page=%u\n",live.x[0],sn.phase,command==1);
        error=sn_invoke(&sn,&live);++calls;if(error)break;
        status=(int64_t)live.x[0];value=live.x[1];
        if(status==1){if(++resumes>1024){error=ETIMEDOUT;break;}continue;}
        if(status==-12&&busy++<3){sn_delay(&sn,30000);live=request;continue;}
        if(status||value)error=EIO;break;
    }while(true);
    sn.function=0;
    IOLog("REDFIN SENSORS: PAS1 command=%u result=%d status=%lld value=%#llx calls=%u resumes=%u\n",command,error,status,value,calls,resumes);
    return error;
}
static int sn_metadata(void)
{
    if(sn_check(&sn)||sn.metadata||sn.phase!=SN_METADATA||!sn.cold_witness||sn.initialized||sn.reset)return EPERM;
    sn.metadata=IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
        kIOMemoryPhysicallyContiguous|kIODirectionInOut|kIOMapWriteCombineCache,16384,16384);
    if(!sn.metadata)return ENOMEM;
    IOByteCount contiguous=0;sn.metadata_physical=sn.metadata->getPhysicalSegment(0,&contiguous,kIOMemoryMapperNone);
    if(!sn.metadata_physical||sn.metadata_physical%16384||contiguous<16384||
        sn.metadata_physical<UINT64_C(0x180000000)||sn.metadata_physical>UINT64_C(0x200000000)-16384)return EPERM;
    uint8_t *page=(uint8_t *)sn.metadata->getBytesNoCopy();if(!page||sn.image.metadata_bytes>16384)return EPERM;
    memset(page,0,16384);memcpy(page,sn.image.metadata,sn.image.metadata_bytes);
    __asm__ volatile("dsb sy":::"memory");
    const volatile uint8_t *readback=page;
    for(unsigned i=0;i<16384;++i)if(readback[i]!=(i<sn.image.metadata_bytes?sn.image.metadata[i]:0))return EIO;
    return sn_check(&sn);
}
static int sn_copy(uint32_t offset,const uint8_t *data,uint32_t bytes)
{
    if(sn_check(&sn)||!sn.reset||!sn.initialized||!sn.setup||sn.auth_attempted||!sn.destination.base||!bytes||bytes>65536||
        offset>RF_SENSOR_MEMORY||bytes>RF_SENSOR_MEMORY-offset||
        sn.phase!=SN_COPY)return EPERM;
    uint8_t *destination=(uint8_t *)sn.destination.base+offset;
    if(data)memcpy(destination,data,bytes);else memset(destination,0,bytes);
    __asm__ volatile("dsb osh":::"memory");
    const volatile uint8_t *actual=destination;
    for(uint32_t i=0;i<bytes;++i)if(actual[i]!=(data?data[i]:0))return EIO;
    ++sn.copies;return sn_check(&sn);
}
static int sn_reset(void *p){return !sn_check(p)&&sn.reset&&!sn.auth_attempted?0:EPERM;}
static int sn_started(void *p){return !sn_check(p)&&sn.authenticated?0:EPERM;}
static int sn_lock(void *p,uint32_t ms){return sn_check(p)?EPERM:fw_start_lock(&fw_start,ms);}
static int sn_unlock(void *){return fw_start_unlock(&fw_start);}
static int sn_write(void *p,uint32_t offset,uint32_t value)
{
    if(sn_check(p)||offset%4||offset>REDFIN_SMEM_BYTES-4)return EPERM;
    /* Both allocators validate their exact host2 item/FIFO target before this
     * callback; recheck the selected private heap for an independent bound. */
    redfin_smem_report heap={};
    if(redfin_smem_inspect_host((const volatile uint8_t *)fw_start.mapping[FW_START_SMEM].base,
        REDFIN_SMEM_BYTES,2,&heap)!=REDFIN_SMEM_OK||offset<heap.partition_offset||
        offset>heap.partition_offset+heap.partition_bytes-4)return EPERM;
    ++sn.stores;return fw_start_smem_write(&fw_start,offset,value);
}
static int sn_notify(void *p,unsigned signal)
{
    if(sn_check(p)||(signal!=0&&signal!=2))return EPERM;
    __asm__ volatile("dsb oshst":::"memory");
    *(volatile uint32_t *)(fw_start.mapping[FW_START_IPCC].base+0xc)=0x30000u|signal;
    __asm__ volatile("dsb osh":::"memory");return sn_check(p);
}
static int sn_kick(void *p){return sn_notify(p,2);}
static int sn_gl_kick(void *p){return sn_notify(p,0);}
static int sn_ms(void *p,uint64_t *ms){if(!ms||sn_check(p))return EPERM;*ms=sn_ns(p)/1000000u;return 0;}
static int sn_pause(void *p,uint32_t us){if(sn_check(p)||!us||us>1000)return EPERM;IODelay(us);return sn_check(p);}
static int sn_gl_check(void *p)
{
    if(sn_check(p)||!sn.authenticated||sn.smp.stage!=RF_WIFI_SMP2P_READY||sn.smp.poisoned||!sn.smp.peer)return EPERM;
    uint32_t offset=sn.smp.peer+36+20*sn.smp.slave_index;
    if(sn.smp.slave_index>=16||offset>REDFIN_SMEM_BYTES-4)return EPERM;
    return (redfin_smem_u32((const volatile uint8_t *)fw_start.mapping[FW_START_SMEM].base+offset)&3)==2?0:EPERM;
}
static int sn_gl_lock(void *p){return sn_gl_check(p)?EPERM:sn_lock(p,1000);}
static int sn_payload(void *p,uint32_t offset,const uint8_t *data,uint32_t bytes)
{
    uint32_t tx=sn.glink.tx;
    if(sn_gl_check(p)||!tx||!data||!bytes||bytes>16384||(offset|bytes)%4||offset<tx||offset-tx>16384-bytes)return EPERM;
    memcpy((void *)(fw_start.mapping[FW_START_SMEM].base+offset),data,bytes);
    return sn_barrier(p);
}
static int sn_queue(uint32_t type,uint32_t from,uint32_t node,uint32_t to,const uint8_t *data,uint32_t bytes)
{
    if(sn_gl_check(&sn)||!data||!bytes||bytes>RF_HOST_BLOCK+4||sn.queue_count>=32)return ENOBUFS;
    uint8_t *q=sn.queue[sn.queue_head];uint32_t n=32+((bytes+3)&~3u);memset(q,0,n);
    const uint32_t fields[8]={1,type,1,from,0,bytes,node,to};
    for(unsigned i=0;i<8;++i)rf_gl_encode(q+i*4,fields[i]);memcpy(q+32,data,bytes);
    sn.queue_bytes[sn.queue_head]=n;sn.queue_head=(sn.queue_head+1)%32;++sn.queue_count;return 0;
}
static int sn_control(uint32_t type,uint32_t from,uint32_t node,uint32_t to,uint32_t a,uint32_t b,uint32_t c=0,uint32_t d=0)
{uint8_t data[20];uint32_t v[5]={type,a,b,c,d};for(unsigned i=0;i<5;++i)rf_gl_encode(data+i*4,v[i]);return sn_queue(type,from,node,to,data,sizeof(data));}
static int sn_host_send(void *,uint32_t from,uint32_t node,uint32_t to,const uint8_t *data,uint32_t bytes)
{return sn_queue(1,from,node,to,data,bytes);}
static int sn_lookup(void *,const char *name,const uint8_t **data,uint32_t *bytes)
{
    if(strncmp(name,"image/",6)||sn_gl_check(&sn))return ENOENT;
    char key[80];if(strlen(name+6)>70)return ENOENT;
    snprintf(key,sizeof(key),"fw/%s",name+6);const rf_sensor_asset *a=rf_sensor_asset_find(&sn.assets,key);
    if(!a)return ENOENT;*data=a->data;*bytes=a->bytes;return 0;
}
static void sn_host_event(void *,unsigned kind,const char *name,uint32_t bytes)
{IOLog("REDFIN SENSORS: host event=%u file=%.150s bytes=%u\n",kind,name,bytes);}
static int sn_pd(uint32_t source,uint32_t from,const uint8_t *data,uint32_t bytes)
{
    if(bytes<7||bytes>4096||data[0]||rf_host_le16(data+5)!=bytes-7)return EINVAL;
    uint16_t msg=rf_host_le16(data+3);uint8_t response[512]={2};
    memcpy(response+1,data+1,4);response[7]=2;response[8]=4;unsigned used=14;
    char service[80]={};unsigned found=0;
    for(unsigned at=7;at<bytes;) {
        if(bytes-at<3)return EINVAL;
        unsigned type=data[at],n=rf_host_le16(data+at+1);at+=3;if(n>bytes-at)return EINVAL;
        if(type==1&&msg==0x21) {
            if(found++||!n||n>=sizeof(service))return EINVAL;
            for(unsigned i=0;i<n;++i)if(data[at+i]<32||data[at+i]>126)return EINVAL;
            memcpy(service,data+at,n);
        }
        at+=n;
    }
    if(msg==0x21&&found) {
        static const char *const domains[3]={"root_pd","sensor_pd","audio_pd"};unsigned count=0;
        const rf_sensor_asset *match[3]={};
        for(unsigned i=0;i<3;++i) {
            char key[80];if(snprintf(key,sizeof(key),"pd/%s/%s",domains[i],service)>=(int)sizeof(key))return EINVAL;
            match[i]=rf_sensor_asset_find(&sn.assets,key);if(match[i]){if(match[i]->bytes!=12)return EINVAL;++count;}
        }
        response[used++]=0x10;response[used++]=2;response[used++]=0;rf_host_le_put(response+used,count,2);used+=2;
        response[used++]=0x11;response[used++]=2;response[used++]=0;response[used++]=1;response[used++]=0;
        if(count) {
            response[used++]=0x12;unsigned length_at=used;used+=2;response[used++]=(uint8_t)count;
            for(unsigned i=0;i<3;++i)if(match[i]) {
                char domain[48];int n=snprintf(domain,sizeof(domain),"msm/adsp/%s",domains[i]);
                response[used++]=(uint8_t)n;memcpy(response+used,domain,n);used+=(unsigned)n;
                memcpy(response+used,match[i]->data,4);used+=4;response[used++]=(uint8_t)rf_sa32(match[i]->data+4);
                memcpy(response+used,match[i]->data+8,4);used+=4;
            }
            rf_host_le_put(response+length_at,used-length_at-2,2);
        }
        IOLog("REDFIN SENSORS: native pd service=%.79s actual-domains=%u\n",service,count);
    } else if(msg!=0x20){response[10]=1;response[12]=0x5e;}
    rf_host_le_put(response+5,used-7,2);return sn_queue(1,0x4001,source,from,response,used);
}
static int sn_ssc_send(void *,const uint8_t *data,uint32_t bytes)
{return sn.ssc_port?sn_queue(1,0x4004,sn.ssc_node,sn.ssc_port,data,bytes):ENXIO;}
static void sn_sample(void *,unsigned kind,const rf_ssc_sensor *sensor)
{
    redfin_sensor_hid_sample(kind,sensor);
    if(sensor->samples==1||sensor->samples%1024==0)IOLog("REDFIN SENSORS: sample datatype=%s name=%.79s count=%u status=%u values=%u fixed=%d,%d,%d ticks=%llu\n",
        rf_ssc_datatype(kind),sensor->name,sensor->samples,sensor->status,sensor->values,sensor->fixed[0],sensor->fixed[1],sensor->fixed[2],sensor->ticks);
}
static void sn_withdraw(void *,unsigned kind){redfin_sensor_hid_withdraw(kind);}
static void sn_event(void *,const char *event,unsigned a,unsigned b)
{IOLog("REDFIN SENSORS: SSC event=%s a=%u b=%u\n",event,a,b);}
static void sn_packet(void *,const uint8_t *data,uint32_t length)
{
    uint32_t type,source,from,confirm,size,destination,to,at;
    if(length>=32&&rf_gl_u32(data)==1) {
        type=rf_gl_u32(data+4);source=rf_gl_u32(data+8);from=rf_gl_u32(data+12);confirm=rf_gl_u32(data+16);
        size=rf_gl_u32(data+20);destination=rf_gl_u32(data+24);to=rf_gl_u32(data+28);at=32;
    }else if(length>=16&&data[0]==3&&!(data[2]&~1u)) {
        type=data[1];confirm=data[2]&1;size=rf_gl_u32(data+4);source=rf_host_le16(data+8);from=rf_host_le16(data+10);
        destination=rf_host_le16(data+12);to=rf_host_le16(data+14);at=16+data[3];
        if(from==0xfffe)from=0xfffffffeu;if(to==0xfffe)to=0xfffffffeu;
    }else {sn.failed=1;return;}
    if(at>length||!size||size>length-at||confirm>1||(destination!=1&&destination!=UINT32_MAX)){sn.failed=1;return;}
    if(!sn.peer_seen){sn.peer=source;sn.peer_seen=1;}
    if(source!=sn.peer){sn.failed=1;return;}
    if(confirm&&sn_control(7,to,source,from,destination,to)){sn.failed=1;return;}
    const uint8_t *p=data+at;int error=0;
    if(type==2) {
        if(!(sn.hello&2)){sn.hello|=3;error=sn_control(2,0xfffffffeu,source,0xfffffffeu,0,0);}
    }else if(type==4&&to==0xfffffffeu&&size==20) {
        uint32_t service=rf_gl_u32(p+4),instance=rf_gl_u32(p+8),node=rf_gl_u32(p+12),port=rf_gl_u32(p+16);
        IOLog("REDFIN SENSORS: QRTR service=%u version=%u instance=%u node=%u port=%#x\n",service,instance&255,instance>>8,node,port);
        if(service==RF_SNS_SERVICE&&(instance&255)==RF_SNS_VERSION&&node==source&&port) {
            if(sn.ssc_port&&(sn.ssc_node!=node||sn.ssc_port!=port)){sn.failed=1;return;}
            sn.ssc_node=node;sn.ssc_port=port;
        }
    }else if(type==5&&size==20&&rf_gl_u32(p+4)==RF_SNS_SERVICE){error=ENXIO;}
    else if(type==1&&to==0x4001)error=sn_pd(source,from,p,size);
    else if(type==1&&to==0x4002)error=rf_host_tftp_request(&sn.host,&sn.host_ops,source,from,p,size);
    else if(type==1&&to>=0x4100&&to<0x5100)error=rf_host_tftp_packet(&sn.host,&sn.host_ops,source,from,to,p,size);
    else if(type==1&&to==0x4004&&source==sn.ssc_node&&from==sn.ssc_port)error=rf_ssc_receive(&sn.ssc,p,size);
    if(error){IOLog("REDFIN SENSORS: QRTR failed=%d type=%u to=%#x\n",error,type,to);sn.failed=1;}
}
static int sn_start(void)
{
    sn.active=1;sn.phase=SN_SOURCE;sn.nonce=fw_probe.nonce;sn.started=sn_ns(NULL);
    if(!sn_contract(true)||sn_check(&sn))return EPERM;
    int error=sn_read_source();if(error)return error;
    const uint8_t *data=sn.source_data;
    if(rf_sensor_assets_open(&sn.assets,data,(size_t)sn.source_bytes,sn.source_sha,redfin_mpss_kernel_sha256,NULL)||
        rf_sensor_image_open(&sn.image,&sn.assets))return EINVAL;
    IOLog("REDFIN SENSORS: source verified assets=%u segments=%u native-reservation=%#llx/%#x\n",sn.assets.count,sn.image.count,RF_SENSOR_BASE,RF_SENSOR_MEMORY);
    sn.smp.remote_pid=2;
    sn.smp_ops={(const volatile uint8_t *)fw_start.mapping[FW_START_SMEM].base,REDFIN_SMEM_BYTES,&sn,sn_check,
        sn_reset,sn_started,sn_lock,sn_unlock,sn_write,sn_barrier,sn_kick,sn_ms,sn_pause};
    error=rf_wifi_smp2p_cold(&sn.smp,&sn.smp_ops);
    IOLog("REDFIN SENSORS: native readonly cold-witness=%d; no inactive-DSP shutdown, no destination access\n",error);
    if(error)return error;sn.cold_witness=1;
    sn.reason_before_valid=rf_sensor_reason((const volatile uint8_t *)fw_start.mapping[FW_START_SMEM].base,
        REDFIN_SMEM_BYTES,sn.reason_before)==0;
    sn.phase=SN_POWER;error=redfin_sensor_power_start(&sn,sn_check);if(error)return error;sn.power=1;
    sn.phase=SN_METADATA;error=sn_metadata();if(error)return error;
    if(rf_wifi_smp2p_cold(&sn.smp,&sn.smp_ops))return EPERM;
    sn.phase=SN_INIT;error=sn_pas(1);if(error)return error;sn.initialized=1;
    sn.phase=SN_SETUP;error=sn_pas(2);if(error)return error;sn.setup=1;sn.reset=1;
    /* Match native PIL: only accepted INIT/MEM_SETUP may grant DSP RAM.
     * Metadata remains in our separately wired page, retained on uncertainty. */
    error=sn_map(&sn.destination,RF_SENSOR_BASE,RF_SENSOR_MEMORY,true);if(error)return error;
    sn.phase=SN_SMP;error=rf_wifi_smp2p_prepare(&sn.smp,&sn.smp_ops);if(error)return error;
    sn.phase=SN_COPY;
    for(unsigned i=0;i<sn.image.count;++i) {
        const rf_sensor_segment *s=&sn.image.segment[i];
        for(uint32_t at=0;at<s->memory;) {
            uint32_t n=at<s->bytes?s->bytes-at:s->memory-at;if(n>65536)n=65536;
            error=sn_copy(s->physical-(uint32_t)RF_SENSOR_BASE+at,at<s->bytes?s->data+at:NULL,n);if(error)return error;at+=n;
        }
        /* This same owner services WLAN/MPSS between native sensor segments. */
        error=fw_start_packets_poll(&fw_start,fw_start_ns(&fw_start));if(error)return error;
    }
    if(!sn_contract(false)||redfin_wifi_power_audit())return EPERM;
    error=rf_wifi_smp2p_auth_begin(&sn.smp,&sn.smp_ops);if(error)return error;
    sn.phase=SN_AUTH;sn.auth_attempted=1;error=sn_pas(5);if(error)return error;sn.authenticated=1;sn.reset=0;
    sn.phase=SN_READY;error=rf_wifi_smp2p_wait_ready(&sn.smp,&sn.smp_ops,10000);
    IOLog("REDFIN SENSORS: SMP2P ready=%d state=%#x handover=%u copies=%u elapsed-ms=%llu\n",error,sn.smp.last_state,sn.smp.handover,sn.copies,(sn_ns(NULL)-sn.started)/1000000u);
    if(error)return error;
    sn.phase=SN_LINK;sn.glink.remote_host=2;
    sn.glink_ops={&sn,(const volatile uint8_t *)fw_start.mapping[FW_START_SMEM].base,sn_gl_check,sn_gl_lock,sn_unlock,
        sn_write,sn_barrier,sn_gl_kick,sn_packet,sn_payload};
    sn.host_ops={&sn,sn_gl_check,sn_lookup,sn_host_send,sn_host_event};
    sn.ssc_ops={&sn,sn_gl_check,sn_ssc_send,sn_ns,sn_sample,sn_withdraw,sn_event};
    error=rf_gl_init(&sn.glink,&sn.glink_ops);if(error)return error;
    error=rf_gl_say(&sn.glink,&sn.glink_ops,0,1,1,NULL,0);if(!error)sn.phase=SN_RUNNING;
    return error;
}
static void sn_poll(void)
{
    if(sn.failed)return;
    if(!sn.attempted) {
        if(!fw_start.interface_timed)return;
        DTEntry node;if(SecureDTLookupEntry(NULL,"/redfin-sensors",&node)!=kSuccess){sn.attempted=1;sn.failed=1;return;}
        sn.attempted=1;int error=sn_start();
        IOLog("REDFIN SENSORS: start result=%d phase=%u reset=%u auth=%u retained=1 same-worker=1\n",error,sn.phase,sn.reset,sn.authenticated);
        if(error){sn.failed=1;return;}
    }
    int error=rf_wifi_smp2p_alive(&sn.smp,&sn.smp_ops);
    if(error==RF_WIFI_SMP2P_UNSTABLE)return;
    if(!error)error=rf_gl_pump(&sn.glink,&sn.glink_ops);
    if(error==RF_GL_AGAIN)error=0;
    if(!error&&sn.glink.open&&!(sn.hello&1)) {sn.hello|=1;error=sn_control(2,0xfffffffeu,UINT32_MAX,0xfffffffeu,0,0);}
    if(!error&&sn.glink.open&&!sn.announced) {
        error=sn_control(4,0xfffffffeu,UINT32_MAX,0xfffffffeu,64,0x101,1,0x4001);
        if(!error)error=sn_control(4,0xfffffffeu,UINT32_MAX,0xfffffffeu,4096,1,1,0x4002);
        if(!error)sn.announced=1;
    }
    while(!error&&sn.queue_count) {
        error=rf_gl_send_packet(&sn.glink,&sn.glink_ops,sn.queue[sn.queue_tail],sn.queue_bytes[sn.queue_tail],sn.transport,sizeof(sn.transport));
        if(error==RF_GL_AGAIN){error=0;break;}if(error)break;
        sn.queue_tail=(sn.queue_tail+1)%32;--sn.queue_count;
    }
    if(!error&&sn.ssc_port&&!sn.ssc_started){sn.ssc_started=1;error=rf_ssc_begin(&sn.ssc,&sn.ssc_ops,&sn.assets);}
    if(!error&&sn.ssc_started) {
        for(unsigned i=0;i<RF_SENSOR_COUNT;++i) {
            uint32_t interval=redfin_sensor_hid_interval(i);
            if(interval)error=rf_ssc_set_interval(&sn.ssc,i,interval);
            if(error)break;
        }
        if(!error)error=rf_ssc_poll(&sn.ssc);
    }
    uint64_t now=sn_ns(NULL);
    if(now>=sn.report_at) {
        sn.report_at=now+UINT64_C(5000000000);
        IOLog("REDFIN SENSORS: GLINK open=%u packets=%u SSC=%#x registry=%u pending=%u error=%d\n",sn.glink.open,sn.glink.packets,sn.ssc_port,sn.ssc.registry_verified,sn.ssc.pending,error);
        if(!sn_contract(false))error=EPERM;
    }
    if(error||sn.failed) {
        if(error==RF_WIFI_SMP2P_FATAL&&!sn_check(&sn)) {
            char reason[RF_SENSOR_REASON_BYTES]={};
            int detail=rf_sensor_reason((const volatile uint8_t *)fw_start.mapping[FW_START_SMEM].base,REDFIN_SMEM_BYTES,reason);
            IOLog("REDFIN SENSORS: actual native SMEM423 SFR result=%d reason=%.255s prior-present=%u changed=%u readonly=1 no-restart=1\n",
                detail,detail?"(unavailable)":reason,sn.reason_before_valid,
                !detail&&(!sn.reason_before_valid||strcmp(reason,sn.reason_before)));
        }
        IOLog("REDFIN SENSORS: stopped error=%d phase=%u glink=%u/%u changed=%u offset=%#x retained=1\n",error,sn.phase,sn.glink.last_command,sn.glink.last_p1,sn.glink.changed_reason,sn.glink.changed_offset);
        rf_ssc_stop(&sn.ssc);sn.failed=1;
    }
}
