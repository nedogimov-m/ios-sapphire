/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_SANDBOX_NATIVE_H
#define REDFIN_SANDBOX_NATIVE_H
#include <sys/proc.h>
#include <sys/types.h>
int redfin_sandbox_extension_call(proc_t,int,user_addr_t);
void redfin_sandbox_extension_exit(proc_t);
#endif
