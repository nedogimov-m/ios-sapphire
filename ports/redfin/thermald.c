/* SPDX-License-Identifier: MIT */
/* Preferred HackiOS a79ff077 thermald's native notification boundary,
 * adapted to Redfin's TSENS26xx/OSM service and ordinary Apple launchd. */
#include <notify.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <unistd.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include "gui-profile.h"

static int native_value(const char *key,int *value)
{size_t n=sizeof(*value);return sysctlbyname(key,value,&n,NULL,0) || n!=sizeof(*value);}
int main(void)
{
    setvbuf(stdout,NULL,_IOLBF,0);
    char args[608]={},nonce[17]={};size_t n=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&n,NULL,0) || n>sizeof(args) ||
        !redfin_gpu_gui_profile(args,(unsigned)n,NULL)) return 0;
    const char *at=strstr(args,"redfinbootid=0x");if (!at || strlen(at+15)<16) return 2;
    memcpy(nonce,at+15,16);
    const char *notification="com.apple.system.thermalpressurelevel";
    int token=0,last=-1;uint32_t status=notify_register_check(notification,&token);
    if (status!=NOTIFY_STATUS_OK) {printf("REDFIN THERMAL NOTIFY: boot=%s register-error=%u\n",nonce,status);return 3;}
    for (unsigned tick=0;;++tick) {
        int running=0,level=-1,hot=-273150,battery=-273150;
        if (!native_value("kern.redfin_power.thermal_running",&running) && running &&
            !native_value("kern.redfin_power.thermal_pressure",&level) && level>=0 && level<=4) {
            uint64_t published=UINT64_MAX;
            uint32_t query_status=notify_get_state(token,&published);
            /* The stock monitor can still be present while its native sensor
             * backend is brought up. Reassert actual kernel pressure if a
             * stale writer replaced it, even without a new thermal crossing. */
            if (last!=level || query_status!=NOTIFY_STATUS_OK || published!=(uint64_t)level) {
                status=notify_set_state(token,(uint64_t)level);
                if (status==NOTIFY_STATUS_OK) status=notify_post(notification);
                uint64_t readback=UINT64_MAX;uint32_t read_status=notify_get_state(token,&readback);
                printf("REDFIN THERMAL NOTIFY: boot=%s pressure=%d post-status=%u read-status=%u exact=%u\n",
                    nonce,level,status,read_status,read_status==NOTIFY_STATUS_OK && readback==(uint64_t)level);
                if (status==NOTIFY_STATUS_OK && !read_status && readback==(uint64_t)level) last=level;
            }
            if (!(tick%10)) {
                (void)native_value("kern.redfin_power.hottest_mc",&hot);(void)native_value("kern.redfin_power.battery_mc",&battery);
                struct timeval now={};gettimeofday(&now,NULL);
                printf("REDFIN THERMAL INPUT: boot=%s hot-mC=%d battery-mC=%d pressure=%d calendar-valid=%u\n",
                    nonce,hot,battery,level,(uint64_t)now.tv_sec>=1577836800ULL);
            }
        }
        sleep(1);
    }
}
