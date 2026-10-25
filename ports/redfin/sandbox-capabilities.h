/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_SANDBOX_CAPABILITIES_H
#define REDFIN_SANDBOX_CAPABILITIES_H
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#define RF_SBX_TOKEN_BYTES 2048u
#define RF_SBX_CLASS_BYTES 160u
#define RF_SBX_PATH_BYTES 1024u
#define RF_SBX_ENTRIES 512u
#define RF_SBX_HANDLES 2048u
#define RF_SBX_TARGET_PID 0x10000u
#define RF_SBX_TARGET_VERSION 0x20000u
struct rf_sbx_actor {uint32_t pid,version,uid,issuer;};
struct rf_sbx_request {
    uint32_t kind,flags,target_pid,target_version;
    char class_name[RF_SBX_CLASS_BYTES],resource[RF_SBX_PATH_BYTES];
};
struct rf_sbx_entry {
    uint32_t used,references,issuer_uid,target_pid,target_version,flags,kind;
    uint64_t generation;
    uint8_t tag[32];
    char class_name[RF_SBX_CLASS_BYTES],resource[RF_SBX_PATH_BYTES];
};
struct rf_sbx_handle {uint64_t value,generation;uint32_t entry,pid,version;};
struct rf_sbx_registry {
    uint64_t generation;
    struct rf_sbx_entry entry[RF_SBX_ENTRIES];
    struct rf_sbx_handle handle[RF_SBX_HANDLES];
};
struct rf_sbx_ops {
    void *context;
    int (*random)(void *,uint8_t *,size_t);
    /* Actual HMAC-SHA256 with a private per-boot key held by the adapter. */
    int (*mac)(void *,const uint8_t *,size_t,uint8_t[32]);
    void (*lock)(void *);
    void (*unlock)(void *);
};
#ifdef __cplusplus
extern "C" {
#endif
int rf_sbx_issue(struct rf_sbx_registry *,const struct rf_sbx_ops *,const struct rf_sbx_actor *,
    const struct rf_sbx_request *,char token[RF_SBX_TOKEN_BYTES]);
int rf_sbx_consume(struct rf_sbx_registry *,const struct rf_sbx_ops *,const struct rf_sbx_actor *,
    const char *,size_t bytes,uint64_t *handle);
int rf_sbx_release(struct rf_sbx_registry *,const struct rf_sbx_ops *,const struct rf_sbx_actor *,uint64_t handle);
void rf_sbx_exit(struct rf_sbx_registry *,const struct rf_sbx_ops *,const struct rf_sbx_actor *);
#ifdef __cplusplus
}
#endif
#endif
