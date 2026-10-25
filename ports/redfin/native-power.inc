/* SPDX-License-Identifier: APSL-2.0 */
/* Native Redfin QG/ADC5/SMB5, TSENS26xx and OSM adapter.
 * IOPMPowerSource publication follows HackiOS RedwoodBattery (8e611870),
 * adapted to Google's actual Redfin hardware/500b3a2059c1ee interfaces.
 * This is a Modification of Original Code subject to APSL2.0; see LICENSE.
 * No inherited SM6225 or Redwood PMIC/EPSS address is used. */
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/pwr_mgt/IOPM.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include <arm64/redfin_gui_profile.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <sys/sysctl.h>
#include <sys/reboot.h>
#include <pexpert/pexpert.h>
#include <vm/pmap.h>
#include <vm/memory_types.h>
#include <arm/memory_types.h>
#include "RedfinPowerPolicy.h"
#include "RedfinPowerConversion.h"

extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
namespace {
static const uint32_t power_contract[]={1,2,0x4800,0xb100,0x3100,0x1000,0x1100,0x1200,0x1300,0x1400,0x1500,
    0x0c222000,0x0c263000,0x0c223000,0x0c265000,0x18323000,0x18325800,0x18327800};
static vm_offset_t power_core,power_observer,power_config;
static uint32_t power_version;
static bool power_spmi_ok,power_attempted;
static int power_running,power_pressure,power_hottest=-273150,power_battery_mc=-273150;
static int power_soc=-1,power_uv=-1,power_ua,power_external=-1,power_charging=-1;
static unsigned power_samples,power_errors,power_throttles;
enum {P_REVID,P_QG,P_SDAM,P_ADC,P_CHGR,P_DCDC,P_BATIF,P_USB,P_DC,P_TYPEC,P_RTC,P_COUNT};
struct power_target {unsigned ppid,apid,owner;uint32_t mapping;vm_offset_t writer;};
static power_target power_targets[P_COUNT]={{0x201,512,0,0,0},{0x248,512,0,0,0},{0x2b1,512,0,0,0},
    {0x231,512,0,0,0},{0x210,512,0,0,0},{0x211,512,0,0,0},{0x212,512,0,0,0},
    {0x213,512,0,0,0},{0x214,512,0,0,0},{0x215,512,0,0,0},{0x060,512,0,0,0}};
struct power_tsens {vm_offset_t srot,tm;uint32_t control,enabled;};
static power_tsens power_ts[2];
struct power_domain {vm_offset_t base;uint32_t rows[40],khz[40],boot,current,normal,count,cores;bool valid;};
static power_domain power_domains[3];
static struct redfin_soc_tracker power_soc_tracker;

static uint32_t power_rd(vm_offset_t base,unsigned offset)
{uint32_t n=*(volatile uint32_t *)(base+offset);__asm__ volatile("dmb oshld" ::: "memory");return n;}
static void power_wr(vm_offset_t base,unsigned offset,uint32_t value)
{*(volatile uint32_t *)(base+offset)=value;__asm__ volatile("dsb osh" ::: "memory");}
static uint64_t power_now(void)
{uint64_t n;absolutetime_to_nanoseconds(mach_absolute_time(),&n);return n;}
static bool power_match(const power_target *t)
{
    return power_spmi_ok && t && t->apid<512 && power_rd(power_core,0)==power_version &&
        power_rd(power_core,0x900+4*t->apid)==t->mapping &&
        (power_rd(power_config,0x700+4*t->apid)&7)==t->owner;
}
static int power_poll(vm_offset_t base,unsigned offset)
{
    for (unsigned us=0;us<1000;++us) {
        uint32_t status=power_rd(base,offset);
        if (status&1) {
            if (!(status&14)) return 0;
            power_spmi_ok=false;return EIO;
        }
        IODelay(1);
    }
    /* No reuse of an uncertain observer/writer or retry after its timeout. */
    power_spmi_ok=false;return ETIMEDOUT;
}
static int power_read(unsigned which,unsigned address,uint8_t *out,unsigned bytes)
{
    if (which>=P_COUNT || !out || !bytes || bytes>8 || (address&255)+bytes>256) return EINVAL;
    const power_target *t=&power_targets[which];
    if ((address>>8)!=(t->ppid&255) || !power_match(t)) return ENXIO;
    unsigned channel=t->apid*0x80;
    power_wr(power_observer,channel,(1u<<27)|((address&255)<<4)|(bytes-1));
    int error=power_poll(power_observer,channel+8);if (error) return error;
    uint32_t data[2]={power_rd(power_observer,channel+0x18),0};
    if (bytes>4) data[1]=power_rd(power_observer,channel+0x1c);
    if (!power_match(t)) {power_spmi_ok=false;return EAGAIN;}
    memcpy(out,data,bytes);return 0;
}
static int power_byte(unsigned which,unsigned address,uint8_t *out)
{return power_read(which,address,out,1);}
static int power_write(unsigned which,unsigned address,const uint8_t *data,unsigned bytes)
{
    bool allowed=(which==P_ADC && ((address>=0x3142 && address+bytes<=0x3147) ||
        (address==0x3147 && bytes==1))) ||
        (which==P_CHGR && bytes==1 && (address==0x1042 || address==0x1043)) ||
        (which==P_QG && address==0x48bf && bytes==1);
    if (!allowed || !data || !bytes || bytes>5) return EINVAL;
    power_target *t=&power_targets[which];
    if (!power_match(t) || t->owner!=0) return EPERM;
    if (!t->writer) t->writer=ml_io_map_unmappable(0x0c600000ULL+(uint64_t)t->apid*0x10000,0x20,VM_WIMG_IO);
    if (!t->writer) return ENOMEM;
    uint32_t value[2]={};memcpy(value,data,bytes);
    power_wr(t->writer,0x10,value[0]);if (bytes>4) power_wr(t->writer,0x14,value[1]);
    if (!power_match(t)) {power_spmi_ok=false;return EAGAIN;}
    power_wr(t->writer,0,((address&255)<<4)|(bytes-1));
    int error=power_poll(t->writer,8);
    if (!error && !power_match(t)) {power_spmi_ok=false;error=EAGAIN;}
    return error;
}
static int power_bit(unsigned address,unsigned bit,bool on)
{
    if (bit!=1 || (address!=0x1042 && address!=0x1043)) return EINVAL;
    uint8_t old=0,after=0;int e=power_byte(P_CHGR,address,&old);if (e) return e;
    uint8_t intended=(uint8_t)(on ? old|bit : old&~bit);
    if (intended==old) return 0;
    if ((e=power_write(P_CHGR,address,&intended,1))) return e;
    if ((e=power_byte(P_CHGR,address,&after))) return e;
    if (after!=intended) {power_spmi_ok=false;return EIO;}return 0;
}
static int power_adc(unsigned channel,uint16_t *out)
{
    if (!out || (channel!=0x4a && channel!=8 && channel!=0x4f)) return EINVAL;
    uint8_t saved[5],wanted[5],before=0,status=0,sequence=0;
    int error=power_byte(P_ADC,0x3108,&status);
    if (error) return error;
    if (status&2) return EBUSY;
    if ((error=power_read(P_ADC,0x3142,saved,5)) || (error=power_byte(P_ADC,0x3109,&before))) return error;
    memcpy(wanted,saved,5);
    wanted[0]=(wanted[0]&~0x7c)|0x28; /* timer/absolute, native840 decimation */
    wanted[1]&=~7u;wanted[2]=(uint8_t)channel;
    wanted[3]=(wanted[3]&~15u)|2u;wanted[4]|=0x80;
    if ((error=power_write(P_ADC,0x3142,wanted,5))) return error;
    uint8_t request=0x80;
    if ((error=power_write(P_ADC,0x3147,&request,1))) return error;
    bool busy_seen=false,completed=false;
    for (unsigned ms=0;ms<100;++ms) {
        if ((error=power_byte(P_ADC,0x3108,&status)) || (error=power_byte(P_ADC,0x3109,&sequence))) return error;
        busy_seen|=(status&2)!=0;
        if ((status&3)==1 && (busy_seen || ((sequence^before)&0x70))) {completed=true;break;}
        IOSleep(1);
    }
    if (!completed) {power_spmi_ok=false;return ETIMEDOUT;}
    uint8_t raw[2]={};error=power_read(P_ADC,0x3150,raw,2);
    /* Restore only after a known completed conversion. Never restore/reuse an
     * uncertain live conversion, and never touch its interrupt registers. */
    if (!error) error=power_write(P_ADC,0x3142,saved,5);
    if (!error) {
        uint8_t actual[5];error=power_read(P_ADC,0x3142,actual,5);
        if (!error && memcmp(actual,saved,5)) {power_spmi_ok=false;error=EIO;}
    }
    if (!error) {*out=redfin_power_u16(raw);if (*out>0x7fff) error=ERANGE;}
    return error;
}
static bool power_spmi_init(void)
{
    power_core=ml_io_map_unmappable(0x0c440000,0x1100,VM_WIMG_IO);
    power_observer=ml_io_map_unmappable(0x0e600000,0x100000,VM_WIMG_IO);
    power_config=ml_io_map_unmappable(0x0c40a000,0x26000,VM_WIMG_IO);
    if (!power_core || !power_observer || !power_config) return false;
    power_version=power_rd(power_core,0);
    if (power_version<0x50000000 || power_version>=0x70000000) return false;
    for (unsigned i=0;i<512;++i) {
        uint32_t map=power_rd(power_core,0x900+i*4);unsigned ppid=(map>>8)&0xfff;
        if (!map) continue;
        for (unsigned j=0;j<P_COUNT;++j) {
            power_target *t=&power_targets[j];if (t->ppid!=ppid) continue;
            unsigned owner=power_rd(power_config,0x700+i*4)&7;
            if (t->apid==512 || owner==0) {*t=(power_target){ppid,i,owner,map,0};}
        }
    }
    power_spmi_ok=true;
    for (unsigned i=0;i<P_COUNT;++i) {
        const power_target *t=&power_targets[i];
        IOLog("REDFIN POWER APID: ppid=%#x apid=%u owner=%u mapped=%u\n",t->ppid,t->apid,t->owner,power_match(t));
    }
    uint8_t id[2]={};int error=power_read(P_REVID,0x0104,id,2);
    /* SID2 is physically PM7250B, not the unverified SID4 label. */
    IOLog("REDFIN POWER PMIC: type=%#x subtype=%#x result=%d\n",id[0],id[1],error);
    return !error && id[0]==0x51 && id[1]==0x2e;
}
static bool power_tsens_init(void)
{
    unsigned enabled=0;
    for (unsigned i=0;i<2;++i) {
        power_tsens *t=&power_ts[i];
        t->srot=ml_io_map_unmappable(power_contract[11+i*2],8,VM_WIMG_IO);
        t->tm=ml_io_map_unmappable(power_contract[12+i*2],0x1ff,VM_WIMG_IO);
        if (!t->srot || !t->tm) continue;
        uint32_t version=power_rd(t->srot,0);t->control=power_rd(t->srot,4);
        t->enabled=(t->control&1) ? (t->control>>3)&0xffff : 0;
        IOLog("REDFIN THERMAL TSENS: block=%u version=%#x control=%#x sensors=%#x inherited=1\n",i,version,t->control,t->enabled);
        enabled|=t->enabled;
    }
    return enabled!=0;
}
static bool power_temperatures(int32_t *hottest)
{
    unsigned good=0;int32_t maximum=-273150;
    for (unsigned i=0;i<2;++i) {
        power_tsens *t=&power_ts[i];if (!t->enabled) continue;
        if (power_rd(t->srot,4)!=t->control || !(power_rd(t->tm,0xe4)&8)) continue;
        for (unsigned j=0;j<16;++j) if (t->enabled&(1u<<j)) {
            int32_t mc=-273150;
            for (unsigned tries=0;tries<3;++tries)
                if (redfin_tsens_value(power_rd(t->tm,0xa0+4*j),&mc)) {++good;break;}
            if (mc>maximum) maximum=mc;
        }
    }
    if (!good) return false;
    *hottest=maximum;return true;
}
static void power_domains_init(void)
{
    for (unsigned i=0;i<3;++i) {
        power_domain *d=&power_domains[i];d->cores=i ? 1 : 6;
        d->normal=UINT32_MAX;
        d->base=ml_io_map_unmappable(power_contract[15+i],0x1000,VM_WIMG_IO);
        if (!d->base || !(power_rd(d->base,0)&1)) continue;
        uint32_t previous=0,previous_cores=0;
        for (unsigned row=0;row<40;++row) {
            uint32_t value=power_rd(d->base,0x110+32*row),cores=(value>>16)&7;
            uint32_t khz=(value>>30) ? 19200*(value&255) : 300000;
            if (row && khz==previous && cores==previous_cores) break;
            if (khz<100000 || khz>3000000 || (row && khz<previous)) {d->count=0;break;}
            d->rows[row]=value;d->khz[row]=khz;d->count=row+1;
            if (cores==d->cores) d->normal=row;
            previous=khz;previous_cores=cores;
        }
        d->boot=d->current=power_rd(d->base,0x920);
        d->valid=d->count>1 && d->count<40 && d->boot<d->count && d->normal<d->count;
        IOLog("REDFIN THERMAL OSM: domain=%u rows=%u boot-row=%u boot-khz=%u normal-row=%u normal-khz=%u valid=%u standard-layout=1\n",
            i,d->count,d->boot,d->valid ? d->khz[d->boot] : 0,d->normal,
            d->valid ? d->khz[d->normal] : 0,d->valid);
    }
}
static void power_limit_domains(unsigned pressure)
{
    for (unsigned i=0;i<3;++i) {
        power_domain *d=&power_domains[i];if (!d->valid) continue;
        /* The bootloader's low startup row is not a runtime governor. Use
         * the highest hardware-provided row for this domain's real core
         * count only while real TSENS data permits it. OSM owns voltage. */
        uint32_t cap=d->khz[d->normal],target=d->normal;
        if (pressure==1) cap=cap*3/4;
        if (pressure==2) cap=cap/2;
        if (pressure>=3) cap=300000;
        if (pressure) {
            target=UINT32_MAX;
            for (unsigned r=0;r<=d->normal;++r)
                if (((d->rows[r]>>16)&7)==d->cores && d->khz[r]<=cap) target=r;
            if (target==UINT32_MAX) {d->valid=false;continue;}
        }
        bool exact=(power_rd(d->base,0)&1) && power_rd(d->base,0x920)==d->current;
        for (unsigned r=0;r<d->count && exact;++r) exact=power_rd(d->base,0x110+32*r)==d->rows[r];
        if (!exact) {d->valid=false;IOLog("REDFIN THERMAL OSM: domain=%u foreign state changed; no write\n",i);continue;}
        if (target==d->current) continue;
        power_wr(d->base,0x920,target);
        if (power_rd(d->base,0x920)!=target) {d->valid=false;continue;}
        d->current=target;++power_throttles;
        IOLog("REDFIN THERMAL LIMIT: domain=%u pressure=%u row=%u khz=%u hardware-voltage-owned=1\n",i,pressure,target,d->khz[target]);
    }
}
static void power_clock(IORegistryEntry *node)
{
    OSData *data=OSDynamicCast(OSData,node->getProperty("rtc-anchor"));
    uint64_t anchor[2]={};
    if (!data || data->getLength()!=sizeof(anchor)) return;
    memcpy(anchor,data->getBytesNoCopy(),sizeof(anchor));
    uint8_t enabled=0,bytes[4]={},lsb=0;
    int error=power_byte(P_RTC,0x6046,&enabled);
    if (!error && (enabled&0x80)) error=power_read(P_RTC,0x6048,bytes,4);
    else if (!error) error=ENXIO;
    if (!error) error=power_byte(P_RTC,0x6048,&lsb);
    if (!error && lsb<bytes[0]) error=power_read(P_RTC,0x6048,bytes,4);
    uint32_t raw=(uint32_t)bytes[0]|((uint32_t)bytes[1]<<8)|((uint32_t)bytes[2]<<16)|((uint32_t)bytes[3]<<24);
    uint64_t epoch=(uint64_t)raw+anchor[1];
    bool valid=!error && anchor[0]>0 && anchor[0]<=UINT32_MAX && raw>=anchor[0] &&
        raw-anchor[0]<5ULL*366*86400 && epoch>=1577836800 && epoch<4102444800ULL;
    if (valid) clock_set_calendar_microtime((clock_sec_t)epoch,0);
    IOLog("REDFIN RTC: anchor-valid=%u read-error=%d physical-counter=1 PMIC-time-write=0 calendar-set=%u\n",valid,error,valid);
}
static int power_battery(struct redfin_power_sample *s)
{
    *s=(struct redfin_power_sample){};s->version=RF_POWER_ABI;s->bytes=sizeof(*s);
    uint8_t header[2]={},qg_status=0,raw[2]={},mono=0,chg[2]={},temp_status=0,enabled=0,fv=0,batif=0,path=0,usb=0,dc=0;
    int e=power_read(P_QG,0x4804,header,2);if (e) return e;
    if (header[0]!=0x0d || (header[1]!=3 && header[1]!=4)) return ENOTSUP;
    if ((e=power_byte(P_QG,0x4808,&qg_status)) || (e=power_byte(P_BATIF,0x1210,&batif))) return e;
    if (!(qg_status&0x80)) return EAGAIN;
    s->present=(qg_status&1)!=0 && !(batif&0x30);
    if ((e=power_read(P_QG,0x48c0,raw,2))) return e;
    s->voltage_uv=redfin_qg_voltage(redfin_power_u16(raw));s->valid|=RF_POWER_VOLTAGE;
    if ((e=power_read(P_QG,0x48c2,raw,2))) return e;
    s->current_ua=redfin_qg_current(redfin_power_u16(raw),header[1]);s->valid|=RF_POWER_CURRENT;
    if ((e=power_byte(P_QG,0x48bf,&mono))) return e;
    s->soc_hundredths=(mono*10000+127)/255;s->valid|=RF_POWER_SOC;
    uint16_t adc=0;
    if ((e=power_adc(0x4a,&adc))) return e;
    if (!redfin_adc5_battery_temp(adc,&s->temperature_mc)) return ERANGE;
    s->valid|=RF_POWER_TEMP;
    if ((e=power_read(P_CHGR,0x1006,chg,2)) || (e=power_byte(P_CHGR,0x100d,&temp_status)) ||
        (e=power_byte(P_CHGR,0x100b,&enabled)) || (e=power_byte(P_CHGR,0x1070,&fv)) ||
        (e=power_byte(P_DCDC,0x110b,&path)) || (e=power_byte(P_USB,0x1310,&usb)) ||
        (e=power_byte(P_DC,0x1410,&dc))) return e;
    s->wireless=(dc&0x10) && (path&8);s->external=(path&1) && ((usb&0x10) || s->wireless);
    int32_t float_uv=3600000+fv*10000;
    s->charger_faults=redfin_smb5_faults(chg[1],temp_status,s->voltage_uv,float_uv);
    redfin_smb5_state(s,chg[0],enabled);
    static uint32_t previous_status=UINT32_MAX;
    uint32_t packed=chg[0]|((uint32_t)chg[1]<<8)|((uint32_t)temp_status<<16)|((uint32_t)enabled<<24);
    if (packed!=previous_status) {
        previous_status=packed;
        IOLog("REDFIN SMB5 STATUS: raw1=%#x raw2=%#x raw5=%#x raw7=%#x native-FV-uV=%d actual-V-uV=%d hard-faults=%#x full=%d charging=%d\n",
            chg[0],chg[1],enabled,temp_status,float_uv,s->voltage_uv,s->charger_faults,s->full,s->charging);
    }
    s->valid|=RF_POWER_CHARGER;
    if (!power_read(P_SDAM,0xb168,raw,2)) {
        unsigned full=redfin_power_u16(raw);
        if (full>=500 && full<=6000) {
            s->full_uah=(int32_t)full*1000;s->design_uah=4000000;s->valid|=RF_POWER_CAPACITY;
        }
    }
    if (!power_byte(P_DCDC,0x1107,&usb)) s->usb_current_ua=usb*50000;
    if (s->external && !s->wireless && !power_adc(8,&adc))
        s->usb_voltage_uv=(int32_t)((uint64_t)adc*1875000*16/0x70e4);
    if (!power_byte(P_USB,0x1308,&usb)) s->usb_type=(usb&1) ? 1 : (usb&4) ? 3 : (usb&8) ? 2 : 5;
    (void)redfin_soc_update(&power_soc_tracker,s,power_now());
    if (!power_spmi_ok) return EIO;
    return redfin_power_valid(s) ? 0 : ERANGE;
}
static void power_charge_policy(const struct redfin_power_sample *s)
{
    if (redfin_charger_must_pause(s)) {
        int e=power_bit(0x1043,1,true);
        static unsigned reports;
        if (e || reports++<2 || !(reports&(reports-1)))
            IOLog("REDFIN CHARGE GUARD: paused=1 valid=%u temp-mC=%d fault=%#x error=%d\n",redfin_power_valid(s),s->temperature_mc,s->charger_faults,e);
        return;
    }
    if (!s->external || s->full) return;
    uint8_t fv=0,fcc=0,timer=0,jeita=0;
    if (power_byte(P_CHGR,0x1070,&fv) || power_byte(P_CHGR,0x1061,&fcc) ||
        power_byte(P_CHGR,0x10a0,&timer) || power_byte(P_CHGR,0x1090,&jeita)) return;
    bool permitted=redfin_charger_enable_allowed(s,3600000+fv*10000,fcc*50000,timer,jeita);
    if (!permitted) {
        static unsigned refused;
        if (refused++<2) IOLog("REDFIN CHARGE ADMISSION: permitted=0 FV-uV=%u FCC-uA=%u timer=%#x JEITA=%#x inherited-limits=1\n",3600000+fv*10000,fcc*50000,timer,jeita);
        return;
    }
    int e=power_bit(0x1042,1,true);if (!e) e=power_bit(0x1043,1,false);
    static unsigned reports;
    if (e || reports++<2) IOLog("REDFIN CHARGE POLICY: enable-request=1 error=%d FV-uV=%u FCC-uA=%u inherited-limits=1 JEITA=1 safety-timer=1\n",e,3600000+fv*10000,fcc*50000);
}
} /* namespace */

