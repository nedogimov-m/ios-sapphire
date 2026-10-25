"""Record native Metal transfers in the existing ordered command-buffer path."""
from pathlib import Path
from ports.redfin.eagl_userland import replace_once


def adapt(text):
    text = '#include "redfin_metal_blit.h"\n'+text
    point = '- (void)recordWork:(RedwoodMetalWork *)work;'
    text = replace_once(text, point, point+'\n- (void)redfinRetainResource:(id)resource;')
    point = '@interface RedwoodMetalComputeEncoder : _MTLCommandEncoder'
    text = replace_once(text, point, '''@interface RedfinMetalBlitEncoder : _MTLCommandEncoder
- (instancetype)initWithRedfinCommandBuffer:(RedwoodMetalCommandBuffer *)command;
@end

'''+point)
    point = '@interface RedwoodMetalWork : NSObject {\n@public'
    text = replace_once(text, point, point+'''\n    struct redfin_metal_blit redfinBlit;
    id redfinBlitSource,redfinBlitDestination;''')
    point = '\tint (*commands_begin)(struct rwa_device *, char *, size_t);'
    text = replace_once(text, point, point+'''
    int (*redfin_blit)(struct rwa_device *,struct rwa_buffer *,struct rwa_buffer *,
        struct rwa_texture *,struct rwa_texture *,const struct redfin_metal_blit *,char *,size_t);''')
    point = '\t*(void **)&mesa.commands_begin = dlsym(mesa.handle, "rwa_commands_begin");'
    text = replace_once(text, point, point+'\n    *(void **)&mesa.redfin_blit=dlsym(mesa.handle,"rwa_redfin_blit");')
    point = 'if (mesa.redfin_clear == NULL ||'
    text = replace_once(text, point, 'if (mesa.redfin_blit == NULL || mesa.redfin_clear == NULL ||')
    point = '- (id)blitCommandEncoder { RW_ONCE("REDFIN METAL UNSERVED: blitCommandEncoder requested\\n");return nil; }'
    text = replace_once(text, point, '''- (id)blitCommandEncoder
{
    return [[[RedfinMetalBlitEncoder alloc] initWithRedfinCommandBuffer:self] autorelease];
}
- (id)blitCommandEncoderWithDescriptor:(id)descriptor
{
    /* Ordinary transfers have no counter sample attachments on this device. */
    if(descriptor&&[descriptor respondsToSelector:@selector(sampleBufferAttachments)]) {
        id attachments=[descriptor sampleBufferAttachments];
        for(NSUInteger i=0;i<4;++i)if([[attachments objectAtIndexedSubscript:i] sampleBuffer])return nil;
    }
    return [self blitCommandEncoder];
}''')
    point = '\tfor (RedwoodMetalWork *work in _work) {\n        if(work->redfinClearOnly) {'
    text = replace_once(text, point, '''\tfor (RedwoodMetalWork *work in _work) {
        if(work->redfinBlit.operation) {
            id source=work->redfinBlitSource,destination=work->redfinBlitDestination;
            struct rwa_buffer *sb=[source isKindOfClass:[RedwoodMetalBuffer class]]?[source mesaBuffer]:NULL;
            struct rwa_buffer *db=[destination isKindOfClass:[RedwoodMetalBuffer class]]?[destination mesaBuffer]:NULL;
            struct rwa_texture *st=[source isKindOfClass:[RedwoodMetalTexture class]]?[source mesaTexture]:NULL;
            struct rwa_texture *dt=[destination isKindOfClass:[RedwoodMetalTexture class]]?[destination mesaTexture]:NULL;
            if(RF_MESA(redfin_blit,[[_queue device] mesaDevice],sb,db,st,dt,&work->redfinBlit,why,sizeof(why))) {
                [self failWith:why];goto done;
            }
            continue;
        }
        if(work->redfinClearOnly) {''')
    text = replace_once(text, '{if(work->redfinClearOnly)continue;if(work->render) ++draws;else ++computes;}',
        '{if(work->redfinClearOnly||work->redfinBlit.operation)continue;if(work->render) ++draws;else ++computes;}')
    return text+'\n'+Path(__file__).with_name('metal-blit-encoder.inc').read_text()
