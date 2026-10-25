/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GRAPHICS_EXEC_SCOPE_H
#define REDFIN_GRAPHICS_EXEC_SCOPE_H
#include <stdbool.h>
#include <string.h>

/* Exact installed system executables. An app extension, renamed executable,
 * writable container or another process with the same comm is not admitted. */
static inline bool redfin_ui_executable(const char *path)
{
    static const char *const paths[] = {
        "/System/Library/CoreServices/SpringBoard.app/SpringBoard",
        "/Applications/Preferences.app/Preferences",
        "/Applications/MobilePhone.app/MobilePhone",
        "/Applications/MobileSlideShow.app/MobileSlideShow",
        "/Applications/AppStore.app/AppStore",
    };
    if (!path) return false;
    for (unsigned i=0;i<sizeof(paths)/sizeof(paths[0]);++i)
        if (!strcmp(path,paths[i])) return true;
    return false;
}
static inline bool redfin_ui_fullscreen(const char *args, unsigned bytes)
{
    if (!redfin_gpu_gui_profile(args,bytes,NULL)) return false;
    for (unsigned at=0;at<bytes && args[at];) {
        if (args[at]==' ') {++at;continue;}
        unsigned first=at;
        while (at<bytes && args[at] && args[at]!=' ') ++at;
        if (redfin_gui_token(args+first,at-first,"redfinfit=1")) return true;
    }
    return false;
}
/* Read-only native exception/authorization observations for an explicit
 * capture boot. Only these exact system daemons are eligible. */
static inline bool redfin_diagnostic_executable(const char *path)
{
    return path && (!strcmp(path,
        "/System/Library/Frameworks/AssetsLibrary.framework/Support/assetsd") || !strcmp(path,
        "/System/Library/PrivateFrameworks/TCC.framework/Support/tccd"));
}
static inline bool redfin_diagnostic_requested(const char *args,unsigned bytes)
{
    if (!redfin_gpu_gui_profile(args,bytes,NULL)) return false;
    for (unsigned at=0;at<bytes && args[at];) {
        if (args[at]==' ') {++at;continue;}
        unsigned first=at;
        while (at<bytes && args[at] && args[at]!=' ') ++at;
        if (redfin_gui_token(args+first,at-first,"redfinscreen=1")) return true;
    }
    return false;
}
#endif
