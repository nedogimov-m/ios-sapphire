/* SPDX-License-Identifier: APSL-2.0
 * Preferred8e611870 kern_exec.c exec_inject_env ABI, scoped to the exact
 * Redfin GUI3 and Apple's absolute backboardd path. Stock launchd filters
 * DYLD_* in jobs; append this fixed environment entry during native exec.
 * No configurable injection list, other process, image code or argv changes.
 */
#include <arm64/redfin_gui_profile.h>

/* REDFIN_GRAPHICS_EXEC_TEST_BEGIN */
static bool redfin_graphics_exec_selected(const char *args,unsigned bytes,
    const char *saved_path,const char *name,unsigned name_bytes)
{
    /* exec_save_path stores EXECUTABLE_KEY before the original pathname;
     * ip_strings itself is the full Apple-vector string, not a bare path. */
    static const char key[]="executable_path=";
    return saved_path && !strncmp(saved_path,key,sizeof(key)-1) &&
        name && name_bytes==sizeof("backboardd")-1 &&
        !memcmp(name,"backboardd",sizeof("backboardd")-1) &&
        !strcmp(saved_path+sizeof(key)-1,"/usr/libexec/backboardd") &&
        redfin_gpu_gui_profile(args,bytes,NULL);
}
/* REDFIN_GRAPHICS_EXEC_TEST_END */

static bool redfin_graphics_exec_wanted(struct image_params *imgp)
{
    if(!imgp || !imgp->ip_ndp || !(imgp->ip_flags&IMGPF_IS_64BIT_ADDR))return false;
    const char *args=PE_boot_args();unsigned bytes=0;
    if(!args)return false;
    while(bytes<608 && args[bytes])bytes++;
    if(bytes==608)return false;
    return redfin_graphics_exec_selected(args,bytes+1,imgp->ip_strings,
        imgp->ip_ndp->ni_cnd.cn_nameptr,imgp->ip_ndp->ni_cnd.cn_namelen);
}
