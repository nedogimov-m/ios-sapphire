"""Share the original caller pages through Redfin's prepared IOSurface import."""
from pathlib import Path
from ports.redfin.eagl_userland import replace_once


def adapt(text):
    text = '#import <Metal/Metal.h>\n#include "redfin_metal_buffer_import.h"\n#include "iosurface-abi.h"\n#include <unistd.h>\n'+text
    point = '\tint (*commands_begin)(struct rwa_device *, char *, size_t);'
    text = replace_once(text, point, point+'''
    struct rwa_buffer *(*redfin_buffer_from_surface)(struct rwa_device *,unsigned,size_t,void *,char *,size_t);''')
    point = '\t*(void **)&mesa.commands_begin = dlsym(mesa.handle, "rwa_commands_begin");'
    text = replace_once(text, point, point+'\n    *(void **)&mesa.redfin_buffer_from_surface=dlsym(mesa.handle,"rwa_redfin_buffer_from_surface");')
    point = 'if (mesa.redfin_blit == NULL ||'
    text = replace_once(text, point, 'if (mesa.redfin_buffer_from_surface == NULL || mesa.redfin_blit == NULL ||')
    first = text.index('@interface RedwoodMetalBuffer :')
    last = text.index('\n@end',first)
    chunk = text[first:last]
    chunk = replace_once(chunk, '\tNSUInteger _length;', '''\tNSUInteger _length;
    IOSurfaceRef _redfinBufferSurface;
    id _redfinExternalDevice;
    void (^_redfinDeallocator)(void *,NSUInteger);
    NSUInteger _redfinExternalOptions;''')
    chunk+='''
- (instancetype)initWithRedfinDevice:(RedwoodMetalDevice *)device surface:(IOSurfaceRef)surface
    bytes:(void *)bytes length:(NSUInteger)length options:(NSUInteger)options
    deallocator:(void (^)(void *,NSUInteger))deallocator;
- (void)redfinReleaseExternal;
'''
    text = text[:first]+chunk+text[last:]
    first = text.index('- (id)newBufferWithIOSurface:(void *)surface {')
    last = text.index('\n- (id)newIndirectCommandBufferWithDescriptor:',first)
    text = text[:first]+'''
- (id)newBufferWithIOSurface:(void *)opaque
{
    IOSurfaceRef surface=(IOSurfaceRef)opaque;
    if(!surface)return nil;
    return [[RedwoodMetalBuffer alloc] initWithRedfinDevice:self surface:surface
        bytes:IOSurfaceGetBaseAddress(surface) length:IOSurfaceGetAllocSize(surface)
        options:MTLResourceStorageModeShared deallocator:nil];
}
- (id)newBufferWithBytesNoCopy:(void *)bytes length:(NSUInteger)length options:(NSUInteger)options
    deallocator:(void (^)(void *,NSUInteger))deallocator
{
    NSUInteger page=(NSUInteger)getpagesize();
    BOOL valid=bytes&&length&&length<=128ULL*1024*1024&&page&&!(page&(page-1))&&
        !((uintptr_t)bytes&(page-1))&&!(length&(page-1))&&(uintptr_t)bytes<=UINTPTR_MAX-length&&
        !(options&MTLResourceStorageModeMask)&&(options&MTLResourceCPUCacheModeMask)<=MTLResourceCPUCacheModeWriteCombined&&
        !(options&~(MTLResourceCPUCacheModeMask|MTLResourceHazardTrackingModeMask));
    RW_AGAIN("REDFIN METAL NO COPY REQUEST: bytes=%lu page-offset=%lu length-page-offset=%lu options=%lu valid=%u\\n",
        (unsigned long)length,(unsigned long)((uintptr_t)bytes&(page-1)),
        (unsigned long)(length&(page-1)),(unsigned long)options,valid);
    if(!valid)return nil;
    /* IOSurfaceAddress holds/prepares the caller's exact pages in SweetSurface;
     * the tiny image geometry is unused by this raw-buffer import. */
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@1,(id)kIOSurfaceHeight:@1,
        (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@64,
        (id)kIOSurfaceAllocSize:@(length),(id)kIOSurfacePixelFormat:@0x42475241,
        @"IOSurfaceAddress":@((uint64_t)(uintptr_t)bytes),@"IOSurfaceIsGlobal":@YES};
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    if(!surface){rw_print("REDFIN METAL NO COPY REFUSED: original pages could not be prepared\\n");return nil;}
    RedwoodMetalBuffer *buffer=[[RedwoodMetalBuffer alloc] initWithRedfinDevice:self surface:surface
        bytes:bytes length:length options:options deallocator:deallocator];
    CFRelease(surface);return buffer;
}
'''+text[last:]
    first = text.index('@implementation RedwoodMetalBuffer')
    last = text.index('\n@end',first)
    chunk = text[first:last]
    point = '- (struct rwa_buffer *)mesaBuffer'
    methods = Path(__file__).with_name('metal-buffer-object.inc').read_text()
    chunk = replace_once(chunk, point, methods+'\n'+point)
    chunk = replace_once(chunk, '\t\tRF_MESA(buffer_destroy,_mesa);',
        '\t\tRF_MESA(buffer_destroy,_mesa);\n\t\t[self redfinReleaseExternal];')
    chunk = replace_once(chunk, '- (NSUInteger)cpuCacheMode       { return 1; }',
        '- (NSUInteger)cpuCacheMode       { return _redfinBufferSurface?(_redfinExternalOptions&MTLResourceCPUCacheModeMask):1; }')
    chunk = replace_once(chunk, '- (NSUInteger)resourceOptions    { return 0; }',
        '- (NSUInteger)resourceOptions    { return _redfinBufferSurface?_redfinExternalOptions:0; }')
    chunk = replace_once(chunk, '- (NSUInteger)hazardTrackingMode { return 0; }',
        '- (NSUInteger)hazardTrackingMode { return _redfinBufferSurface?(_redfinExternalOptions&MTLResourceHazardTrackingModeMask)>>MTLResourceHazardTrackingModeShift:0; }')
    point = '- (BOOL)doesAliasResource:(id)resource { (void)resource; return NO; }'
    chunk = replace_once(chunk, point, '''- (BOOL)doesAliasResource:(id)resource
{
    if(![resource isKindOfClass:[RedwoodMetalBuffer class]])return NO;
    RedwoodMetalBuffer *other=resource;
    uintptr_t a=(uintptr_t)_contents,b=(uintptr_t)other->_contents;
    return resource==self||(_redfinBufferSurface&&other->_redfinBufferSurface&&
        IOSurfaceGetID(_redfinBufferSurface)==IOSurfaceGetID(other->_redfinBufferSurface))||
        (a&&b&&a<=UINTPTR_MAX-_length&&b<=UINTPTR_MAX-other->_length&&a<b+other->_length&&b<a+_length);
}''')
    for mode in ('Any','All'):
        point='- (BOOL)doesAlias'+mode+'Resources:(const id *)resources count:(NSUInteger)count\n{\n\t(void)resources; (void)count;\n\treturn NO;\n}'
        body=('if([self doesAliasResource:resources[i]])return YES;\n    return NO;' if mode=='Any' else
              'if(![self doesAliasResource:resources[i]])return NO;\n    return count!=0;')
        chunk=replace_once(chunk,point,'- (BOOL)doesAlias'+mode+'Resources:(const id *)resources count:(NSUInteger)count\n{\n'
            '    if(count&&!resources)return NO;\n    for(NSUInteger i=0;i<count;++i)'+body+'\n}')
    point = '\t(void)descriptor; (void)offset; (void)bytesPerRow;'
    chunk = replace_once(chunk, point, point+'\n    RW_ONCE("REDFIN METAL UNSERVED: buffer-backed texture requested\\n");')
    return text[:first]+chunk+text[last:]
