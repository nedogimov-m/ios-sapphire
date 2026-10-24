/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_EAGL_GUARD_H
#define REDFIN_EAGL_GUARD_H
#include <stdint.h>
int redfin_eagl_validate(void);
int redfin_eagl_hardware(void);
int redfin_eagl_installed(void);
void redfin_eagl_mark_installed(unsigned methods);
void redfin_eagl_frame(unsigned frame,unsigned draws,unsigned triangles,
                       unsigned shared,unsigned copied,unsigned errors);
void redfin_eagl_set_tls(void *native_context);
#endif
