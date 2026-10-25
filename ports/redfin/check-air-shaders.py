#!/usr/bin/env python3
"""Validate patched AIR and compile A620 instructions on a Mac, without a phone.

The prepared Mesa tree is copied before editing. Private host tools own their
GLSL cache/driver-UBO setup, which their original standalone entry point omits.
No software renderer executes a system shader and no device state is changed.
Apple bitcode, disassembly, snapshots and logs stay in the ignored work directory.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OPTIONS = {
    'b_ndebug': 'false', 'platforms': '', 'gallium-drivers': 'softpipe,freedreno',
    'freedreno-kmds': 'msm', 'vulkan-drivers': '', 'glx': 'disabled', 'egl': 'disabled',
    'gbm': 'disabled', 'osmesa': 'true', 'llvm': 'disabled', 'shared-glapi': 'enabled',
    'gles1': 'disabled', 'gles2': 'enabled', 'opengl': 'true', 'zstd': 'disabled',
    'xmlconfig': 'disabled', 'expat': 'disabled', 'shader-cache': 'disabled',
    'valgrind': 'disabled', 'libunwind': 'disabled', 'glvnd': 'disabled', 'video-codecs': '',
    'tools': '', 'gallium-vdpau': 'disabled', 'gallium-va': 'disabled',
    'gallium-xa': 'disabled', 'lmsensors': 'disabled', 'build-tests': 'false',
}


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('unreviewed standalone compiler anchor: ' + before[:100])
    return text.replace(before, after)


def prepare_ir3_tool(source):
    path = source / 'src/gallium/drivers/freedreno/ir3/ir3_cmdline.c'
    text = path.read_text()
    active = (source/'src/compiler/air/redfin_metal_active_resources.inc').exists()
    if active:
        text = replace_once(text, 'static struct ir3_compiler *compiler;',
                            '#include "redfin_metal_active_resources.inc"\n\nstatic struct ir3_compiler *compiler;')
        text = replace_once(text, '   printf("; AIR: %s, %u resources, %u varyings, %u render targets\\n",',
                            '''   redfin_pipeline_requirements(nir, &info);
   for (unsigned i = 0; i < info.num_resources; i++)
      printf("; REQUIRED: kind=%u index=%u\\n", info.resources[i].kind, info.resources[i].index);
   printf("; AIR: %s, %u resources, %u varyings, %u render targets\\n",''')
    anchor = '   unsigned num_fc = air_module_function_constants(NULL, bitcode, bitcode_size, &fc);'
    text = replace_once(text, anchor, anchor + r'''
   const char *pattern = getenv("REDFIN_HOST_CONSTANT_BYTE");
   if (pattern) for (unsigned i = 0; i < num_fc; i++)
      memset(fc[i].words, (unsigned char)strtoul(pattern, NULL, 0), sizeof(fc[i].words));
   const char *supplied = getenv("REDFIN_HOST_CONSTANT_VALUES");
   if (supplied) {
      for (unsigned i = 0; i < num_fc; i++) {
         memset(fc[i].words, 0, sizeof(fc[i].words)); fc[i].undefined = true;
      }
      char *owned = strdup(supplied), *cursor = owned, *item;
      while ((item = strsep(&cursor, ",")) != NULL && *item) {
         char *end; unsigned index = strtoul(item, &end, 10);
         if (*end++ != '/') errx(1, "invalid explicit host constant index");
         unsigned slot = 0;
         while (slot < num_fc && fc[slot].index != index) slot++;
         if (slot == num_fc || !fc[slot].undefined)
            errx(1, "unknown/duplicate explicit host constant %u", index);
         size_t bytes = strlen(end) / 2;
         if (!bytes || bytes > sizeof(fc[slot].words) || strlen(end) != bytes * 2)
            errx(1, "invalid explicit host constant bytes");
         unsigned char *out = (unsigned char *)fc[slot].words;
         for (size_t i = 0; i < bytes; i++) {
            char pair[3] = {end[2*i], end[2*i+1], 0}, *tail;
            out[i] = strtoul(pair, &tail, 16);
            if (*tail) errx(1, "invalid explicit host constant hex");
         }
         fc[slot].undefined = false;
      }
      free(owned);
   }
''')
    anchor = '   compiler = ir3_compiler_create(NULL, &dev_id, fd_dev_info_raw(&dev_id),'
    text = replace_once(text, anchor, '   glsl_type_singleton_init_or_ref();\n' + anchor)
    anchor = '   v->const_state = rzalloc_size(v, sizeof(*v->const_state));'
    text = replace_once(text, anchor, anchor + '''
   v->const_state->consts_ubo.idx = -1;
   v->const_state->driver_params_ubo.idx = -1;
   v->const_state->primitive_map_ubo.idx = -1;
   v->const_state->primitive_param_ubo.idx = -1;
''')
    anchor = '      NIR_PASS(_, nir, nir_lower_system_values);\n      NIR_PASS(_, nir, nir_lower_compute_system_values, NULL);'
    text = replace_once(text, anchor, '''      const struct nir_lower_sysvals_to_varyings_options coordinates = { .point_coord = true };
      if (nir_lower_sysvals_to_varyings(nir, &coordinates)) {
         nir_foreach_shader_in_variable(var, nir)
            if (var->data.location == VARYING_SLOT_PNTC)
               var->data.driver_location = nir->num_inputs++;
      }
''' + anchor)
    path.write_text(text)


def prepare_memory_probe(source):
    """Use the actual frontend's debug allocator; never guess memory from IR size."""
    path = source/'src/gallium/drivers/freedreno/ir3/ir3_cmdline.c'
    text = path.read_text()
    point = '   nir_shader *nir = air_to_nir(NULL, bitcode, bitcode_size, NULL, &options,'
    text = replace_once(text, point,
        '   void *redfin_host_context = ralloc_context(NULL);\n'
        '   nir_shader *nir = air_to_nir(redfin_host_context, bitcode, bitcode_size, NULL, &options,')
    point = '   nir_print_shader(nir, stdout);\n   return nir;'
    text = replace_once(text, point, r'''
   const char *repeat_text = getenv("REDFIN_HOST_LIFETIME_ROUNDS");
   unsigned repeats = repeat_text ? strtoul(repeat_text, NULL, 10) : 0;
   if (repeats > 32) errx(1, "bounded host shader lifetime rounds required");
   size_t retained = ralloc_total_size(redfin_host_context);
   printf("; AIR MEMORY: shader-bytes=%zu context-bytes=%zu\n",
          ralloc_total_size(nir), retained);
   void *held[32] = {0}; size_t held_bytes = 0;
   for (unsigned round = 0; round < repeats; round++) {
      held[round] = ralloc_context(NULL);
      struct air_shader_info repeated_info;
      nir_shader *repeated = air_to_nir(held[round], bitcode, bitcode_size,
          NULL, &options, ir3_get_compiler_options(compiler), &repeated_info, &err);
      if (!repeated) errx(1, "lifetime round %u: %s", round, err);
      nir_validate_shader(repeated, "repeated actual AIR translation");
      held_bytes += ralloc_total_size(held[round]);
   }
   for (unsigned round = 0; round < repeats; round++) ralloc_free(held[round]);
   if (ralloc_total_size(redfin_host_context) != retained)
      errx(1, "releasing independent shader contexts changed the retained shader");
   nir_validate_shader(nir, "surviving AIR after independent contexts released");
   printf("; AIR LIFETIME: rounds=%u held-bytes=%zu independent-release=1\n",
          repeats, held_bytes);
''' + point)
    path.write_text(text)


