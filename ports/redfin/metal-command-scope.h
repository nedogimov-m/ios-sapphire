/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_COMMAND_SCOPE_H
#define REDFIN_METAL_COMMAND_SCOPE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The Metal adapter holds the device's recursive Gallium mutex for the whole
 * command scope. Queue-ordered GPU operations defer their CPU wait; explicit
 * CPU consumers drain before reading changed bytes. Every scope exit pays
 * the real final fence, including a partially encoded command that failed.
 * A failed GPU completion permanently retires this scope, without a retry. */
struct redfin_metal_command_scope {
    bool active,pending,failed,completion_failed;
    uint64_t deferred_draws;
};
typedef int (*redfin_metal_finish_fn)(void *,char *,size_t);

static inline int redfin_metal_scope_begin(struct redfin_metal_command_scope *s)
{
    if (!s || s->active || s->pending || s->failed) return -1;
    s->active=true;return 0;
}
static inline int redfin_metal_scope_drain(struct redfin_metal_command_scope *s,
    redfin_metal_finish_fn finish,void *context,char *why,size_t bytes)
{
    if (!s || s->completion_failed || !finish) return -1;
    if (!s->pending) return s->failed?-1:0;
    int error=finish(context,why,bytes);
    if (error) {s->failed=true;s->completion_failed=true;return error;}
    s->pending=false;return s->failed?-1:0;
}
static inline int redfin_metal_scope_prepare(struct redfin_metal_command_scope *s,
    bool gpu_ordered,redfin_metal_finish_fn finish,void *context,char *why,size_t bytes)
{
    if (!s || s->failed) return -1;
    return gpu_ordered ? 0 : redfin_metal_scope_drain(s,finish,context,why,bytes);
}
static inline int redfin_metal_scope_complete(struct redfin_metal_command_scope *s,
    bool gpu_ordered,redfin_metal_finish_fn finish,void *context,char *why,size_t bytes)
{
    if (!s) return -1;
    s->pending=true;
    if(s->failed)return s->active?-1:redfin_metal_scope_drain(s,finish,context,why,bytes);
    if (s->active && gpu_ordered) {++s->deferred_draws;return 0;}
    return redfin_metal_scope_drain(s,finish,context,why,bytes);
}
static inline int redfin_metal_scope_end(struct redfin_metal_command_scope *s,
    redfin_metal_finish_fn finish,void *context,char *why,size_t bytes)
{
    if (!s || !s->active) return -1;
    int error=redfin_metal_scope_drain(s,finish,context,why,bytes);
    s->active=false;return error;
}
#endif
