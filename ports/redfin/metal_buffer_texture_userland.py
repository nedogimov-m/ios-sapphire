"""Actual buffer-backed 2D textures over the parent's prepared shared pages."""
from pathlib import Path
from ports.redfin.eagl_userland import replace_once


def adapt(text):
    point='\tint (*commands_begin)(struct rwa_device *, char *, size_t);'
    text=replace_once(text,point,point+'''
    int (*redfin_texture_buffer_link)(struct rwa_texture *,struct rwa_buffer *,uint64_t,uint64_t,char *,size_t);''')
    point='\t*(void **)&mesa.commands_begin = dlsym(mesa.handle, "rwa_commands_begin");'
    text=replace_once(text,point,point+'\n    *(void **)&mesa.redfin_texture_buffer_link=dlsym(mesa.handle,"rwa_redfin_texture_buffer_link");')
    point='if (mesa.redfin_buffer_from_surface == NULL ||'
    text=replace_once(text,point,'if (mesa.redfin_texture_buffer_link == NULL || mesa.redfin_buffer_from_surface == NULL ||')
    first=text.index('@interface RedwoodMetalTexture :');last=text.index('\n@end',first)
    chunk=text[first:last]
    point='\tstruct rwa_texture_shape _shape;'
    chunk=replace_once(chunk,point,point+'''
    id _redfinParentBuffer,_redfinParentDevice;
    NSUInteger _redfinParentOffset,_redfinParentPitch;''')
    chunk+='\n- (void)redfinSetParentBuffer:(id)buffer offset:(NSUInteger)offset pitch:(NSUInteger)pitch;\n'
    text=text[:first]+chunk+text[last:]
    first=text.index('@implementation RedwoodMetalTexture');last=text.index('\n@end',first)
    chunk=text[first:last]
    point='- (struct rwa_texture *)mesaTexture { return _texture; }'
    chunk=replace_once(chunk,point,'''- (void)redfinSetParentBuffer:(id)buffer offset:(NSUInteger)offset pitch:(NSUInteger)pitch
{
    _redfinParentBuffer=[buffer retain];_redfinParentDevice=[_owner retain];
    _redfinParentOffset=offset;_redfinParentPitch=pitch;
}
'''+point)
    chunk=replace_once(chunk,'- (id)buffer                       { return nil; }','- (id)buffer {return _redfinParentBuffer;}')
    chunk=replace_once(chunk,'- (NSUInteger)bufferOffset         { return 0; }','- (NSUInteger)bufferOffset {return _redfinParentOffset;}')
    chunk=replace_once(chunk,'- (NSUInteger)bufferBytesPerRow    { return 0; }','- (NSUInteger)bufferBytesPerRow {return _redfinParentPitch;}')
    chunk=replace_once(chunk,'- (BOOL)doesAliasResource:(id)resource { (void)resource; return NO; }','''- (BOOL)doesAliasResource:(id)resource
{
    if(resource==self)return YES;
    if([resource isKindOfClass:[RedwoodMetalBuffer class]])return [_redfinParentBuffer doesAliasResource:resource];
    if(![resource isKindOfClass:[RedwoodMetalTexture class]])return NO;
    RedwoodMetalTexture *other=resource;
    return (_redfinParentBuffer&&[_redfinParentBuffer doesAliasResource:other->_redfinParentBuffer])||
        (_redfinIOSurface&&other->_redfinIOSurface&&IOSurfaceGetID(_redfinIOSurface)==IOSurfaceGetID(other->_redfinIOSurface));
}''')
    for mode in ('Any','All'):
        signature='- (BOOL)doesAlias'+mode+'Resources:(const id *)resources count:(NSUInteger)count'
        start=chunk.index(signature);end=chunk.index('\n}\n',start)+3
        body=('if([self doesAliasResource:resources[i]])return YES;\n    return NO;' if mode=='Any' else
              'if(![self doesAliasResource:resources[i]])return NO;\n    return count!=0;')
        chunk=chunk[:start]+signature+'\n{\n    if(count&&!resources)return NO;\n    for(NSUInteger i=0;i<count;++i)'+body+'\n}\n'+chunk[end:]
    chunk=replace_once(chunk,'[super dealloc];','[_redfinParentBuffer release];[_redfinParentDevice release];\n\t[super dealloc];')
    text=text[:first]+chunk+text[last:]
    first=text.index('@implementation RedwoodMetalBuffer');last=text.index('\n@end',first)
    chunk=text[first:last]
    point='    if(![resource isKindOfClass:[RedwoodMetalBuffer class]])return NO;'
    chunk=replace_once(chunk,point,'    if([resource isKindOfClass:[RedwoodMetalTexture class]])resource=[resource buffer];\n'+point)
    at=chunk.index('- (id)newTextureWithDescriptor:(id)descriptor offset:')
    end=chunk.index('\n}\n',at)+3
    chunk=chunk[:at]+'''- (id)newTextureWithDescriptor:(id)descriptor offset:(NSUInteger)offset bytesPerRow:(NSUInteger)row
{return [self redfinTextureWithDescriptor:descriptor offset:offset bytesPerRow:row];}
'''+chunk[end:]
    chunk+='\n'+Path(__file__).with_name('metal-buffer-view-object.inc').read_text()
    text=text[:first]+chunk+text[last:]
    point='\tif (resource) [_redfinResources addObject:resource];'
    text=replace_once(text,point,point+'''
    if([resource isKindOfClass:[RedwoodMetalTexture class]]) {
        id parent=[resource buffer];if(parent)[_redfinResources addObject:parent];
    }''')
    return text
