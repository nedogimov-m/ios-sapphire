"""Native Metal function specialization, with immutable per-function values."""
from pathlib import Path
from ports.redfin.eagl_userland import replace_once


def adapt(text):
    text=replace_once(text,'#include "redfin_metal_buffer_import.h"',
        '#include "redfin_metal_buffer_import.h"\n#include "redfin_metal_function_constants.h"')
    point='static void ensure_function_encoder(void);'
    text=replace_once(text,point,point+'''
static void redfin_install_function_constants(void);
static struct redfin_metal_constants redfin_function_constants(id);
''')
    # Existing legacy exports remain available for upstream clients. Every
    # native Metal compilation uses the function's explicit specialization.
    point='\tvoid (*compute_destroy)(struct rwa_compute *);'
    text=replace_once(text,point,'''
    struct rwa_compute *(*redfin_compute_create)(struct rwa_device *,const void *,size_t,const char *,struct rwa_compute_info *,const struct redfin_metal_constants *,char *,size_t);
    struct rwa_render *(*redfin_render_create)(struct rwa_device *,const void *,size_t,const char *,const void *,size_t,const char *,const struct rwa_render_shape *,struct rwa_render_info *,const struct redfin_metal_constants *,const struct redfin_metal_constants *,char *,size_t);
    int (*redfin_module_argbufs)(struct rwa_device *,const void *,size_t,const char *,struct rwa_argbuf_layout *,unsigned,unsigned *,const struct redfin_metal_constants *,char *,size_t);
'''+point)
    point='\t*(void **)&mesa.compute_create = dlsym(mesa.handle, "rwa_compute_create");'
    text=replace_once(text,point,point+'''
    *(void **)&mesa.redfin_compute_create=dlsym(mesa.handle,"rwa_redfin_compute_create");
    *(void **)&mesa.redfin_render_create=dlsym(mesa.handle,"rwa_redfin_render_create");
    *(void **)&mesa.redfin_module_argbufs=dlsym(mesa.handle,"rwa_redfin_module_argbufs");''')
    point='if (mesa.redfin_texture_from_buffer == NULL ||'
    text=replace_once(text,point,'if (mesa.redfin_compute_create == NULL || mesa.redfin_render_create == NULL || mesa.redfin_module_argbufs == NULL || mesa.redfin_texture_from_buffer == NULL ||')
    point='if (!redfin_metal_abi_ready() || !redfin_metal_hardware_ready()) { object_dispose(self); return nil; }'
    text=replace_once(text,point,point+'\n    redfin_install_function_constants();')
    point='\tstruct rwa_render *render = RF_MESA(render_create,_mesa,'
    text=replace_once(text,point,'''
    struct redfin_metal_constants vertex_values=redfin_function_constants(vertex),fragment_values=redfin_function_constants(fragment);
\tstruct rwa_render *render = RF_MESA(redfin_render_create,_mesa,''')
    point='\t    &shape, &info, why, sizeof(why));'
    text=replace_once(text,point,'\t    &shape, &info, &vertex_values, &fragment_values, why, sizeof(why));')
    point='\tstruct rwa_compute *compute = RF_MESA(compute_create,_mesa, [air bytes], [air length],'
    text=replace_once(text,point,'''
    struct redfin_metal_constants values=redfin_function_constants(function);
\tstruct rwa_compute *compute = RF_MESA(redfin_compute_create,_mesa, [air bytes], [air length],''')
    point='''\t\t\t\t\t\t\t  [[function name] UTF8String], &info,
\t\t\t\t\t\t\t  why, sizeof(why));'''
    text=replace_once(text,point,point.replace('why, sizeof(why)', '&values, why, sizeof(why)'))
    point='\tif (RF_MESA(module_argbufs,_mesa, [air bytes], [air length],'
    text=replace_once(text,point,'''
    struct redfin_metal_constants values=redfin_function_constants(function);
\tif (RF_MESA(redfin_module_argbufs,_mesa, [air bytes], [air length],''')
    point='\t\t\t\t(unsigned)(sizeof(sets) / sizeof(sets[0])), &count, why,'
    text=replace_once(text,point,point.replace('&count, why,','&count, &values, why,'))
    return text+'\n'+Path(__file__).with_name('metal-function-constants-object.inc').read_text()
