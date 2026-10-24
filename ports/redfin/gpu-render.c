/* SPDX-License-Identifier: MIT */
/* Actual iOS userspace rendering through Mesa -> IOKit -> native A620.
 * Two shader draws into a real IOSurface, checked through GL and its CPU view.
 * A software renderer, unchanged target, wrong colors or GL error is failure.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include "iosurface-abi.h"
#include <OpenGLES/ES2/gl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/sysctl.h>

typedef void *OSMesaContext;
extern OSMesaContext OSMesaCreateContextAttribs(const int *,OSMesaContext);
extern unsigned char OSMesaMakeCurrent(OSMesaContext,void *,unsigned,int,int);
extern void OSMesaDestroyContext(OSMesaContext);
extern void (*OSMesaGetProcAddress(const char *))(void);
enum {W=256,H=256,ROW=W*4};
static uint64_t boot_nonce;
static void number(CFMutableDictionaryRef d,CFStringRef key,int32_t value)
{
    CFNumberRef n=CFNumberCreate(kCFAllocatorDefault,kCFNumberSInt32Type,&value);
    CFDictionarySetValue(d,key,n);CFRelease(n);
}
static GLuint shader(GLenum kind,const char *source)
{
    GLuint s=glCreateShader(kind);GLint compiled=0;
    glShaderSource(s,1,&source,NULL);glCompileShader(s);glGetShaderiv(s,GL_COMPILE_STATUS,&compiled);
    if(!compiled){char log[1024]={0};glGetShaderInfoLog(s,sizeof(log)-1,NULL,log);printf("REDFIN GPU RENDER SHADER: %s\n",log);return 0;}
    return s;
}
static int close_color(const unsigned char *pixel,const unsigned char *expected)
{
    for(unsigned i=0;i<4;i++)if(abs((int)pixel[i]-expected[i])>1)return 0;
    return 1;
}
static int render(void)
{
    io_service_t service=0;
    for(unsigned i=0;i<600 && !service;i++) {
        service=IOServiceGetMatchingService(0,IOServiceMatching("RedwoodGPU"));
        if(!service)usleep(100000);
    }
    if(!service){puts("REDFIN GPU RENDER FAIL: native service absent after60s");return 2;}
    io_connect_t connection=0;
    kern_return_t kr=IOServiceOpen(service,mach_task_self(),0,&connection);IOObjectRelease(service);
    if(kr){printf("REDFIN GPU RENDER FAIL: open=%#x\n",kr);return 3;}
    struct {uint32_t pipe,param;uint64_t value;uint32_t len,pad;} param={0x10,3,0,0,0};
    size_t bytes=sizeof(param);
    kr=IOConnectCallStructMethod(connection,0x40,&param,sizeof(param),&param,&bytes);
    IOServiceClose(connection);
    if(kr || bytes!=sizeof(param) || param.value!=0x06020001) {
        printf("REDFIN GPU RENDER FAIL: actual A620 parameter=%#llx result=%#x\n",(unsigned long long)param.value,kr);return 4;
    }
    const int attributes[]={0x22,GL_RGBA,0x30,0,0x31,0,0x33,0x38,0x36,2,0x37,0,0};
    OSMesaContext context=OSMesaCreateContextAttribs(attributes,NULL);
    static unsigned char window[16*16*4];
    if(!context || !OSMesaMakeCurrent(context,window,GL_UNSIGNED_BYTE,16,16)) {
        puts("REDFIN GPU RENDER FAIL: Mesa ES context");return 5;
    }
    const char *renderer=(const char *)glGetString(GL_RENDERER);
    printf("REDFIN GPU RENDER DRIVER: %s; version=%s\n",renderer?renderer:"NULL",glGetString(GL_VERSION));
    if(!renderer || !strstr(renderer,"620") || strstr(renderer,"softpipe") || strstr(renderer,"llvmpipe")) {
        puts("REDFIN GPU RENDER FAIL: A620 hardware renderer required");return 6;
    }
    CFMutableDictionaryRef d=CFDictionaryCreateMutable(kCFAllocatorDefault,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    number(d,kIOSurfaceWidth,W);number(d,kIOSurfaceHeight,H);number(d,kIOSurfaceBytesPerRow,ROW);
    number(d,kIOSurfaceBytesPerElement,4);number(d,kIOSurfaceAllocSize,ROW*H);
    number(d,kIOSurfacePixelFormat,0x42475241); /* BGRA, the system framebuffer's format. */
    IOSurfaceRef surface=IOSurfaceCreate(d);CFRelease(d);
    if(!surface){puts("REDFIN GPU RENDER FAIL: IOSurfaceCreate");return 7;}
    if(IOSurfaceLock(surface,0,NULL)){puts("REDFIN GPU RENDER FAIL: initial lock");return 8;}
    memset(IOSurfaceGetBaseAddress(surface),0,ROW*H);IOSurfaceUnlock(surface,0,NULL);
    typedef void (*ImageTexture)(GLenum,void *);
    ImageTexture image=(ImageTexture)OSMesaGetProcAddress("glEGLImageTargetTexture2DOES");
    if(!image){puts("REDFIN GPU RENDER FAIL: IOSurface texture import absent");return 9;}
    GLuint texture=0,framebuffer=0;
    glGenTextures(1,&texture);glBindTexture(GL_TEXTURE_2D,texture);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_NEAREST);
    image(GL_TEXTURE_2D,(void *)(uintptr_t)IOSurfaceGetID(surface));
    glGenFramebuffers(1,&framebuffer);glBindFramebuffer(GL_FRAMEBUFFER,framebuffer);
    glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_2D,texture,0);
    GLenum status=glCheckFramebufferStatus(GL_FRAMEBUFFER),error=glGetError();
    if(status!=GL_FRAMEBUFFER_COMPLETE || error) {
        printf("REDFIN GPU RENDER FAIL: imported FBO=%#x error=%#x\n",status,error);return 10;
    }
    GLuint vs=shader(GL_VERTEX_SHADER,"attribute vec2 p;void main(){gl_Position=vec4(p,0.0,1.0);}");
    GLuint fs=shader(GL_FRAGMENT_SHADER,"precision mediump float;uniform vec4 color;void main(){gl_FragColor=color;}");
    if(!vs || !fs)return 11;
    GLuint program=glCreateProgram();glAttachShader(program,vs);glAttachShader(program,fs);
    glBindAttribLocation(program,0,"p");glLinkProgram(program);GLint linked=0;
    glGetProgramiv(program,GL_LINK_STATUS,&linked);
    if(!linked){puts("REDFIN GPU RENDER FAIL: program link");return 12;}
    glUseProgram(program);GLint color=glGetUniformLocation(program,"color");
    const GLfloat vertices[]={-0.8f,-0.8f,0.8f,-0.8f,0.0f,0.8f};
    GLuint vertexBuffer=0;glGenBuffers(1,&vertexBuffer);glBindBuffer(GL_ARRAY_BUFFER,vertexBuffer);
    glBufferData(GL_ARRAY_BUFFER,sizeof(vertices),vertices,GL_STATIC_DRAW);
    glVertexAttribPointer(0,2,GL_FLOAT,GL_FALSE,0,0);glEnableVertexAttribArray(0);
    glViewport(0,0,W,H);glDisable(GL_DITHER);glDisable(GL_BLEND);glDisable(GL_DEPTH_TEST);
    unsigned char previous[4]={0};
    for(unsigned pass=0;pass<2;pass++) {
        const unsigned char expected[2][4]={{192+(boot_nonce&63),32,16,255},
            {16,128+((boot_nonce>>8)&63),64,255}},clear[4]={10,20,41,255};
        glClearColor(10/255.0f,20/255.0f,41/255.0f,1);glClear(GL_COLOR_BUFFER_BIT);
        glUniform4f(color,expected[pass][0]/255.0f,expected[pass][1]/255.0f,expected[pass][2]/255.0f,1);
        glDrawArrays(GL_TRIANGLES,0,3);glFinish();
        unsigned char center[4]={0},corner[4]={0};
        glReadPixels(W/2,H/2,1,1,GL_RGBA,GL_UNSIGNED_BYTE,center);
        glReadPixels(4,4,1,1,GL_RGBA,GL_UNSIGNED_BYTE,corner);error=glGetError();
        if(error || !close_color(center,expected[pass]) || !close_color(corner,clear) ||
            (pass && !memcmp(previous,center,4))) {
            printf("REDFIN GPU RENDER FAIL: pass=%u GL=%#x center=%u/%u/%u/%u corner=%u/%u/%u/%u\n",
                pass,error,center[0],center[1],center[2],center[3],corner[0],corner[1],corner[2],corner[3]);return 13;
        }
        if(IOSurfaceLock(surface,kIOSurfaceLockReadOnly,NULL)){puts("REDFIN GPU RENDER FAIL: CPU lock");return 14;}
        const unsigned char *pixels=IOSurfaceGetBaseAddress(surface);
        unsigned row=(unsigned)IOSurfaceGetBytesPerRow(surface);
        const unsigned char *p=pixels+(H/2)*row+(W/2)*4;
        unsigned char cpu[4]={p[2],p[1],p[0],p[3]};uint32_t checksum=2166136261u;
        for(unsigned y=0;y<H;y++)for(unsigned x=0;x<ROW;x++)checksum=(checksum^pixels[y*row+x])*16777619u;
        IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);
        if(!close_color(cpu,expected[pass])) {
            printf("REDFIN GPU RENDER FAIL: IOSurface readback pass=%u RGBA=%u/%u/%u/%u\n",pass,cpu[0],cpu[1],cpu[2],cpu[3]);return 15;
        }
        memcpy(previous,center,4);
        printf("REDFIN GPU RENDER PASS: pass=%u IOSurface=%u %ux%u center=%u/%u/%u/%u checksum=%08x\n",
            pass,IOSurfaceGetID(surface),W,H,cpu[0],cpu[1],cpu[2],cpu[3],checksum);
    }
    glDeleteBuffers(1,&vertexBuffer);glDeleteProgram(program);glDeleteShader(vs);glDeleteShader(fs);
    glDeleteFramebuffers(1,&framebuffer);glDeleteTextures(1,&texture);CFRelease(surface);
    OSMesaDestroyContext(context);return 0;
}
int main(void)
{
    setvbuf(stdout,NULL,_IONBF,0);setvbuf(stderr,NULL,_IONBF,0);
    char arguments[608]={0};size_t argument_bytes=sizeof(arguments);bool selected=false;
    if(sysctlbyname("kern.bootargs",arguments,&argument_bytes,NULL,0) ||
        !argument_bytes || argument_bytes>sizeof(arguments) || arguments[argument_bytes-1]) {
        puts("REDFIN GPU RENDER FAIL: boot identity unavailable");return 16;
    }
    char *save=NULL;
    for(char *token=strtok_r(arguments," ",&save);token;token=strtok_r(NULL," ",&save)) {
        if(!strcmp(token,"redfingui=3"))selected=true;
        if(strlen(token)==31 && !strncmp(token,"redfinbootid=0x",15))boot_nonce=strtoull(token+15,NULL,16);
    }
    if(!selected){puts("REDFIN GPU RENDER: skipped; GUI3 was not selected");return 0;}
    if(!boot_nonce){puts("REDFIN GPU RENDER FAIL: missing boot nonce");return 17;}
    printf("REDFIN GPU RENDER BOOT: %016llx\n",(unsigned long long)boot_nonce);
    puts("REDFIN GPU RENDER: iOS Mesa/A620 shader + IOSurface two-draw test starts");
    int result=render();printf("REDFIN GPU RENDER RESULT: result=%d hardware=%u draws=%u\n",result,!result,result?0:2);
    return result;
}
