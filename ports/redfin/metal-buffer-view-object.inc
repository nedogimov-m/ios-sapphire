/* SPDX-License-Identifier: MIT */
- (id)redfinTextureWithDescriptor:(MTLTextureDescriptor *)descriptor offset:(NSUInteger)offset bytesPerRow:(NSUInteger)row
{
    char why[256]={0};unsigned cpp=0;
    NSUInteger width=descriptor.width,height=descriptor.height;
    RW_AGAIN("REDFIN METAL BUFFER TEXTURE REQUEST: type=%lu format=%lu size=%lux%lu offset=%lu pitch=%lu usage=%lu storage=%lu mips=%lu\n",
        (unsigned long)descriptor.textureType,(unsigned long)descriptor.pixelFormat,(unsigned long)width,
        (unsigned long)height,(unsigned long)offset,(unsigned long)row,(unsigned long)descriptor.usage,
        (unsigned long)descriptor.storageMode,(unsigned long)descriptor.mipmapLevelCount);
    if(!descriptor||!_mesa||!_contents||descriptor.textureType!=MTLTextureType2D||
       descriptor.depth!=1||descriptor.arrayLength!=1||descriptor.mipmapLevelCount!=1||descriptor.sampleCount!=1||
       descriptor.storageMode!=MTLStorageModeShared||!width||!height||width>16384||height>16384||
       descriptor.pixelFormat>UINT32_MAX||descriptor.usage>UINT32_MAX||
       rwd_format_of_metal((unsigned)descriptor.pixelFormat,NULL,&cpp,why,sizeof(why)))goto refused;
    if(!row&&height==1)row=(width*cpp+63)&~(NSUInteger)63;
    if(!row||(row&3)||(offset&3)||row>UINT32_MAX||offset>_length||
       width>row/cpp||height>(_length-offset)/row)goto refused;
    struct rwa_texture_shape shape={.pixel_format=(unsigned)descriptor.pixelFormat,.type=2,
        .width=(unsigned)width,.height=(unsigned)height,.depth=1,.array_length=1,.mip_levels=1,.sample_count=1,
        .usage=(unsigned)descriptor.usage};
    struct rwa_texture *native=RF_MESA(redfin_texture_from_buffer,[_owner mesaDevice],_mesa,&shape,offset,row,why,sizeof(why));
    if(!native)goto refused;
    RedwoodMetalTexture *texture=[[RedwoodMetalTexture alloc] initWithRedwoodDevice:_owner texture:native shape:&shape];
    if(!texture){RF_MESA(texture_destroy,native);return nil;}
    [texture redfinSetParentBuffer:self offset:offset pitch:row];
    rw_print("REDFIN METAL BUFFER TEXTURE: original-parent-BO=1 offset=%lu pitch=%lu CPU-pixel-copy=0\n",(unsigned long)offset,(unsigned long)row);
    return texture;
refused:
    rw_print("REDFIN METAL BUFFER TEXTURE REFUSED: %s\n",why[0]?why:"unsupported descriptor or logical parent range");return nil;
}
