/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_COMPOSITOR_POLICY_H
#define REDFIN_COMPOSITOR_POLICY_H
#include <stdbool.h>
#include <string.h>

#define REDFIN_COMPOSITOR_ENV "REDFIN_COMPOSITOR_API"

/* Only the render server selects a composition API. Metal discovery in apps,
 * including the native correctness checker, keeps its ordinary device path.
 * An absent setting preserves older roots; new jobs explicitly select GLES. */
static inline bool redfin_compositor_setting_valid(const char *setting)
{
    return !setting || !strcmp(setting,"gles") || !strcmp(setting,"metal");
}

static inline bool redfin_compositor_metal_allowed(const char *program,const char *setting)
{
    if(!program || strcmp(program,"backboardd"))return true;
    return !setting || !strcmp(setting,"metal");
}
#endif
