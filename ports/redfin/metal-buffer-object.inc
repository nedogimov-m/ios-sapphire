/* SPDX-License-Identifier: MIT */
- (instancetype)initWithRedfinDevice:(RedwoodMetalDevice *)device surface:(IOSurfaceRef)surface
    bytes:(void *)bytes length:(NSUInteger)length options:(NSUInteger)options
    deallocator:(void (^)(void *,NSUInteger))deallocator
{
    if(!(self=[super init]))return nil;
    char why[256]={0};
    if(!surface||!bytes||!length||length>128ULL*1024*1024||
       IOSurfaceGetAllocSize(surface)<length||!mesa_available()||![device mesaDevice]) {
        [self release];return nil;
    }
    _mesa=RF_MESA(redfin_buffer_from_surface,[device mesaDevice],IOSurfaceGetID(surface),length,bytes,why,sizeof(why));
    if(!_mesa){static unsigned refused;if(__sync_fetch_and_add(&refused,1)<16)rw_print("REDFIN METAL NO COPY REFUSED: %s\n",why);[self release];return nil;}
    _owner=device;_redfinExternalDevice=[device retain];_length=length;_contents=bytes;
    _redfinBufferSurface=(IOSurfaceRef)CFRetain(surface);_redfinExternalOptions=options;
    _redfinDeallocator=[deallocator copy];return self;
}
- (void)redfinReleaseExternal
{
    /* Native BO users and the surface pins leave before the caller may free its
     * memory. The command buffer retains this object through actual completion. */
    if(_redfinBufferSurface){CFRelease(_redfinBufferSurface);_redfinBufferSurface=NULL;}
    if(_redfinDeallocator){_redfinDeallocator(_contents,_length);[_redfinDeallocator release];_redfinDeallocator=nil;}
    [_redfinExternalDevice release];_redfinExternalDevice=nil;
}
