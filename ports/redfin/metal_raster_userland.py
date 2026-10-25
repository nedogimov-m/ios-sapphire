"""Complete recorded Metal raster and independent render-pass load actions."""
from ports.redfin.eagl_userland import replace_once


def _method(text, signature, body, start=0):
    first = text.index(signature+'\n{', start)
    last = text.index('\n}\n', first)+3
    return text[:first]+signature+'\n{\n'+body+'\n}\n'+text[last:]


def adapt(text):
    text = '#include "redfin_metal_raster.h"\n'+text
    point = '\t_fragmentBuffers[index] = buffer;'
    text = replace_once(text, point, '''\tstatic unsigned redfin_fragment_bind_reports;
    if(__sync_fetch_and_add(&redfin_fragment_bind_reports,1)<128)
        rw_print("REDFIN METAL FRAGMENT BIND: index=%lu present=%u bytes=%lu offset=%lu\\n",
            (unsigned long)index,buffer!=nil,(unsigned long)[buffer length],(unsigned long)offset);
'''+point)
    point = '''- (void)setFragmentBytes:(const void *)bytes length:(NSUInteger)length atIndex:(NSUInteger)index
{
\tid buffer = [[self device] newBufferWithBytes:bytes length:length options:0];'''
    text = replace_once(text, point, point+'''
    if(!buffer&&length)rw_print("REDFIN METAL FRAGMENT BYTES REFUSED: index=%lu bytes=%lu\\n",
        (unsigned long)index,(unsigned long)length);''')
    text = replace_once(text, '\tunsigned fragment_buffer_table_count;\n};',
        '\tunsigned fragment_buffer_table_count;\n\tconst struct redfin_metal_raster_state *redfin_raster;\n};')
    point = '\tint (*render_draw)(struct rwa_render *, const struct rwa_draw *, char *, size_t);'
    text = replace_once(text, point, point+'\n\tint (*redfin_clear)(struct rwa_device *,struct rwa_texture *const *,unsigned,unsigned,\n'
        '\t\tconst float[8][4],struct rwa_texture *,const float *,const unsigned *,char *,size_t);')
    point = '\t*(void **)&mesa.render_draw = dlsym(mesa.handle, "rwa_render_draw");'
    text = replace_once(text, point, point+'\n\t*(void **)&mesa.redfin_clear=dlsym(mesa.handle,"rwa_redfin_clear_pass");')
    point = 'if (mesa.commands_begin == NULL ||'
    text = replace_once(text, point, 'if (mesa.redfin_clear == NULL || mesa.commands_begin == NULL ||')
    point = '@interface RedwoodMetalWork : NSObject {\n@public'
    text = replace_once(text, point, point+'\n\tBOOL redfinClearOnly;\n\tunsigned redfinClearMask;\n'
        '\tfloat redfinClearColors[8][4];\n\tstruct redfin_metal_raster_state redfinRaster;')
    point = '\tBOOL _hasDepthRange;'
    text = replace_once(text, point, point+'\n\tstruct redfin_metal_raster_state _redfinRaster;\n'
        '\tunsigned _redfinClearMask;\n\tfloat _redfinClearColors[8][4];')
    first = text.index('\t\tif (i == 0 && [attachment loadAction] == MTLLoadActionClear)')
    last = text.index('\n\t\t}', first)+4
    text = text[:first]+'''\t\tif ([attachment loadAction] == MTLLoadActionClear) {
\t\t\tMTLClearColor c=[attachment clearColor];
\t\t\t_redfinClearMask|=1u<<i;
\t\t\t_redfinClearColors[i][0]=(float)c.red;_redfinClearColors[i][1]=(float)c.green;
\t\t\t_redfinClearColors[i][2]=(float)c.blue;_redfinClearColors[i][3]=(float)c.alpha;
\t\t}'''+text[last:]
    encoder = text.index('@implementation RedwoodMetalRenderEncoder')
    first = text.index('- (instancetype)initWithRedwoodCommandBuffer:', encoder)
    last = text.index('\n}\n', first)
    body = text[first:last]
    body = replace_once(body, '\treturn self;', '\t[self redfinRecordPassClear];\n\treturn self;')
    text = text[:first]+body+text[last:]
    point = '- (id)device { return [_commandBuffer device]; }'
    clear_method = '''
- (void)redfinRecordPassClear
{
    if (!_redfinClearMask&&!_clearsDepth&&!_clearsStencil) return;
    RedwoodMetalWork *work=[RedwoodMetalWork new];work->redfinClearOnly=YES;
    work->colorCount=_colorCount;for(unsigned i=0;i<_colorCount;++i)work->color[i]=_color[i];
    work->redfinClearMask=_redfinClearMask;memcpy(work->redfinClearColors,_redfinClearColors,sizeof(_redfinClearColors));
    work->depth=_depth;work->clearDepth=_clearDepth;work->clearStencil=_clearStencil;
    work->clearsDepth=_clearsDepth;work->clearsStencil=_clearsStencil;
    [_commandBuffer recordWork:work];[work release];
    _redfinClearMask=0;_clears=_clearsDepth=_clearsStencil=NO;
}
'''
    first = text.index(point, encoder)
    text = text[:first]+clear_method+'\n'+text[first:]
    text = _method(text, '- (void)setViewport:(MTLViewport)viewport', '''
    _redfinRaster.flags|=1;
    const double values[6]={viewport.originX,viewport.originY,viewport.width,viewport.height,viewport.znear,viewport.zfar};
    memcpy(_redfinRaster.viewport,values,sizeof(values));
    _depthRange[0]=(float)viewport.znear;_depthRange[1]=(float)viewport.zfar;_hasDepthRange=YES;''', encoder)
    for signature, body in [
        ('- (void)setScissorRect:(MTLScissorRect)rect',
         '_redfinRaster.flags|=2;_redfinRaster.scissor[0]=rect.x;_redfinRaster.scissor[1]=rect.y;_redfinRaster.scissor[2]=rect.width;_redfinRaster.scissor[3]=rect.height;'),
        ('- (void)setCullMode:(NSUInteger)mode', '_redfinRaster.cull=mode>UINT32_MAX?UINT32_MAX:(uint32_t)mode;'),
        ('- (void)setFrontFacingWinding:(NSUInteger)winding', '_redfinRaster.winding=winding>UINT32_MAX?UINT32_MAX:(uint32_t)winding;'),
        ('- (void)setTriangleFillMode:(NSUInteger)mode', '_redfinRaster.fill=mode>UINT32_MAX?UINT32_MAX:(uint32_t)mode;'),
    ]:
        first = text.index(signature, encoder);last = text.index('\n', first)
        text = text[:first]+signature+'\n{ '+body+' }'+text[last:]
    text = _method(text, '- (void)setBlendColorRed:(float)r green:(float)g blue:(float)b alpha:(float)a',
        '    _redfinRaster.blend_color[0]=r;_redfinRaster.blend_color[1]=g;_redfinRaster.blend_color[2]=b;_redfinRaster.blend_color[3]=a;', encoder)
    text = _method(text, '- (void)setDepthClipMode:(NSUInteger)mode',
        '    _redfinRaster.depth_clip=mode>UINT32_MAX?UINT32_MAX:(uint32_t)mode;', encoder)
    text = _method(text, '- (void)setDepthBias:(float)bias slopeScale:(float)scale clamp:(float)clamp',
        '    _redfinRaster.depth_bias=bias;_redfinRaster.slope_scale=scale;_redfinRaster.bias_clamp=clamp;', encoder)
    text = _method(text, '- (void)setScissorRects:(const MTLScissorRect *)rects count:(NSUInteger)count',
        '    if(count==1&&rects)[self setScissorRect:rects[0]];else _redfinRaster.flags|=0x80000000u;', encoder)
    text = replace_once(text, '\twork->render = _pipeline;', '\twork->redfinRaster=_redfinRaster;\n\twork->render = _pipeline;')
    point = '\t\t.fragment_buffer_table_count = work->count,'
    text = replace_once(text, point, point+'\n\t\t.redfin_raster=&work->redfinRaster,')
    point = '\tfor (RedwoodMetalWork *work in _work) {\n\t\tif (work->render != nil) {'
    text = replace_once(text, point, '''\tfor (RedwoodMetalWork *work in _work) {
        if(work->redfinClearOnly) {
            struct rwa_texture *colors[8]={0};
            for(unsigned i=0;i<work->colorCount;++i)colors[i]=[work->color[i] mesaTexture];
            if(RF_MESA(redfin_clear,[[_queue device] mesaDevice],colors,work->colorCount,
                work->redfinClearMask,work->redfinClearColors,[work->depth mesaTexture],
                work->clearsDepth?&work->clearDepth:NULL,work->clearsStencil?&work->clearStencil:NULL,
                why,sizeof(why))) {[self failWith:why];goto done;}
            continue;
        }
\t\tif (work->render != nil) {''')
    text = text.replace('{if(work->render) ++draws;else ++computes;}',
        '{if(work->redfinClearOnly)continue;if(work->render) ++draws;else ++computes;}')
    return text
