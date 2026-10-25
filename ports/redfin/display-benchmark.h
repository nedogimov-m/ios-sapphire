/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_DISPLAY_BENCHMARK_H
#define REDFIN_DISPLAY_BENCHMARK_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define REDFIN_DISPLAY_PROBE_REQUEST "/redfin/display-probe-request"
enum {RF_DISPLAY_PROBE_NONE,RF_DISPLAY_PROBE_PASSIVE,RF_DISPLAY_PROBE_ANIMATE};
/* A root-owned regular control file selects one boot only. No persistent
 * animation is enabled by installing the adapter or by reading statistics. */
static inline unsigned redfin_display_probe_request(const char *data,size_t bytes,uint64_t nonce)
{
    static const char prefix[]="redfin-probe-v1:";
    static const char suffix[2][10]={":passive\n",":animate\n"};
    const size_t head=sizeof(prefix)-1,tail=sizeof(suffix[0])-1;
    if(!data||!nonce||bytes!=head+16+tail||memcmp(data,prefix,head))return RF_DISPLAY_PROBE_NONE;
    uint64_t found=0;
    for(unsigned i=0;i<16;++i) {
        unsigned c=(unsigned char)data[head+i],digit;
        if(c>='0'&&c<='9')digit=c-'0';
        else if(c>='a'&&c<='f')digit=c-'a'+10;
        else return RF_DISPLAY_PROBE_NONE;
        found=(found<<4)|digit;
    }
    if(found!=nonce)return RF_DISPLAY_PROBE_NONE;
    for(unsigned i=0;i<2;++i)if(!memcmp(data+head+16,suffix[i],tail))return i+1;
    return RF_DISPLAY_PROBE_NONE;
}
#endif
