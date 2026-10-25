/* SPDX-License-Identifier: MIT */
@implementation RedfinMetalBlitEncoder {
    RedwoodMetalCommandBuffer *_redfinCommand;
    id _redfinDevice;
    BOOL _redfinEnded;
}
+ (void)load
{
    Protocol *protocol=objc_getProtocol("MTLBlitCommandEncoder");
    if(protocol&&!class_conformsToProtocol(self,protocol))class_addProtocol(self,protocol);
}
- (instancetype)initWithRedfinCommandBuffer:(RedwoodMetalCommandBuffer *)command
{
    if((self=[super initWithCommandBuffer:command])) {
        _redfinCommand=command;_redfinDevice=[[command device] retain];
    }
    return self;
}
- (void)dealloc {[_redfinDevice release];[super dealloc];}
- (id)device {return _redfinDevice;}
- (void)redfinRecord:(struct redfin_metal_blit)request source:(id)source destination:(id)destination
{
    if(_redfinEnded||!_redfinCommand)return;
    BOOL source_buffer=request.operation==RF_BLIT_BUFFER||request.operation==RF_BLIT_UPLOAD;
    BOOL destination_buffer=request.operation==RF_BLIT_BUFFER||request.operation==RF_BLIT_FILL||request.operation==RF_BLIT_DOWNLOAD;
    if(request.operation==RF_BLIT_SYNC&&(!source||
       (![source isKindOfClass:[RedwoodMetalBuffer class]]&&![source isKindOfClass:[RedwoodMetalTexture class]])))
        request.operation=RF_BLIT_INVALID;
    if(request.operation!=RF_BLIT_SYNC&&request.operation!=RF_BLIT_INVALID&&
       ((source&&![source isKindOfClass:source_buffer?[RedwoodMetalBuffer class]:[RedwoodMetalTexture class]])||
        (destination&&![destination isKindOfClass:destination_buffer?[RedwoodMetalBuffer class]:[RedwoodMetalTexture class]])))
        request.operation=RF_BLIT_INVALID;
    RedwoodMetalWork *work=[RedwoodMetalWork new];work->redfinBlit=request;
    work->redfinBlitSource=source;work->redfinBlitDestination=destination;
    [_redfinCommand redfinRetainResource:source];[_redfinCommand redfinRetainResource:destination];
    [_redfinCommand recordWork:work];[work release];
}
- (void)redfinUnsupported:(const char *)selector
{
    rw_print("REDFIN METAL BLIT UNSERVED: %s\n",selector);
    [self redfinRecord:(struct redfin_metal_blit){.operation=RF_BLIT_INVALID} source:nil destination:nil];
}
- (void)copyFromBuffer:(id)source sourceOffset:(NSUInteger)sourceOffset toBuffer:(id)destination
    destinationOffset:(NSUInteger)destinationOffset size:(NSUInteger)size
{
    struct redfin_metal_blit request={.operation=RF_BLIT_BUFFER,.source_offset=sourceOffset,.destination_offset=destinationOffset,.size={size,1,1}};
    [self redfinRecord:request source:source destination:destination];
}
- (void)fillBuffer:(id)buffer range:(NSRange)range value:(uint8_t)value
{
    struct redfin_metal_blit request={.operation=RF_BLIT_FILL,.fill_value=value,.destination_offset=range.location,.size={range.length,1,1}};
    [self redfinRecord:request source:nil destination:buffer];
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)sourceSlice sourceLevel:(NSUInteger)sourceLevel
    sourceOrigin:(MTLOrigin)sourceOrigin sourceSize:(MTLSize)sourceSize toTexture:(id)destination
    destinationSlice:(NSUInteger)destinationSlice destinationLevel:(NSUInteger)destinationLevel destinationOrigin:(MTLOrigin)destinationOrigin
{
    struct redfin_metal_blit request={.operation=RF_BLIT_TEXTURE,.source_level=sourceLevel,.source_slice=sourceSlice,
        .destination_level=destinationLevel,.destination_slice=destinationSlice,
        .source_origin={sourceOrigin.x,sourceOrigin.y,sourceOrigin.z},.destination_origin={destinationOrigin.x,destinationOrigin.y,destinationOrigin.z},
        .size={sourceSize.width,sourceSize.height,sourceSize.depth}};
    [self redfinRecord:request source:source destination:destination];
}
- (void)copyFromTexture:(id)source toTexture:(id)destination
{
    if(![source isKindOfClass:[RedwoodMetalTexture class]]||![destination isKindOfClass:[RedwoodMetalTexture class]]||
       [source textureType]!=[destination textureType]||[source width]!=[destination width]||
       [source height]!=[destination height]||[source depth]!=[destination depth]||
       [source arrayLength]!=[destination arrayLength]||[source mipmapLevelCount]!=[destination mipmapLevelCount]) {
        [self redfinUnsupported:"copy texture object type"];return;
    }
    NSUInteger slices=[source arrayLength];
    if([source textureType]==MTLTextureTypeCube||[source textureType]==MTLTextureTypeCubeArray)slices*=6;
    [self copyFromTexture:source sourceSlice:0 sourceLevel:0 toTexture:destination destinationSlice:0
        destinationLevel:0 sliceCount:slices levelCount:[source mipmapLevelCount]];
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)sourceSlice sourceLevel:(NSUInteger)sourceLevel
    toTexture:(id)destination destinationSlice:(NSUInteger)destinationSlice destinationLevel:(NSUInteger)destinationLevel
    sliceCount:(NSUInteger)slices levelCount:(NSUInteger)levels
{
    if(![source isKindOfClass:[RedwoodMetalTexture class]]||![destination isKindOfClass:[RedwoodMetalTexture class]]) {
        [self redfinUnsupported:"copy texture object type"];return;
    }
    NSUInteger sourceSlices=[source arrayLength],destinationSlices=[destination arrayLength];
    if([source textureType]==MTLTextureTypeCube||[source textureType]==MTLTextureTypeCubeArray)sourceSlices*=6;
    if([destination textureType]==MTLTextureTypeCube||[destination textureType]==MTLTextureTypeCubeArray)destinationSlices*=6;
    if(sourceSlice>sourceSlices||slices>sourceSlices-sourceSlice||destinationSlice>destinationSlices||
       slices>destinationSlices-destinationSlice||sourceLevel>[source mipmapLevelCount]||levels>[source mipmapLevelCount]-sourceLevel||
       destinationLevel>[destination mipmapLevelCount]||levels>[destination mipmapLevelCount]-destinationLevel) {
        [self redfinUnsupported:"copy texture slice/level range"];return;
    }
    for(NSUInteger slice=0;slice<slices;++slice)for(NSUInteger level=0;level<levels;++level) {
        MTLSize size=MTLSizeMake(MAX((NSUInteger)1,[source width]>>(sourceLevel+level)),
            MAX((NSUInteger)1,[source height]>>(sourceLevel+level)),
            [source textureType]==MTLTextureType3D?MAX((NSUInteger)1,[source depth]>>(sourceLevel+level)):1);
        [self copyFromTexture:source sourceSlice:sourceSlice+slice sourceLevel:sourceLevel+level sourceOrigin:MTLOriginMake(0,0,0)
            sourceSize:size toTexture:destination destinationSlice:destinationSlice+slice destinationLevel:destinationLevel+level
            destinationOrigin:MTLOriginMake(0,0,0)];
    }
}
- (void)copyFromBuffer:(id)source sourceOffset:(NSUInteger)offset sourceBytesPerRow:(NSUInteger)row
    sourceBytesPerImage:(NSUInteger)image sourceSize:(MTLSize)size toTexture:(id)destination
    destinationSlice:(NSUInteger)slice destinationLevel:(NSUInteger)level destinationOrigin:(MTLOrigin)origin
{
    [self copyFromBuffer:source sourceOffset:offset sourceBytesPerRow:row sourceBytesPerImage:image sourceSize:size
        toTexture:destination destinationSlice:slice destinationLevel:level destinationOrigin:origin options:0];
}
- (void)copyFromBuffer:(id)source sourceOffset:(NSUInteger)offset sourceBytesPerRow:(NSUInteger)row
    sourceBytesPerImage:(NSUInteger)image sourceSize:(MTLSize)size toTexture:(id)destination
    destinationSlice:(NSUInteger)slice destinationLevel:(NSUInteger)level destinationOrigin:(MTLOrigin)origin options:(NSUInteger)options
{
    struct redfin_metal_blit request={.operation=RF_BLIT_UPLOAD,.options=options,.source_offset=offset,.row_bytes=row,.image_bytes=image,
        .destination_slice=slice,.destination_level=level,.destination_origin={origin.x,origin.y,origin.z},.size={size.width,size.height,size.depth}};
    [self redfinRecord:request source:source destination:destination];
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)slice sourceLevel:(NSUInteger)level sourceOrigin:(MTLOrigin)origin
    sourceSize:(MTLSize)size toBuffer:(id)destination destinationOffset:(NSUInteger)offset
    destinationBytesPerRow:(NSUInteger)row destinationBytesPerImage:(NSUInteger)image
{
    [self copyFromTexture:source sourceSlice:slice sourceLevel:level sourceOrigin:origin sourceSize:size toBuffer:destination
        destinationOffset:offset destinationBytesPerRow:row destinationBytesPerImage:image options:0];
}
- (void)copyFromTexture:(id)source sourceSlice:(NSUInteger)slice sourceLevel:(NSUInteger)level sourceOrigin:(MTLOrigin)origin
    sourceSize:(MTLSize)size toBuffer:(id)destination destinationOffset:(NSUInteger)offset
    destinationBytesPerRow:(NSUInteger)row destinationBytesPerImage:(NSUInteger)image options:(NSUInteger)options
{
    struct redfin_metal_blit request={.operation=RF_BLIT_DOWNLOAD,.options=options,.destination_offset=offset,.row_bytes=row,.image_bytes=image,
        .source_slice=slice,.source_level=level,.source_origin={origin.x,origin.y,origin.z},.size={size.width,size.height,size.depth}};
    [self redfinRecord:request source:source destination:destination];
}
- (void)generateMipmapsForTexture:(id)texture
{[self redfinRecord:(struct redfin_metal_blit){.operation=RF_BLIT_MIPMAP} source:nil destination:texture];}
- (void)synchronizeResource:(id)resource
{[self redfinRecord:(struct redfin_metal_blit){.operation=RF_BLIT_SYNC} source:resource destination:nil];}
- (void)synchronizeTexture:(id)texture slice:(NSUInteger)slice level:(NSUInteger)level
{[self redfinRecord:(struct redfin_metal_blit){.operation=RF_BLIT_SYNC,.source_slice=slice,.source_level=level} source:texture destination:nil];}
- (void)optimizeContentsForGPUAccess:(id)texture {[self synchronizeResource:texture];}
- (void)optimizeContentsForCPUAccess:(id)texture {[self synchronizeResource:texture];}
- (void)optimizeContentsForGPUAccess:(id)texture slice:(NSUInteger)slice level:(NSUInteger)level {[self synchronizeTexture:texture slice:slice level:level];}
- (void)optimizeContentsForCPUAccess:(id)texture slice:(NSUInteger)slice level:(NSUInteger)level {[self synchronizeTexture:texture slice:slice level:level];}
- (void)updateFence:(id)fence {(void)fence;[self redfinUnsupported:"updateFence"];}
- (void)waitForFence:(id)fence {(void)fence;[self redfinUnsupported:"waitForFence"];}
- (void)resetCommandsInBuffer:(id)buffer withRange:(NSRange)range {(void)buffer;(void)range;[self redfinUnsupported:"reset indirect commands"];}
- (void)optimizeIndirectCommandBuffer:(id)buffer withRange:(NSRange)range {(void)buffer;(void)range;[self redfinUnsupported:"optimize indirect commands"];}
- (void)copyIndirectCommandBuffer:(id)source sourceRange:(NSRange)range destination:(id)destination destinationIndex:(NSUInteger)index
{(void)source;(void)range;(void)destination;(void)index;[self redfinUnsupported:"copy indirect commands"];}
- (void)resetTextureAccessCounters:(id)texture region:(MTLRegion)region mipLevel:(NSUInteger)level slice:(NSUInteger)slice
{(void)texture;(void)region;(void)level;(void)slice;[self redfinUnsupported:"reset sparse counters"];}
- (void)getTextureAccessCounters:(id)texture region:(MTLRegion)region mipLevel:(NSUInteger)level slice:(NSUInteger)slice
    resetCounters:(BOOL)reset countersBuffer:(id)buffer countersBufferOffset:(NSUInteger)offset
{(void)texture;(void)region;(void)level;(void)slice;(void)reset;(void)buffer;(void)offset;[self redfinUnsupported:"get sparse counters"];}
- (void)sampleCountersInBuffer:(id)buffer atSampleIndex:(NSUInteger)index withBarrier:(BOOL)barrier
{(void)buffer;(void)index;(void)barrier;[self redfinUnsupported:"sample GPU counters"];}
- (void)endEncoding
{if(!_redfinEnded){[super endEncoding];_redfinEnded=YES;_redfinCommand=nil;}}
@end
