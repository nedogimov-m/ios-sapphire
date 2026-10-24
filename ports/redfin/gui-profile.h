/* Exact bounded GUI8 profile shared by the relocatable shim and XNU.
 * Display/touch geometry and the fenced HFS root are checked by their drivers.
 * No allocation, libc, device access or absolute pointer tables here. */
#ifndef REDFIN_GUI_PROFILE_H
#define REDFIN_GUI_PROFILE_H
#include <stdbool.h>
#include <stdint.h>
static inline bool redfin_gui_token(const char *p,unsigned bytes,const char *s)
{
 unsigned n=0;while(s[n]) { if(n>=bytes || p[n]!=s[n]) return false;n++; }
 return n==bytes;
}
static inline bool redfin_gui_profile(const char *args,unsigned bytes,uint64_t *boot_id)
{
 static const char required[][40]={
  "debug=0xc",
  "serial=3",
  "cpus=8",
  "keepsyms=1",
  "-noprogress",
  "rd=ufsroot0",
  "sweettouch=0",
  "sweetkeys=0",
  "sweetusb=0",
  "sweetcpufreq=0",
  "sweetbattery=0",
  "modem=0",
  "wifi=0",
  "gpu=0",
  "unentitled_ios_sim_launch=1",
  "ignition_level=1",
  "wdt_test=no_user_checkin",
  "launchd_unsecure_cache=1",
  "wdt=-1",
  "redfinfb=1",
  "sweetfb_noconsole=1",
  "redfinshutdown=180",
  "redfintouch=2",
  "redfinrail=1",
  "redfintouchsetup=1",
  "redfinrpmhtouch=1",
  "redfintouchevents=1",
  "redfinufs=3",
  "redfinspmi=0",
  "redfinreturn=0",
  "redfinroot=1",
  "ufsroot=userdata",
  "ufsrw=1",
  "rootrw=1",
  "sweetlog=0",
  "redfinsmp=1",
  "redfinshim=1",
  "redfingui=1",
 };
 const unsigned count=sizeof(required)/sizeof(required[0]);
 _Static_assert(sizeof(required)/sizeof(required[0])<64,"GUI argument bitmap");
 if(!args || !bytes || bytes>608 || args[bytes-1]) return false;
 unsigned length=0;while(length<bytes && args[length]) length++;
 if(!length || length==bytes) return false;
 for(unsigned tail=length;tail<bytes;tail++) if(args[tail]) return false;
 uint64_t seen=0,nonce=0;
 bool nonce_seen=false,trace_seen=false,cadence_seen=false,screen_seen=false;
 unsigned fit_mode=0;
 for(unsigned pos=0;pos<length;) {
  if(args[pos]==' ') { pos++;continue; }
  unsigned start=pos;
  while(pos<length && args[pos]!=' ') {
   if((unsigned char)args[pos]<33 || (unsigned char)args[pos]>126) return false;
   pos++;
  }
  unsigned n=pos-start;
  bool known=false;
  if(redfin_gui_token(args+start,n,"redfingui=2") || redfin_gui_token(args+start,n,"redfingui=3")) {
   uint64_t bit=1ULL<<(count-1);
   if(seen&bit) return false;
   seen|=bit;continue;
  }
  for(unsigned i=0;i<count;i++) if(redfin_gui_token(args+start,n,required[i])) {
   if(seen&(1ULL<<i)) return false;
   seen|=1ULL<<i;known=true;break;
  }
  if(known) continue;
  if(redfin_gui_token(args+start,n,"redfinfit=1") || redfin_gui_token(args+start,n,"redfinfit=2")) {
   if(fit_mode) return false;
   fit_mode=(unsigned)(args[start+n-1]-'0');continue;
  }
  if(redfin_gui_token(args+start,n,"redfinscreen=1")) {
   if(screen_seen) return false;
   screen_seen=true;continue;
  }
  if(redfin_gui_token(args+start,n,"sweetfb_hz=10") ||
     redfin_gui_token(args+start,n,"sweetfb_hz=30") ||
     redfin_gui_token(args+start,n,"sweetfb_hz=60")) {
   if(cadence_seen) return false;
   cadence_seen=true;continue;
  }
  if(redfin_gui_token(args+start,n,"-enable_kprintf_spam")) {
   if(trace_seen) return false;
   trace_seen=true;continue;
  }
  if(n==31 && redfin_gui_token(args+start,15,"redfinbootid=0x")) {
   if(nonce_seen) return false;
   for(unsigned i=15;i<31;i++) {
    unsigned digit=(unsigned)(args[start+i]-'0');
    if(digit>9) { if(args[start+i]<'a' || args[start+i]>'f') return false;digit=(unsigned)(args[start+i]-'a'+10); }
    nonce=(nonce<<4)|digit;
   }
   if(!nonce) return false;
   nonce_seen=true;continue;
  }
  return false;
 }
 if(seen!=((1ULL<<count)-1) || !nonce_seen || !cadence_seen || (screen_seen && fit_mode!=2)) return false;
 if(boot_id) *boot_id=nonce;
 return true;
}
/* Mode2 composes the proven GUI8 root/touch lease with native WLAN. It uses
 * the same bounded command length; all ordinary GUI1 tokens remain exact. */
static inline bool redfin_wifi_gui_profile(const char *args,unsigned bytes,uint64_t *boot_id)
{
 if(!redfin_gui_profile(args,bytes,boot_id)) return false;
 for(unsigned at=0;at<bytes && args[at];) {
  if(args[at]==' ') {at++;continue;}
  unsigned first=at;while(at<bytes && args[at] && args[at]!=' ')at++;
  if(redfin_gui_token(args+first,at-first,"redfingui=2") ||
     redfin_gui_token(args+first,at-first,"redfingui=3")) return true;
 }
 return false;
}
/* GUI3 retains the complete GUI2/WLAN contract and explicitly selects the
 * separately bound A620 runtime. It adds no tokens to the 608-byte field. */
static inline bool redfin_gpu_gui_profile(const char *args,unsigned bytes,uint64_t *boot_id)
{
 if(!redfin_gui_profile(args,bytes,boot_id)) return false;
 for(unsigned at=0;at<bytes && args[at];) {
  if(args[at]==' ') {at++;continue;}
  unsigned first=at;while(at<bytes && args[at] && args[at]!=' ')at++;
  if(redfin_gui_token(args+first,at-first,"redfingui=3")) return true;
 }
 return false;
}
#endif /* REDFIN_GUI_PROFILE_H */
