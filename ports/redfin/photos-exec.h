/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_PHOTOS_EXEC_H
#define REDFIN_PHOTOS_EXEC_H
#include <string.h>
#include <stdbool.h>
#include <arm64/redfin_gui_profile.h>

static inline bool redfin_photos_exec_selected(const char *args, unsigned bytes, const char *saved)
{
    return args && saved && redfin_gpu_gui_profile(args, bytes, NULL) &&
        (!strcmp(saved, "executable_path=/redfin/bin/photos-init") ||
         !strcmp(saved, "executable_path=/redfin/bin/gui-check") ||
         !strcmp(saved, "executable_path=/redfin/bin/metal-check"));
}
static inline bool redfin_photos_exec_signature(unsigned flags, bool platform)
{
    /* Native load_machfile must have validated the initial code page and the
     * original root-signature policy must have assigned the platform status.
     * A requested entitlement alone can never make a damaged helper valid. */
    const unsigned required = 0x20000000u | 0x4000u | 0x1200u | 1u;
    return platform && (flags & required) == required;
}
#endif
