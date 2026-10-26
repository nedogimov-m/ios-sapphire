/* SPDX-License-Identifier: MIT */
/* Full-screen, odd-height native framebuffer-fetch draws into an owned linear
 * IOSurface. CPU-lock is the first reader; a seed change is not completion. */
static int redfin_gles_direct_check(void)
{
#if REDFIN_GLES_PUBLICATION
    enum {DW=1125,DH=2435,DP=4608,EXTENT=DP*2436,ALLOCATION=(EXTENT+16383)&~16383,ROUNDS=4};
    CFMutableDictionaryRef d=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    number(d,kIOSurfaceWidth,DW);number(d,kIOSurfaceHeight,DH);number(d,kIOSurfaceBytesPerRow,DP);
    number(d,kIOSurfaceBytesPerElement,4);number(d,kIOSurfaceAllocSize,ALLOCATION);number(d,kIOSurfacePixelFormat,0x42475241);
    IOSurfaceRef surface=IOSurfaceCreate(d);CFRelease(d);
    if(!surface || IOSurfaceLock(surface,0,NULL))return 20;
    size_t allocation=IOSurfaceGetAllocSize(surface);
    if(allocation<ALLOCATION || IOSurfaceGetBytesPerRow(surface)!=DP)return 21;
    memset(IOSurfaceGetBaseAddress(surface),0xa7,allocation);IOSurfaceUnlock(surface,0,NULL);
    uint32_t sid=IOSurfaceGetID(surface);
    ImageTexture image=(ImageTexture)OSMesaGetProcAddress("glEGLImageTargetTexture2DOES");
    GLuint texture=0,framebuffer=0,vertices=0;
    glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    image(GL_TEXTURE_2D,(void *)(uintptr_t)sid);
    glGenFramebuffers(1,&framebuffer);glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
    if(glCheckFramebufferStatus(GL_FRAMEBUFFER)!=GL_FRAMEBUFFER_COMPLETE || glGetError())return 23;
    uint32_t producer=redfin_gl_surface_producer(sid);
    if(!producer)return 22;
    struct rf_gu_target target={producer,sid};
    GLuint vs=shader(GL_VERTEX_SHADER,"attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}");
    GLuint fs=shader(GL_FRAGMENT_SHADER,
        "#extension GL_EXT_shader_framebuffer_fetch : require\n"
        "precision highp float;void main(){gl_FragColor=gl_LastFragData[0]*0.5+vec4(16.,24.,32.,0.)/255.;}");
    GLuint plain=shader(GL_FRAGMENT_SHADER,"precision highp float;uniform vec4 c;void main(){gl_FragColor=c;}");
    if(!vs || !fs || !plain)return 24;
    GLuint programs[2]={glCreateProgram(),glCreateProgram()};
    for(unsigned i=0;i<2;++i) {
        glAttachShader(programs[i],vs);glAttachShader(programs[i],i?plain:fs);
        glBindAttribLocation(programs[i],0,"p");glLinkProgram(programs[i]);GLint linked=0;
        glGetProgramiv(programs[i],GL_LINK_STATUS,&linked);if(!linked)return 25;
    }
    const GLfloat quad[]={-1,-1,1,-1,-1,1,-1,1,1,-1,1,1};
    glGenBuffers(1,&vertices);glBindBuffer(GL_ARRAY_BUFFER,vertices);
    glBufferData(GL_ARRAY_BUFFER,sizeof(quad),quad,GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,0);glEnableVertexAttribArray(0);
    glViewport(0,0,DW,DH);glDisable(GL_BLEND);glDisable(GL_DITHER);glDisable(GL_DEPTH_TEST);
    unsigned pixels_checked=0,guard_checked=0;
    GLint color=glGetUniformLocation(programs[1],"c");
    for(unsigned pass=0;pass<ROUNDS;++pass) {
        uint8_t red=(uint8_t)(64+4*pass),green=(uint8_t)(96+2*pass),blue=(uint8_t)(128+4*pass);
        uint32_t before=IOSurfaceGetSeed(surface);
        glDisable(GL_SCISSOR_TEST);glClearColor(0,0,0,1);glClear(GL_COLOR_BUFFER_BIT);
        glUseProgram(programs[1]);glUniform4f(color,red/255.0f,green/255.0f,blue/255.0f,1);
        glDrawArrays(GL_TRIANGLES,0,6);
        glEnable(GL_SCISSOR_TEST);glScissor(0,0,DW/2,DH);
        glUniform4f(color,(red+32)/255.0f,(green+16)/255.0f,(blue-24)/255.0f,1);glDrawArrays(GL_TRIANGLES,0,6);
        glDisable(GL_SCISSOR_TEST);glUseProgram(programs[0]);glDrawArrays(GL_TRIANGLES,0,6);
        glFlush();
        if(redfin_gl_publish_surfaces(&target,1))return 26;
        uint32_t after=IOSurfaceGetSeed(surface);
        if(after==before || IOSurfaceLock(surface,kIOSurfaceLockReadOnly,NULL))return 27;
        const uint8_t *data=IOSurfaceGetBaseAddress(surface);
        for(unsigned y=0;y<DH;++y)for(unsigned x=0;x<DW;++x) {
            unsigned left=x<DW/2;
            uint8_t expected[]={(uint8_t)((blue-24*left)/2+32),(uint8_t)((green+16*left)/2+24),
                (uint8_t)((red+32*left)/2+16),128};
            if(!close_color(data+y*DP+x*4,expected)) {
                const uint8_t *actual=data+y*DP+x*4;
                printf("REDFIN GLES DIRECT FAIL: pass=%u x=%u y=%u BGRA=%u/%u/%u/%u expected=%u/%u/%u/%u\n",
                    pass,x,y,actual[0],actual[1],actual[2],actual[3],expected[0],expected[1],expected[2],expected[3]);
                return 28;
            }
            ++pixels_checked;
        }
        for(size_t at=EXTENT;at<allocation;++at) {if(data[at]!=0xa7)return 29;++guard_checked;}
        IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);
        if(glGetError())return 30;
        /* Invalid producer input must not announce a modification. */
        uint32_t seed=IOSurfaceGetSeed(surface);struct rf_gu_target bad={0,sid};
        if(redfin_gl_publish_surfaces(&bad,1)==0 || IOSurfaceGetSeed(surface)!=seed)return 31;
    }
    glDeleteBuffers(1,&vertices);glDeleteFramebuffers(1,&framebuffer);glDeleteTextures(1,&texture);
    glDeleteProgram(programs[0]);glDeleteProgram(programs[1]);glDeleteShader(vs);glDeleteShader(fs);glDeleteShader(plain);CFRelease(surface);
    printf("REDFIN GLES DIRECT CHECK: boot=%016llx mode=%s width=%u height=%u pitch=%u rounds=%u pixels=%u tail-guard-bytes=%u fetch=1 seed-progress=1 CPU-lock-first=1 result=0\n",
        (unsigned long long)boot_nonce,render_mode,DW,DH,DP,ROUNDS,pixels_checked,guard_checked);
#endif
    return 0;
}
