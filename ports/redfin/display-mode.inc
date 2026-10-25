/* SPDX-License-Identifier: APSL-2.0 */
/* Mode publication adapted from preferred8e611870 MiniIOMobileFramebuffer.
 * Native20H392 IOMobileFramebuffer reads TimingElements/ColorElements and
 * selector79's current IDs; QuartzCore reads VerticalAttributes/SyncRate. */
#include "RedfinDisplayMode.h"
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSArray.h>
static void redfin_mode_number(OSDictionary *dictionary,const char *key,uint32_t value)
{
    OSNumber *number=OSNumber::withNumber(value,32);
    if (number) {dictionary->setObject(key,number);number->release();}
}
static bool redfin_publish_modes(IOService *fb,uint32_t width,uint32_t height,uint32_t hz)
{
    OSDictionary *timing=OSDictionary::withCapacity(8),*horizontal=OSDictionary::withCapacity(4);
    OSDictionary *vertical=OSDictionary::withCapacity(4),*color=OSDictionary::withCapacity(8);
    OSArray *timings=OSArray::withCapacity(1),*colors=OSArray::withCapacity(1);
    bool success=timing && horizontal && vertical && color && timings && colors;
    if (success) {
        redfin_mode_number(color,"ID",1);redfin_mode_number(color,"PixelEncoding",0);
        redfin_mode_number(color,"Depth",8);redfin_mode_number(color,"Colorimetry",1);
        redfin_mode_number(color,"EOTF",1);redfin_mode_number(color,"DynamicRange",0);
        redfin_mode_number(color,"Score",1);color->setObject("IsVirtual",kOSBooleanFalse);
        colors->setObject(color);
        redfin_mode_number(horizontal,"Active",width);redfin_mode_number(horizontal,"Total",width);
        redfin_mode_number(horizontal,"SyncRate",hz<<16);redfin_mode_number(horizontal,"PreciseSyncRate",hz<<16);
        redfin_mode_number(vertical,"Active",height);redfin_mode_number(vertical,"Total",height);
        redfin_mode_number(vertical,"SyncRate",hz<<16);redfin_mode_number(vertical,"PreciseSyncRate",hz<<16);
        redfin_mode_number(timing,"ID",1);redfin_mode_number(timing,"Score",1);
        timing->setObject("IsVirtual",kOSBooleanFalse);timing->setObject("IsOverscanned",kOSBooleanFalse);
        timing->setObject("HorizontalAttributes",horizontal);timing->setObject("VerticalAttributes",vertical);
        timing->setObject("ColorModes",colors);timings->setObject(timing);
        success=fb->setProperty("TimingElements",timings) && fb->setProperty("ColorElements",colors);
        /* hz90 can only reach this point after the panel's physical TE and
         * independent INTF counter admitted the transaction. Userland may
         * advertise it only with both of these measured-mode properties. */
        success=fb->setProperty("RedfinVerifiedRefreshHz",hz,32) && success;
        success=fb->setProperty("RedfinPhysicalRefreshVerified",hz==90) && success;
    }
    OSSafeReleaseNULL(timings);OSSafeReleaseNULL(colors);OSSafeReleaseNULL(timing);
    OSSafeReleaseNULL(horizontal);OSSafeReleaseNULL(vertical);OSSafeReleaseNULL(color);
    IOLog("REDFIN DISPLAY MODES: logical=%ux%u rate=%u current-color=1 current-timing=1 published=%u native20H392=1\n",
        width,height,hz,success);
    return success;
}