/* Same native IOPMPowerSource boundary as the preferred RedwoodBattery. */
class RedfinBattery:public IOPMPowerSource {
    OSDeclareDefaultStructors(RedfinBattery);
public:
    void report(const struct redfin_power_sample *s) {
        if (!redfin_power_valid(s)) return;
        setBatteryInstalled(s->present);setExternalConnected(s->external);
        setExternalChargeCapable(s->external);setIsCharging(s->charging);
        setCurrentCapacity((s->soc_hundredths+50)/100);setMaxCapacity(100);
        setVoltage(s->voltage_uv/1000);setAmperage(s->current_ua/1000);
        number("InstantAmperage",s->current_ua/1000);number("Temperature",s->temperature_mc/10);
        flag("FullyCharged",s->full);flag("AppleRawExternalConnected",s->external);
        flag("RedfinDataStale",false);flag("RedfinCoulombIntegrated",s->soc_integrated);
        if (s->valid&RF_POWER_CAPACITY) {
            number("AppleRawCurrentCapacity",s->charge_uah/1000);
            number("AppleRawMaxCapacity",s->full_uah/1000);number("NominalChargeCapacity",s->full_uah/1000);
            number("DesignCapacity",s->design_uah/1000);
        }
        OSDictionary *adapter=OSDictionary::withCapacity(6);
        if (adapter) {
            unsigned family=!s->external ? 0 : s->usb_type==1 ? 0xe0004000u : s->usb_type==2 ? 0xe0004004u : s->usb_type==3 ? 0xe0004005u : 0xe0004009u;
            dict_number(adapter,kIOPMPSAdapterDetailsFamilyKey,family);
            dict_number(adapter,kIOPMPSAdapterDetailsVoltage,s->usb_voltage_uv/1000);
            dict_number(adapter,kIOPMPSAdapterDetailsAmperageKey,s->usb_current_ua/1000);
            dict_number(adapter,kIOPMPSAdapterDetailsWattsKey,(int64_t)s->usb_voltage_uv*s->usb_current_ua/1000000000000LL);
            adapter->setObject("IsWireless",s->wireless ? kOSBooleanTrue : kOSBooleanFalse);
            const OSSymbol *key=OSSymbol::withCString(kIOPMPSAdapterDetailsKey);
            if (key) {setPSProperty(key,adapter);key->release();}adapter->release();
        }
        updateStatus();
    }
    void stale(void) {flag("RedfinDataStale",true);setIsCharging(false);updateStatus();}
private:
    static void dict_number(OSDictionary *d,const char *key,int64_t value) {
        OSNumber *n=OSNumber::withNumber((uint64_t)value,32);if (n) {d->setObject(key,n);n->release();}
    }
    void number(const char *name,int64_t value) {
        const OSSymbol *key=OSSymbol::withCString(name);OSNumber *n=OSNumber::withNumber((uint64_t)value,32);
        if (key && n) setPSProperty(key,n);OSSafeReleaseNULL(n);OSSafeReleaseNULL(key);
    }
    void flag(const char *name,bool value) {
        const OSSymbol *key=OSSymbol::withCString(name);if (key) {setPSProperty(key,value ? kOSBooleanTrue : kOSBooleanFalse);key->release();}
    }
};
OSDefineMetaClassAndStructors(RedfinBattery,IOPMPowerSource);
static RedfinBattery *redfin_battery;
static void redfin_power_report(const struct redfin_power_sample *s)
{
    if (redfin_battery) {redfin_battery->report(s);return;}
    IOService *provider=IOService::getPlatform();RedfinBattery *b=OSTypeAlloc(RedfinBattery);
    if (!provider || !b || !b->init()) {OSSafeReleaseNULL(b);return;}
    if (!b->attach(provider)) {b->release();return;}
    if (!b->start(provider)) {b->detach(provider);b->release();return;}
    b->setName("RedfinBattery");b->report(s);b->registerService();redfin_battery=b;
    IOLog("REDFIN POWER SOURCE: native IOPMPowerSource registered battery=%d external=%d SOC-hundredths=%d\n",s->present,s->external,s->soc_hundredths);
}
SYSCTL_NODE(_kern,OID_AUTO,redfin_power,CTLFLAG_RD|CTLFLAG_LOCKED,0,"Redfin native power and thermals");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,thermal_running,CTLFLAG_RD|CTLFLAG_LOCKED,&power_running,0,"real TSENS inputs available");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,thermal_pressure,CTLFLAG_RD|CTLFLAG_LOCKED,&power_pressure,0,"iOS thermal pressure0..4");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,hottest_mc,CTLFLAG_RD|CTLFLAG_LOCKED,&power_hottest,0,"hottest actual SoC sensor mC");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,battery_mc,CTLFLAG_RD|CTLFLAG_LOCKED,&power_battery_mc,0,"actual battery temperature mC");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,battery_soc,CTLFLAG_RD|CTLFLAG_LOCKED,&power_soc,0,"actual seed/integrated SOC hundredths");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,battery_uv,CTLFLAG_RD|CTLFLAG_LOCKED,&power_uv,0,"actual QG battery uV");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,battery_ua,CTLFLAG_RD|CTLFLAG_LOCKED,&power_ua,0,"actual QG battery uA positive into battery");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,external,CTLFLAG_RD|CTLFLAG_LOCKED,&power_external,0,"SMB5 input source present");
SYSCTL_INT(_kern_redfin_power,OID_AUTO,charging,CTLFLAG_RD|CTLFLAG_LOCKED,&power_charging,0,"SMB5 actual charging state");
static void redfin_power_worker(void *parameter,wait_result_t result __unused)
{
    IORegistryEntry *node=(IORegistryEntry *)parameter;
    bool pmic=power_spmi_init();power_clock(node);node->release();
    bool thermal=power_tsens_init();power_domains_init();
    IOLog("REDFIN POWER: PMIC-ready=%u TSENS-ready=%u software-keychain-independent=1\n",pmic,thermal);
    unsigned missing=0;bool retired=false;
    for (unsigned tick=0;;++tick) {
        int32_t hottest=-273150;
        bool measured=thermal && power_temperatures(&hottest);
        if (measured) {power_hottest=hottest;missing=0;power_running=1;}
        else if (++missing>=16 && power_running) power_pressure=2;
        if (pmic && !power_spmi_ok && !retired) {
            retired=true;power_battery_mc=-273150;power_charging=power_external=-1;
            if (redfin_battery) redfin_battery->stale();
            IOLog("REDFIN POWER: uncertain SPMI completion/state; no further transactions until reset, native charger protections retained\n");
        }
        if (pmic && power_spmi_ok && !(tick%4)) {
            struct redfin_power_sample sample;int error=power_battery(&sample);
            if (!error) {
                ++power_samples;power_battery_mc=sample.temperature_mc;power_soc=sample.soc_hundredths;
                power_uv=sample.voltage_uv;power_ua=sample.current_ua;power_external=sample.external;power_charging=sample.charging;
                power_charge_policy(&sample);redfin_power_report(&sample);
                static unsigned last_soc=UINT32_MAX;
                unsigned soc=(sample.soc_hundredths+50)/100;
                if (sample.soc_integrated && soc!=last_soc) {
                    uint8_t raw=(uint8_t)(soc*255/100);
                    if (!power_write(P_QG,0x48bf,&raw,1)) last_soc=soc;
                }
            } else {
                ++power_errors;if (redfin_battery) redfin_battery->stale();
                /* A bad/missing battery temperature cannot authorize charging. */
                if (power_spmi_ok) (void)power_bit(0x1043,1,true);
                if (power_errors<5) IOLog("REDFIN POWER SAMPLE: error=%d retained-SPMI=%u paused-if-accessible=1\n",error,power_spmi_ok);
            }
        }
        if (measured) power_pressure=(int)redfin_thermal_pressure(power_hottest,power_battery_mc,(unsigned)power_pressure);
        if (power_running) power_limit_domains(missing>=16 ? 4u : (unsigned)power_pressure);
        if (!(tick%40)) IOLog("REDFIN POWER STATUS: samples=%u errors=%u hot-mC=%d battery-mC=%d SOC-hundredths=%d V-uV=%d I-uA=%d external=%d charging=%d pressure=%d throttle-writes=%u\n",
            power_samples,power_errors,power_hottest,power_battery_mc,power_soc,power_uv,power_ua,power_external,power_charging,power_pressure,power_throttles);
        if ((measured && power_hottest>=105000) || power_battery_mc>=55000) {
            IOLog("REDFIN THERMAL CRITICAL: actual threshold exceeded; requesting native clean shutdown\n");
            (void)reboot_kernel(0,NULL);break;
        }
        IOSleep(250);
    }
}
extern "C" void RedfinPowerStart(void)
{
    const char *args=PE_boot_args();unsigned bytes=0;if (args) while (bytes<608 && args[bytes]) ++bytes;
    if (!args || bytes==608 || !redfin_gpu_gui_profile(args,bytes+1,NULL) ||
        __atomic_exchange_n(&power_attempted,true,__ATOMIC_ACQ_REL)) return;
    IORegistryEntry *node=IORegistryEntry::fromPath("/redfin-power",gIODTPlane);if (!node) return;
    OSData *data=OSDynamicCast(OSData,node->getProperty("native-contract"));
    if (!data || data->getLength()!=sizeof(power_contract) || memcmp(data->getBytesNoCopy(),power_contract,sizeof(power_contract))) {node->release();return;}
    thread_t thread=THREAD_NULL;
    kern_return_t status=kernel_thread_start(redfin_power_worker,node,&thread);
    if (status==KERN_SUCCESS) thread_deallocate(thread);else node->release();
}
