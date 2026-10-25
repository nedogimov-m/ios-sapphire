/* SPDX-License-Identifier: MIT */
- (id)redfinTextureWithDescriptor:(MTLTextureDescriptor *)descriptor offset:(NSUInteger)offset bytesPerRow:(NSUInteger)row
{
    char why[256]={0};uint32_t fourcc=0;unsigned cpp=0;
    NSUInteger width=descriptor.width,height=descriptor.height;
    RW_AGAIN("REDFIN METAL BUFFER TEXTURE REQUEST: type=%lu format=%lu size=%lux%lu offset=%lu pitch=%lu usage=%lu storage=%lu mips=%lu\n",
        (unsigned long)descriptor.textureType,(unsigned long)descriptor.pixelFormat,(unsigned long)width,
        (unsigned long)height,(unsigned long)offset,(unsigned long)row,(unsigned long)descriptor.usage,
        (unsigned long)descriptor.storageMode,(unsigned long)descriptor.mipmapLevelCount);
    if(!descriptor||!_mesa||!_contents||descriptor.textureType!=MTLTextureType2D||
       descriptor.depth!=1||descriptor.arrayLength!=1||descriptor.mipmapLevelCount!=1||descriptor.sampleCount!=1||
       descriptor.storageMode!=MTLStorageModeShared||!width||!height||width>16384||height>16384||
       descriptor.pixelFormat>UINT32_MAX||descriptor.usage>UINT32_MAX||
       rwd_format_of_metal((unsigned)descriptor.pixelFormat,&fourcc,&cpp,why,sizeof(why)))goto refused;
    if(!row&&height==1)row=(width*cpp+63)&~(NSUInteger)63;
    if(!row||(row&3)||(offset&3)||row>UINT32_MAX||offset>_length||
       width>row/cpp||height>(_length-offset)/row||((uintptr_t)_contents&((NSUInteger)getpagesize()-1)))goto refused;
    NSDictionary *properties=@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),
        (id)kIOSurfaceBytesPerElement:@(cpp),(id)kIOSurfaceBytesPerRow:@(row),
        (id)kIOSurfaceAllocSize:@(_length),(id)kIOSurfacePixelFormat:@(fourcc),
        @"IOSurfaceOffset":@(offset),@"IOSurfaceAddress":@((uint64_t)(uintptr_t)_contents),@"IOSurfaceIsGlobal":@YES};
    IOSurfaceRef surface=IOSurfaceCreate((CFDictionaryRef)properties);
    if(!surface)goto refused;
    struct rwa_texture_shape shape={.pixel_format=(unsigned)descriptor.pixelFormat,.type=2,
        .width=(unsigned)width,.height=(unsigned)height,.depth=1,.array_length=1,.mip_levels=1,.sample_count=1,
        .usage=(unsigned)descriptor.usage};
    struct rwd_surface took={0};
    struct rwa_texture *native=rwd_texture_for_surface([_owner mesaDevice],surface,0,
        (const struct rwd_texture_shape *)&shape,&took,why,sizeof(why));
    if(native&&RF_MESA(redfin_texture_buffer_link,native,_mesa,offset,row,why,sizeof(why))) {
        RF_MESA(texture_destroy,native);native=NULL;
    }
    if(!native){CFRelease(surface);goto refused;}
    RedwoodMetalTexture *texture=[[RedwoodMetalTexture alloc] initWithRedwoodDevice:_owner texture:native shape:&shape];
    if(!texture){RF_MESA(texture_destroy,native);CFRelease(surface);return nil;}
    [texture redfinSetIOSurface:surface plane:0];
    [texture redfinSetParentBuffer:self offset:offset pitch:row];CFRelease(surface);
    rw_print("REDFIN METAL BUFFER TEXTURE: original-parent-pages=1 native-offset=%u pitch=%u CPU-pixel-copy=0\n",took.offset,took.rowBytes);
    return texture;
refused:
    rw_print("REDFIN METAL BUFFER TEXTURE REFUSED: %s\n",why[0]?why:"unsupported descriptor or logical parent range");return nil;
}
