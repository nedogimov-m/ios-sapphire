/* SPDX-License-Identifier: MIT */
/* Preferred bridge's transfers, with real publication and metadata-only GPU
 * producer notifications. Normal CPU copies/locks and the legacy path stay. */
static unsigned
redfin_eagl_produce_frame(struct eagl *e,bool finished,uint64_t *waited,unsigned *in_place)
{
    struct image *pending[RF_GU_MAX_TARGETS];
    struct rf_gu_target targets[RF_GU_MAX_TARGETS];
    unsigned count=0,announced=0,direct=0,mirrored=0,copied=0;
    for(unsigned i=0;i<e->image_count;++i) {
        struct image *image=&e->images[i];
        if(!image->target || !image->drawn || (!image->shared && !image->mirror))continue;
        pending[count++]=image;
        if(image->producer)targets[announced++]=(struct rf_gu_target){image->producer,IOSurfaceGetID(image->surface)};
        if(image->mirror)++mirrored;else ++direct;
    }
    e->producer_transfer=true;
    for(unsigned i=0;i<count;++i)target_to_surface(e,pending[i]);
    e->producer_transfer=false;
    bool asynchronous=count && e->in_frame && redfin_eagl_frame_budget_enabled() &&
        !finished && !wait_for_frames && !e->frame_budget.disabled;
    GLsync completion=asynchronous ? glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0) : NULL;
    if(count)glFlush(); /* Includes the mirror blit, if that fallback was used. */
    bool notified=count && announced==count && redfin_eagl_publish_surfaces(targets,count);
    /* An explicit Finish also covers a new mirror blit after its earlier
     * rendering wait. A failed announcement never substitutes for completion. */
    if(finished || (count && (wait_for_frames || !notified || e->frame_budget.disabled))) {
        glFinish();rf_gl_frame_clear(&e->frame_budget);
        if(completion)glDeleteSync(completion);
    } else if(asynchronous) {
        (void)rf_gl_frame_publish(&e->frame_budget,completion);
    }
    *waited=now_us();*in_place=count;
    if(!notified)for(unsigned i=0;i<count;++i) {
        IOSurfaceRef surface=pending[i]->surface;
        if(IOSurfaceLock(surface,0,NULL)==0)IOSurfaceUnlock(surface,0,NULL);
    }
    if(shown_texture)for(unsigned i=0;i<count;++i)show_texture(e,pending[i]);
    for(unsigned i=0;i<e->image_count;++i) {
        struct image *image=&e->images[i];
        if(image->target && image->drawn) {
            copied+=!image->shared;
            target_to_surface(e,image);
            if(shown_texture)show_texture(e,image);
        }
    }
    if(e->in_frame) {
        redfin_eagl_direct_frame(e->frames+1,direct,mirrored,notified);
        const struct rf_gl_frame_budget *budget=&e->frame_budget;
        redfin_eagl_frame_budget(e->frames+1,budget->count,budget->maximum,
            budget->waits,budget->already,budget->completed,budget->fallbacks);
    }
    return copied;
}