def prepare_cache_probe(source):
    path=source/'src/gallium/drivers/freedreno/ir3/ir3_cmdline.c'
    shutil.copy2(ROOT/'ports/redfin/metal-cache-host.inc',path.parent/'redfin_metal_cache_host.inc')
    # Exercise the exact production finalizer and cache. Host callbacks own NIR
    # tokens only; actual A620 state creation/pixels remain a native contract.
    metal=(source/'src/compiler/air/air_metal.c').read_text()
    begin=metal.index('static int\ntype_size_vec4(')
    end=metal.index('static void redfin_air_cache_finish(',begin)
    (path.parent/'redfin_metal_cache_finalizer.inc').write_text(metal[begin:end])
    text=path.read_text()
    point='static struct ir3_compiler *compiler;'
    text=replace_once(text,point,point+'\n#include "redfin_metal_cache_host.inc"')
    # Insert only in the AIR loader, after its bounded memory probe.
    point='   printf("; AIR LIFETIME: rounds=%u held-bytes=%zu independent-release=1\\n",\n          repeats, held_bytes);\n'
    text=replace_once(text,point,point+'   redfin_host_cache_run(bitcode,bitcode_size,&options);\n')
    path.write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mesa-source', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--venv', type=Path, help='reuse a prepared graphics build venv')
    parser.add_argument('--shader', type=Path, action='append', default=[])
    parser.add_argument('--constant-byte', type=lambda s: int(s, 0), action='append')
    parser.add_argument('--snapshots', type=Path, help='private JSON: function name -> {index: hex bytes}')
    parser.add_argument('--lifetime-rounds', type=int, default=0,
                        help='hold/release up to 32 independent translations with native debug allocator accounting')
    parser.add_argument('--cache-check',action='store_true',
                        help='exercise real NIR template serialization, metadata ownership and forced LRU eviction')
    args = parser.parse_args()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ)
    env['PATH'] = '/opt/homebrew/opt/bison/bin:/opt/homebrew/opt/flex/bin:/opt/homebrew/bin:' + env.get('PATH', '')
    report = {'success': False, 'device_execution': False, 'checks': [],
              'date_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    setup_log = work / 'host-build.log'
    with setup_log.open('w') as log:
        def run(command, capture=False, timeout=300):
            log.write(repr(list(map(str, command))) + '\n'); log.flush()
            return subprocess.run(list(map(str, command)), env=env, check=True, timeout=timeout,
                                  text=True, stdout=subprocess.PIPE if capture else log, stderr=log)
        try:
            native = args.mesa_source.resolve()
            inputs = ['air_private.h', 'air_to_nir.c', 'air_intrinsics.c', 'air_metal.c']
            report['air_sha256'] = {name: hashlib.sha256((native/'src/compiler/air'/name).read_bytes()).hexdigest()
                                    for name in inputs}
            stamp = native/'.redfin-graphics'
            report['mesa_input_sha256'] = stamp.read_text().strip() if stamp.is_file() else None
            report['air_extensions_sha256'] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((native/'src/compiler/air').glob('redfin_*.inc'))}
            source = work / 'mesa'
            source.mkdir()
            run(['cp', '-cR', str(native) + '/.', source])
            prepare_ir3_tool(source)
            if not 0 <= args.lifetime_rounds <= 32:
                raise ValueError('lifetime rounds must be between 0 and 32')
            prepare_memory_probe(source)
            if args.cache_check:
                prepare_cache_probe(source)
                report['cache_probe_sha256']=hashlib.sha256((ROOT/'ports/redfin/metal-cache-host.inc').read_bytes()).hexdigest()
            venv = args.venv.resolve() if args.venv else work/'venv'
            if not (venv/'bin/meson').is_file():
                run([sys.executable, '-m', 'venv', venv])
                run([venv/'bin/python3', '-m', 'pip', 'install', 'meson==1.9.1', 'Mako==1.3.10',
                     'packaging==25.0', 'PyYAML==6.0.3'])
            env['PATH'] = str(venv/'bin') + ':' + env['PATH']
            sdk = run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], capture=True).stdout.strip()
            cross = work/'mac.ini'
            lines = ['[binaries]']
            for language, name in [('c', 'clang'), ('cpp', 'clang++'), ('objc', 'clang')]:
                compiler = run(['xcrun', '--find', name], capture=True).stdout.strip()
                lines.append(language + ' = ' + repr([compiler, '-target', 'arm64-apple-macos14.0', '-isysroot', sdk]))
            lines += ["ar = '/usr/bin/ar'", "ranlib = '/usr/bin/ranlib'", "pkg-config = 'false'",
                      '[host_machine]', "system = 'darwin'", "cpu_family = 'aarch64'",
                      "cpu = 'arm64'", "endian = 'little'", '[properties]', 'needs_exe_wrapper = false']
            cross.write_text('\n'.join(lines) + '\n')
            build = work/'build'
            run([venv/'bin/meson', 'setup', build, source, '--cross-file', cross, '--wrap-mode=nofallback',
                 '--prefix=/redfin', '--libdir=lib', '--buildtype=release',
                 *['-D'+key+'='+value for key, value in OPTIONS.items()]])
            run(['ninja', '-C', build, 'src/compiler/air/air2nir',
                 'src/gallium/drivers/freedreno/ir3_compiler'])
            contract = work/'resource-check.bc'
            run(['xcrun', '--sdk', 'iphoneos', 'metal', '-x', 'ir', '-c', '-emit-llvm', '-O0',
                 '-Xclang', '-disable-llvm-passes', ROOT/'ports/redfin/metal-resource-check.ll', '-o', contract])
            shaders = [*map(Path.resolve, args.shader), contract]
            validated = run([build/'src/compiler/air/air2nir', '--report', *shaders], capture=True)
            validation_log = work/'nir-validation.log'
            validation_log.write_text(validated.stdout)
            accepted = [line for line in validated.stdout.splitlines()
                        if line.startswith('module=') and '\ttranslate=ok' in line]
            report['nir_validation'] = dict(accepted=len(accepted), expected=len(shaders), log=str(validation_log))
            if len(accepted) != len(shaders):
                raise ValueError('an authored/system module failed NIR validation')
            snapshot_sets = json.loads(args.snapshots.read_text()) if args.snapshots else {}
            patterns = args.constant_byte or [0, 1]
            if any(value < 0 or value > 255 for value in patterns):
                raise ValueError('constant bytes must be between 0 and 255')
            for number, shader in enumerate(shaders):
                explicit = snapshot_sets.get(shader.stem)
                cases = ['snapshot'] if explicit is not None else patterns
                for pattern in cases:
                    check_env = dict(env)
                    check_env['REDFIN_HOST_LIFETIME_ROUNDS'] = str(args.lifetime_rounds)
                    if explicit is not None:
                        fields = []
                        for index, value in sorted(explicit.items(), key=lambda item: int(item[0])):
                            data = bytes.fromhex(value)
                            if not data or len(data) > 32 or not 0 <= int(index) <= 0xffffffff:
                                raise ValueError('invalid actual function-constant snapshot')
                            fields.append(str(int(index))+'/'+data.hex())
                        check_env['REDFIN_HOST_CONSTANT_VALUES'] = ','.join(fields)
                    else:
                        check_env['REDFIN_HOST_CONSTANT_BYTE'] = str(pattern)
                    output = work/f'{number:02d}-{shader.stem}-{pattern}.log'
                    started = time.monotonic()
                    with output.open('w') as stream:
                        checked = subprocess.run([str(build/'src/gallium/drivers/freedreno/ir3_compiler'),
                            '--gpu', '620', str(shader)], env=check_env, stdout=stream,
                            stderr=subprocess.STDOUT, timeout=180)
                    report['checks'].append(dict(shader=str(shader), pattern=pattern,
                        exit_code=checked.returncode, seconds=round(time.monotonic()-started, 3), log=str(output)))
            report['success'] = bool(report['checks']) and all(item['exit_code'] == 0 for item in report['checks'])
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report['error'] = str(error)
    (work/'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(('PASS' if report['success'] else 'FAIL') + ': offline A620 compiler; ' + str(work/'result.json'))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
