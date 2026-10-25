/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_METAL_COMMAND_SCOPE_H
#define REDFIN_METAL_COMMAND_SCOPE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The Metal adapter holds the device's recursive Gallium mutex for the whole
 * command scope. Raster-only shaders may defer their CPU wait; compute and
 * memory-writing shaders retain immediate completion. Every scope exit pays
 * the real final fence, including a partially encoded command that failed.
 * A failed GPU completion permanently retires this scope, without a retry. */
struct redfin_metal_command_scope {
    bool active,pending,failed;
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
    if (!s || s->failed || !finish) return -1;
    if (!s->pending) return 0;
    int error=finish(context,why,bytes);
    if (error) {s->failed=true;return error;}
    s->pending=false;return 0;
}
static inline int redfin_metal_scope_prepare(struct redfin_metal_command_scope *s,
    bool raster_only,redfin_metal_finish_fn finish,void *context,char *why,size_t bytes)
{
    if (!s || s->failed) return -1;
    return raster_only ? 0 : redfin_metal_scope_drain(s,finish,context,why,bytes);
}
static inline int redfin_metal_scope_complete(struct redfin_metal_command_scope *s,
    bool raster_only,redfin_metal_finish_fn finish,void *context,char *why,size_t bytes)
{
    if (!s || s->failed) return -1;
    s->pending=true;
    if (s->active && raster_only) {++s->deferred_draws;return 0;}
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
