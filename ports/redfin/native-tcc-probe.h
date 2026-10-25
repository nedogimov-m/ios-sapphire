/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_NATIVE_TCC_PROBE_H
#define REDFIN_NATIVE_TCC_PROBE_H
/* Repeat this process's ordinary, nonprompting native preflight request with
 * its real credential. Report the native record/error without replacing it. */
void redfin_native_tcc_probe(void (*report)(const char *,void *),void *context);
#endif
