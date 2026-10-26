/* SPDX-License-Identifier: MIT */
#ifndef REDFIN_GLES_FRAME_BUDGET_H
#define REDFIN_GLES_FRAME_BUDGET_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Included after the actual GL declarations. These are retained GL sync
 * objects, never a timer or a synthetic GPU completion. The current frame's
 * fence is made before its ordinary flush/publication. Two earlier published
 * frames may overlap; the next frame waits for the oldest real fence first. */
#define RF_GL_FRAME_DEPTH 2u
#define RF_GL_ALREADY_SIGNALED 0x911au
#define RF_GL_CONDITION_SATISFIED 0x911cu
#define RF_GL_FRAME_TIMEOUT_NS UINT64_C(2000000000)
struct rf_gl_frame_budget {
    GLsync fences[RF_GL_FRAME_DEPTH];
    unsigned head,count,maximum,waits,already,completed,fallbacks;
    bool disabled;
};

static inline void rf_gl_frame_clear(struct rf_gl_frame_budget *budget)
{
    for(unsigned i=0;i<RF_GL_FRAME_DEPTH;++i)if(budget->fences[i]) {
        glDeleteSync(budget->fences[i]);budget->fences[i]=NULL;
    }
    budget->head=budget->count=0;
}

static inline void rf_gl_frame_fail(struct rf_gl_frame_budget *budget)
{
    /* A failed fence cannot release pixels. Keep the ordinary full GPU wait
     * and permanently use that conservative path for this context. */
    glFinish();rf_gl_frame_clear(budget);
    budget->disabled=true;++budget->fallbacks;
}

static inline bool rf_gl_frame_begin(struct rf_gl_frame_budget *budget)
{
    if(budget->disabled)return false;
    if(budget->count<RF_GL_FRAME_DEPTH)return true;
    GLsync fence=budget->fences[budget->head];
    if(!fence){rf_gl_frame_fail(budget);return false;}
    GLenum result=glClientWaitSync(fence,0,RF_GL_FRAME_TIMEOUT_NS);
    ++budget->waits;
    if(result!=RF_GL_ALREADY_SIGNALED && result!=RF_GL_CONDITION_SATISFIED) {
        rf_gl_frame_fail(budget);return false;
    }
    if(result==RF_GL_ALREADY_SIGNALED)++budget->already;else ++budget->completed;
    glDeleteSync(fence);budget->fences[budget->head]=NULL;
    budget->head=(budget->head+1)%RF_GL_FRAME_DEPTH;--budget->count;
    return true;
}

static inline bool rf_gl_frame_publish(struct rf_gl_frame_budget *budget,GLsync fence)
{
    if(budget->disabled || !fence || budget->count>=RF_GL_FRAME_DEPTH) {
        /* The unrecorded object still belongs to this caller. */
        rf_gl_frame_fail(budget);if(fence)glDeleteSync(fence);return false;
    }
    unsigned slot=(budget->head+budget->count)%RF_GL_FRAME_DEPTH;
    budget->fences[slot]=fence;++budget->count;
    if(budget->count>budget->maximum)budget->maximum=budget->count;
    return true;
}
#endif
