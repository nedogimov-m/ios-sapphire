/* SPDX-License-Identifier: MIT */
/* Exercise the same bounded real-GL-fence code as backboardd, with alternating
 * imported surfaces, changed pixels on every reuse and untouched padded tails.
 * This is part of the complete native graphics check, never an app launch. */
static int redfin_gles_budget_check(void)
{
#if REDFIN_GLES_PUBLICATION
    enum {BW=80,BH=61,BP=320,EXTENT=BP*64,ALLOC=32768,ROUNDS=12};
    IOSurfaceRef surfaces[2]={NULL,NULL};GLuint textures[2]={0,0},fb[2]={0,0};
    struct rf_gu_target targets[2];size_t lengths[2]={0,0};
    struct rf_gl_frame_budget budget={0};
    ImageTexture image=(ImageTexture)OSMesaGetProcAddress("glEGLImageTargetTexture2DOES");
    if(!image)return 40;
    for(unsigned i=0;i<2;++i) {
        CFMutableDictionaryRef d=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
        number(d,kIOSurfaceWidth,BW);number(d,kIOSurfaceHeight,BH);number(d,kIOSurfaceBytesPerRow,BP);
        number(d,kIOSurfaceBytesPerElement,4);number(d,kIOSurfaceAllocSize,ALLOC);number(d,kIOSurfacePixelFormat,0x42475241);
        surfaces[i]=IOSurfaceCreate(d);CFRelease(d);
        if(!surfaces[i] || IOSurfaceLock(surfaces[i],0,NULL))return 41;
        lengths[i]=IOSurfaceGetAllocSize(surfaces[i]);
        if(lengths[i]<ALLOC || IOSurfaceGetBytesPerRow(surfaces[i])!=BP)return 42;
        memset(IOSurfaceGetBaseAddress(surfaces[i]),0xa7,lengths[i]);IOSurfaceUnlock(surfaces[i],0,NULL);
        glGenTextures(1,&textures[i]);glBindTexture(GL_TEXTURE_2D,textures[i]);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
        image(GL_TEXTURE_2D,(void *)(uintptr_t)IOSurfaceGetID(surfaces[i]));
        targets[i]=(struct rf_gu_target){redfin_gl_surface_producer(IOSurfaceGetID(surfaces[i])),IOSurfaceGetID(surfaces[i])};
        glGenFramebuffers(1,&fb[i]);glBindFramebuffer(GL_FRAMEBUFFER,fb[i]);
        glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,textures[i],0);
        if(!targets[i].handle || glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE || glGetError())return 43;
    }
    glViewport(0,0,BW,BH);glDisable(GL_SCISSOR_TEST);glDisable(GL_DITHER);
    unsigned checked=0;size_t guards=0;
    for(unsigned pass=0;pass<ROUNDS+2;++pass) {
        unsigned slot=pass%2;
        if(!rf_gl_frame_begin(&budget))return 44;
        if(pass>=2) {
            unsigned old=pass-2;
            if(IOSurfaceLock(surfaces[slot],kIOSurfaceLockReadOnly,NULL))return 45;
            const uint8_t *data=IOSurfaceGetBaseAddress(surfaces[slot]);
            const uint8_t expected[]={(uint8_t)(128+2*old),(uint8_t)(48+4*old),(uint8_t)(32+8*old),255};
            for(unsigned y=0;y<BH;++y)for(unsigned x=0;x<BW;++x) {
                if(!close_color(data+y*BP+x*4,expected))return 46;++checked;
            }
            for(size_t at=EXTENT;at<lengths[slot];++at) {if(data[at]!=0xa7)return 47;++guards;}
            IOSurfaceUnlock(surfaces[slot],kIOSurfaceLockReadOnly,NULL);
        }
        if(pass>=ROUNDS)continue;
        glBindFramebuffer(GL_FRAMEBUFFER,fb[slot]);
        glClearColor((32+8*pass)/255.0f,(48+4*pass)/255.0f,(128+2*pass)/255.0f,1);
        glClear(GL_COLOR_BUFFER_BIT);
        GLsync completion=glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE,0);
        glFlush();
        if(redfin_gl_publish_surfaces(&targets[slot],1) || !rf_gl_frame_publish(&budget,completion) || glGetError())return 48;
    }
    /* The last pending object belongs to already verified pixels too. */
    glFinish();rf_gl_frame_clear(&budget);
    if(budget.maximum!=2 || budget.waits!=ROUNDS-1 || budget.fallbacks || budget.disabled || checked!=BW*BH*ROUNDS)return 49;
    glDeleteFramebuffers(2,fb);glDeleteTextures(2,textures);
    for(unsigned i=0;i<2;++i)CFRelease(surfaces[i]);
    printf("REDFIN GLES BUDGET CHECK: boot=%016llx bound=2 rounds=%u maximum=%u waits=%u pixels=%u tail-guard-bytes=%zu real-GL-fences=1 CPU-pixels=1 result=0\n",
        (unsigned long long)boot_nonce,ROUNDS,budget.maximum,budget.waits,checked,guards);
#endif
    return 0;
}
