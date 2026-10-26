/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GLES_MEMORY_POLICY_H
#define REDFIN_GLES_MEMORY_POLICY_H
#include <string.h>
#define REDFIN_GLES_MEMORY_ENV "REDFIN_GLES_MEMORY"

/* Backboardd's GLES pipeline has full native sysmem/fetch/surface coverage.
 * Use direct GPU writes there; applications and Metal keep Mesa's ordinary
 * policy. Explicit auto and unknown settings retain the original selection. */
static inline const char *redfin_gles_memory_debug(const char *program,
    const char *api,const char *setting)
{
    if(!program || strcmp(program,"backboardd") || !api || strcmp(api,"gles"))return "";
    return !setting || !strcmp(setting,"sysmem") ? "sysmem" : "";
}
#endif
