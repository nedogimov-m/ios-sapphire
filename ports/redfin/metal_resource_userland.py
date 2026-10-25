"""Native IOSurface ownership and explicit evidence of unserved Metal calls."""
from ports.redfin.eagl_userland import replace_once


def adapt(text):
    start=text.index('@interface RedwoodMetalTexture :')
    end=text.index('\n@end',start)
    chunk=text[start:end]
    chunk=replace_once(chunk,'\tstruct rwa_texture_shape _shape;',
        '\tstruct rwa_texture_shape _shape;\n\tvoid *_redfinIOSurface;\n\tNSUInteger _redfinIOSurfacePlane;')
    chunk+='\n- (void)redfinSetIOSurface:(void *)surface plane:(NSUInteger)plane;\n'
    text=text[:start]+chunk+text[end:]
    start=text.index('- (id)newTextureWithDescriptor:(MTLTextureDescriptor *)d iosurface:')
    end=text.index('\n}\n',start)+3
    chunk=text[start:end]
    before='''\treturn [[RedwoodMetalTexture alloc] initWithRedwoodDevice:self
\t\t\t\t\t\t\t texture:texture
\t\t\t\t\t\t\t   shape:&shape];'''
    chunk=replace_once(chunk,before,'''    RedwoodMetalTexture *object=[[RedwoodMetalTexture alloc] initWithRedwoodDevice:self
        texture:texture shape:&shape];
    [object redfinSetIOSurface:s plane:p];return object;''')
    text=text[:start]+chunk+text[end:]
    start=text.index('@implementation RedwoodMetalTexture')
    end=text.index('\n@end',start)
    chunk=text[start:end]
    point='\t[super dealloc];'
    chunk=replace_once(chunk,point,'\tif(_redfinIOSurface)CFRelease(_redfinIOSurface);\n'+point)
    point='- (struct rwa_texture *)mesaTexture { return _texture; }'
    chunk=replace_once(chunk,point,'''- (void)redfinSetIOSurface:(void *)surface plane:(NSUInteger)plane
{
    void *next=surface?(void *)CFRetain(surface):NULL;
    if(_redfinIOSurface)CFRelease(_redfinIOSurface);
    _redfinIOSurface=next;_redfinIOSurfacePlane=plane;
}

'''+point)
    chunk=replace_once(chunk,'- (id)iosurface                    { return nil; }',
        '- (id)iosurface                    { return (id)_redfinIOSurface; }')
    chunk=replace_once(chunk,'- (NSUInteger)iosurfacePlane       { return 0; }',
        '- (NSUInteger)iosurfacePlane       { return _redfinIOSurfacePlane; }')
    # Keep the native API failure for unsupported views, with evidence that
    # distinguishes an actual caller from a merely possible missing feature.
    first=0
    while True:
        at=chunk.find('- (id)newTextureViewWithPixelFormat:',first)
        if at<0:break
        brace=chunk.index('{',at)
        chunk=chunk[:brace+1]+' RW_ONCE("REDFIN METAL UNSERVED: texture view requested\\n");'+chunk[brace+1:]
        first=brace+80
    text=text[:start]+chunk+text[end:]
    replacements={
        '- (id)newFence                                      { return nil; }':
            '- (id)newFence { RW_ONCE("REDFIN METAL UNSERVED: newFence requested\\n");return nil; }',
        '- (id)blitCommandEncoder          { return nil; }':
            '- (id)blitCommandEncoder { RW_ONCE("REDFIN METAL UNSERVED: blitCommandEncoder requested\\n");return nil; }',
        '- (id)resourceStateCommandEncoder { return nil; }':
            '- (id)resourceStateCommandEncoder { RW_ONCE("REDFIN METAL UNSERVED: resourceStateCommandEncoder requested\\n");return nil; }',
        '- (id)newBufferWithIOSurface:(void *)surface        { (void)surface; return nil; }':
            '- (id)newBufferWithIOSurface:(void *)surface { (void)surface;RW_ONCE("REDFIN METAL UNSERVED: IOSurface buffer requested\\n");return nil; }',
        '- (void)encodeSignalEvent:(id)event value:(uint64_t)value { (void)event; (void)value; }':
            '- (void)encodeSignalEvent:(id)event value:(uint64_t)value { (void)event;(void)value;RW_ONCE("REDFIN METAL UNSERVED: signal event requested\\n"); }',
        '- (void)encodeWaitForEvent:(id)event value:(uint64_t)value { (void)event; (void)value; }':
            '- (void)encodeWaitForEvent:(id)event value:(uint64_t)value { (void)event;(void)value;RW_ONCE("REDFIN METAL UNSERVED: wait event requested\\n"); }',
    }
    for before,after in replacements.items():text=replace_once(text,before,after)
    point='\treturn nil;   /* wrapping the caller\'s own pages needs the kernel to map them: not yet */'
    text=replace_once(text,point,'\tRW_ONCE("REDFIN METAL UNSERVED: no-copy buffer requested\\n");\n'+point)
    return text
