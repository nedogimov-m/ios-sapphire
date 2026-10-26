"""Prepare the pinned MIT EAGL bridge for Redfin and the installed cache ABI.

Keep upstream's shader, IOSurface and compositor adaptations together. Do not
copy inject.c's 20F66 addresses, input replacement or prototype Metal device.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from ports.redfin.graphics_abi import Cache, derive_eagl, derive_ca, EAGL_METHODS, require


def replace_once(text, before, after):
    require(text.count(before) == 1, 'unreviewed preferred EAGL source: ' + before[:80])
    return text.replace(before, after, 1)


def header(abi, ca):
    def literal(value):
        return json.dumps(value)

    lines = ['/* Generated from the paired actual 20H392 cache; keep private. */',
        '#ifndef REDFIN_EAGL_ABI_H', '#define REDFIN_EAGL_ABI_H',
        '#include <stdint.h>',
        '#define REDFIN_EAGL_IMAGE ' + literal(abi['path']),
        '#define REDFIN_EAGL_UUID ' + literal(abi['uuid']),
        '#define REDFIN_EAGL_MACRO_BIAS ' + str(abi['macro_bias']),
        '#define REDFIN_EAGL_TLS_OFFSET ' + str(abi['tls_offset']),
        '#define REDFIN_EAGL_WRAPPERS ' + str(len(abi['wrappers'])),
        '#define REDFIN_EAGL_METHODS ' + str(len(EAGL_METHODS)),
        'static const uint8_t redfin_eagl_uuid[16]={' +
            ','.join('0x'+abi['uuid'][i:i+2] for i in range(0,32,2)) + '};',
        'struct redfin_eagl_method {const char *name,*types;uintptr_t rva;int meta;};',
        'static const struct redfin_eagl_method redfin_eagl_methods[]={']
    for name in EAGL_METHODS:
        method = abi['methods'][name]
        lines.append('{' + ','.join((literal(name[1:]), literal(method['types']), hex(method['rva']),
                                     str(int(name[0] == '+')))) + '},')
    lines += ['};', '#define REDFIN_CA_IMAGE ' + literal(ca['path']),
        'static const uint8_t redfin_ca_uuid[16]={' +
            ','.join('0x'+ca['uuid'][i:i+2] for i in range(0,32,2)) + '};']
    for field in ('state_offset','function_offset','supported_rva','uniform_rva',
                  'supported_slot_rva','uniform_slot_rva'):
        lines.append('#define REDFIN_CA_' + field.upper() + ' ' + hex(ca[field]))
    return '\n'.join(lines + ['#endif', ''])


def adapt_source(text, abi):
    text = replace_once(text, '#include <IOSurface/IOSurfaceRef.h>', '#include "iosurface-abi.h"')
    text = replace_once(text, '#include "redwood_gl.h"',
                        '#include "redwood_gl.h"\n#include "eagl-guard.h"\n#include "eagl-abi.h"')
    text = replace_once(text, 'struct eagl {\n\tvoid *table[SLOTS];',
        'struct eagl {\n\tvoid *native_prefix[REDFIN_EAGL_MACRO_BIAS / sizeof(void *)];\n\tvoid *table[SLOTS];')
    text = replace_once(text, 'static unsigned trace_first, trace_last;',
        '_Static_assert(offsetof(struct eagl, table) == REDFIN_EAGL_MACRO_BIAS, "native and macro context bases");\n\n'
        'static unsigned trace_first, trace_last;')
    text = replace_once(text, '#include <stdarg.h>', '#include <stdarg.h>\n#include <stddef.h>')
    text = replace_once(text, '\t\tcurrent = e;\n',
                        '\t\tcurrent = e;\n\t\tredfin_eagl_set_tls(e->native_prefix);\n')
    text = replace_once(text, '\tIOObjectRelease(display);\n\treturn waits;',
        '\tif (!waits) waits = redfin_eagl_display_waits(display);\n'
        '\tIOObjectRelease(display);\n\treturn waits;')
    # Upstream's zero-time GL client wait can leave the Gallium CPU worker
    # pending. Flush that worker and publish the real kernel fence first;
    # the retained display FIFO alone waits for GPU completion. Explicit
    # glFinish and the upstream synchronous/copy paths retain their semantics.
    publication = '''\t\tGLsync sync = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);

\t\tif (sync != NULL) {
\t\t\t(void)glClientWaitSync(sync, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
\t\t\tglDeleteSync(sync);
\t\t}'''
    text = replace_once(text, publication,
        '\t\tif (!redfin_eagl_publish_frame()) glFinish();')
    text = replace_once(text, '\te->frames++;\n',
        '\te->frames++;\n\tredfin_eagl_frame(e->frames,e->draws,e->triangles,in_place,copied,e->errors);\n')
    text = replace_once(text, '\tcurrent = e;\n\te->object = self;',
        '\tif (!redfin_eagl_hardware()) {\n'
        '\t\tredwood_gl_make_current(NULL); redwood_gl_destroy(e->gl); free(e); return nil;\n\t}\n'
        '\tcurrent = e;\n\te->native_prefix[0] = (void *)self;\n'
        '\te->native_prefix[2] = (void *)(uintptr_t)api;\n'
        '\tredfin_eagl_set_tls(e->native_prefix);\n\te->object = self;')
    text = replace_once(text, '\t\t\tcurrent = NULL;\n',
                        '\t\t\tcurrent = NULL;\n\t\t\tredfin_eagl_set_tls(NULL);\n')
    text = replace_once(text, '\t\tredwood_gl_destroy(e->gl);\n\t\tfree(e);',
        '\t\tfor (unsigned i=0;i<e->image_count;i++) CFRelease(e->images[i].surface);\n'
        '\t\tfor (unsigned i=0;i<256;i++) free((void *)e->sources[i]);\n'
        '\t\tredwood_gl_destroy(e->gl);\n\t\tfree(e);')
    # Derive the CA fields from function_supported in the paired cache. The
    # preferred bridge uses these fields when drawing a shader-less function.
    before = '*(*(uint8_t **)((char *)ca_context + 0x10) + 0x10)'
    require(text.count(before) == 3, 'unreviewed preferred CA field uses')
    text = text.replace(before, '*(*(uint8_t **)((char *)ca_context + REDFIN_CA_STATE_OFFSET) + REDFIN_CA_FUNCTION_OFFSET)')
    methods = '''static BOOL
my_setCurrentContext(id cls, SEL selector, id object)
{
    (void)cls; (void)selector;
    struct eagl *e=object?context_of(object):NULL;
    if ((object && !e) || !redwood_gl_make_current(e?e->gl:NULL)) return NO;
    current=e;
    redfin_eagl_set_tls(e?e->native_prefix:NULL);
    return YES;
}

static id
my_currentContext(id cls, SEL selector)
{
    (void)cls; (void)selector;
    return current?current->object:nil;
}

'''
    text = replace_once(text, '__attribute__((constructor)) static void\ninstall(void)',
                        methods + '__attribute__((constructor)) static void\ninstall(void)')
    text = replace_once(text, '\t\t{ "initWithAPI:properties:", (IMP)my_initWithAPI },',
        '\t\t{ "initWithAPI:properties:", (IMP)my_initWithAPI },\n'
        '\t\t{ "commonInitWithAPI:properties:", (IMP)my_initWithAPI },')
    text = replace_once(text, '\t/* the kernel\'s boot-args are where a run is told things */',
        '\tif (!redfin_eagl_validate()) return;\n\n'
        '\t/* the kernel\'s boot-args are where a run is told things */')
    # Every method was checked before the first change. All instance methods
    # here are owned by EAGLContext in the reviewed cache, including dealloc.
    tail = '''
    method_setImplementation(class_getClassMethod(class,sel_registerName("setCurrentContext:")),(IMP)my_setCurrentContext);
    method_setImplementation(class_getClassMethod(class,sel_registerName("currentContext")),(IMP)my_currentContext);
    replaced += 2;
    redfin_eagl_mark_installed(replaced);
'''
    text = replace_once(text, '\tsay("redwood-gl: %u of %zu methods of EAGLContext are ours;',
                        tail + '\tsay("redwood-gl: %u of %zu methods of EAGLContext are ours;')
    return text


def prepare(upstream, source, osmesa, out, cache_path):
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    src = Path(upstream) / 'userland/src'
    with Cache(cache_path) as cache:
        abi, ca = derive_eagl(cache), derive_ca(cache)
    used = set(); old_slots = {}
    for line in (src / 'eagl_slots.txt').read_text().splitlines():
        fields = line.split('#', 1)[0].split()
        if fields:
            offset, mark, *names = fields
            for name in names:
                old_slots[name] = int(offset,16)
                if mark == '*':
                    used.add(name)
    require(set(old_slots) == set(abi['wrappers']), 'preferred/current GL export identities differ')
    require(all(abi['wrappers'][name]['slot'] == slot for name,slot in old_slots.items()),
            'macro context dispatch differs from preferred source; adapt manual handlers first')
    slots = ['# Derived from actual 20H392 wrappers minus the native macro-context prefix.']
    for offset, names in sorted(abi['groups'].items()):
        slots.append(f'{offset:#06x} ' + ('*' if used.intersection(names) else '-') + ' ' + ' '.join(names))
    (out / 'eagl_slots.txt').write_text('\n'.join(slots) + '\n')
    (out / 'eagl-abi.h').write_text(header(abi,ca))
    (out / 'eagl.c').write_text(adapt_source((src / 'eagl.c').read_text(),abi))
    shutil.copy2(src / 'gl_osmesa.c',out / 'gl_osmesa.c')
    shutil.copy2(src / 'redwood_gl.h',out / 'redwood_gl.h')
    shutil.copy2(Path(upstream) / 'LICENSE',out / 'UPSTREAM-LICENSE')
    exports = subprocess.check_output(['nm','-gU',str(osmesa)],text=True)
    names = sorted({line.rsplit(None,1)[-1][1:] for line in exports.splitlines()
                    if re.search(r'\s_gl\w+$',line)})
    require(len(names) > 1000, 'Mesa exports missing')
    (out / 'exported-gl.txt').write_text('\n'.join(names) + '\n')
    command = [sys.executable,str(Path(upstream) / 'userland/mkeagl.py'),str(out / 'eagl_slots.txt'),
               str(Path(source) / 'src/mapi/glapi/registry/gl.xml'),str(out / 'exported-gl.txt'),str(out / 'eagl.c')]
    with (out / 'eagl_gen.h').open('w') as stream:
        subprocess.run(command,stdout=stream,check=True)
    report = dict(abi=abi,ca=ca,source_sha256=hashlib.sha256((out / 'eagl.c').read_bytes()).hexdigest(),
                  wrappers=len(abi['wrappers']),macro_table_matches_preferred=True)
    (out / 'abi.json').write_text(json.dumps(report,indent=2) + '\n')
    return report
