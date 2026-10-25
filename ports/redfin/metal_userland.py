"""Adapt the preferred Metal/AIR driver to the installed Redfin arm64 ABI.

Generated Apple metadata and upstream copies stay in the private build tree.
The kernel's actual 128 MiB object bound applies to every advertised buffer.
"""
import hashlib
import json
import copy
from pathlib import Path
import plistlib
import re
import shutil
import struct

from ports.redfin.graphics_abi import Cache, require
from ports.redfin.eagl_userland import replace_once
from ports.redfin.wifi_userland import _encode_same_size

JOB_PATH='/System/Library/LaunchDaemons/com.redfin.metal-check.plist'
LOG_PATH='/private/var/mobile/Library/Logs/redfin-metal-check.log'


def job():
    return dict(Label='com.redfin.metal-check',ProgramArguments=['/redfin/bin/metal-check'],
        RunAtLoad=True,KeepAlive=False,UserName='mobile',ProcessType='Background',
        StandardOutPath=LOG_PATH,StandardErrorPath=LOG_PATH,
        EnvironmentVariables={'FD_MESA_DEBUG':'sysmem','RWA_SOFTWARE':'0'},
        JetsamProperties={'ActiveHardMemoryLimit':512,'InactiveHardMemoryLimit':512})


def patch_launchd_cache(original):
    require(isinstance(original,bytes) and original.startswith(b'bplist00') and
            40<=len(original)<=16*1024**2,'bounded native launchd cache required')
    before=plistlib.loads(original);after=copy.deepcopy(before)
    jobs=after.get('LaunchDaemons');require(isinstance(jobs,dict),'native launchd jobs absent')
    found=[(k,v) for k,v in jobs.items() if isinstance(v,dict) and v.get('Label')==job()['Label']]
    require(not found or found==[(JOB_PATH,job())],'conflicting Metal checker identity')
    require(JOB_PATH not in jobs or bool(found),'occupied Metal checker path')
    jobs[JOB_PATH]=job()
    if after==before:return original,dict(changed=False)
    encoded,padding=_encode_same_size(after,len(original),compact=True)
    decoded=plistlib.loads(encoded)
    for value in (before,decoded):value['LaunchDaemons'].pop(JOB_PATH,None)
    require(decoded==before,'Metal checker changed an unrelated native job')
    return encoded,dict(changed=True,padding_bytes=padding)


def inventory(bundle):
    bundle=Path(bundle);proof=json.loads((bundle/'metal-build.json').read_text())
    require(proof.get('success') and proof.get('actual_abi_compatible') and
            proof.get('max_buffer_bytes')==128<<20,'complete actual-ABI Metal bundle required')
    result=[]
    for target,record in proof['files'].items():
        require(target.startswith('/') and '..' not in Path(target).parts,'unsafe Metal bundle destination')
        source=bundle/record['source']
        require(bundle.resolve() in source.resolve().parents and source.is_file() and
                not source.is_symlink(),'unsafe Metal bundle source')
        require(hashlib.sha256(source.read_bytes()).hexdigest()==record['sha256'],'Metal bundle artifact changed')
        result.append((source,target,record['uid'],record['mode'],record['sha256']))
    return result


def prepare_root(root,metadata,bundle):
    from ports.redfin.userland_files import prepare as prepare_files
    root=Path(root).resolve()
    prepare_files(root,metadata,[(source,target,uid,mode,digest,target.endswith('.log'))
        for source,target,uid,mode,digest in inventory(bundle)])
    path=root/'System/Library/xpc/launchd.plist'
    require(not path.is_symlink() and root in path.resolve().parents,'native launchd cache escapes root')
    before=path.read_bytes();after,proof=patch_launchd_cache(before)
    with path.open('r+b') as stream:
        require(stream.write(after)==len(after),'short Metal startup write')
        stream.flush();stream.seek(0)
        require(stream.read()==after,'Metal startup readback differs')
    return proof

METAL = '/System/Library/Frameworks/Metal.framework/Metal'
METHODS = {
    '_MTLDevice': ('-init', '-initWithAcceleratorPort:', '-targetDeviceInfo',
                   '-initLimits', '-initGPUFamilySupport'),
    '_MTLCommandQueue': ('-initWithDevice:descriptor:',),
    '_MTLCommandBuffer': ('-initWithQueue:retainedReferences:synchronousDebugMode:',),
    '_MTLCommandEncoder': ('-initWithCommandBuffer:', '-endEncoding'),
    '_MTLComputePipelineState': ('-initWithDevice:pipelineStateDescriptor:',),
    '_MTLRenderPipelineState': ('-initWithDevice:pipelineStateDescriptor:',),
    '_MTLDepthStencilState': ('-initWithDevice:depthStencilDescriptor:',),
    '_MTLSamplerState': ('-initWithDevice:samplerDescriptor:',),
    '_MTLFunction': ('-bitcodeData', '-newArgumentEncoderWithBufferIndex:',
                     '-newArgumentEncoderWithBufferIndex:reflection:'),
}


def native_ivars(cache, image, class_name):
    start, length = image.sections['__objc_classlist']
    for at in range(start, start + length, 8):
        obj = cache.pointer(at); ro = cache.pointer(obj + 32) & ~7
        if cache.string(cache.pointer(ro + 24)) != class_name:
            continue
        table = cache.pointer(ro + 48)
        require(table != 0, 'native Metal ivar list absent: ' + class_name)
        stride, count = struct.unpack('<II', cache.read(table, 8))
        require(stride == 32 and count < 256, 'unreviewed native Metal ivar list')
        result = {}
        for n in range(count):
            entry = table + 8 + stride * n
            offset_ptr, name, types = (cache.pointer(entry + 8 * j) for j in range(3))
            offset, = struct.unpack('<I', cache.read(offset_ptr, 4))
            size, = struct.unpack('<I', cache.read(entry + 28, 4))
            result[cache.string(name)] = dict(types=cache.string(types), size=size, offset=offset)
        return result
    raise ValueError('native Metal class absent: ' + class_name)


def derive(cache):
    image = cache.image(METAL)
    exports,_=image.exports()
    require(bool(exports.get('_MTLAddDevice')),'native Metal registration export absent')
    result = dict(path=METAL, uuid=image.uuid, methods={})
    for cls, names in METHODS.items():
        methods = image.objc_methods(cls)
        require(all(name in methods for name in names), 'missing actual Metal base method: ' + cls)
        result['methods'][cls] = {name: methods[name] for name in names}
    require(result['methods']['_MTLDevice']['-targetDeviceInfo']['types'] ==
            'r^{MTLTargetDeviceArch=QI*}16@0:8', 'unreviewed native Metal target struct')
    result['ivars'] = {}
    for cls, name, size in (('_MTLCommandQueue', '_commandBufferSemaphore', 8),
                           ('_MTLCommandQueue', '_completionQueue', 8),
                           ('_MTLCommandBuffer', '_needsCommandBufferSemaphoreSignal', 1)):
        ivar = native_ivars(cache, image, cls).get(name)
        require(ivar and ivar['size'] == size and ivar['types'][0] == ('B' if size == 1 else '@'),
                'unreviewed native Metal lifetime ivar: ' + cls + '.' + name)
        result['ivars'].setdefault(cls, {})[name] = ivar
    return result


def header(abi, pairing):
    rows = ['/* Generated from the installed cache; no upstream instruction addresses. */',
            '#include <stdint.h>', '#define REDFIN_METAL_PAIRING ' + json.dumps(pairing),
            'static const uint8_t redfin_metal_uuid[16]={' +
            ','.join('0x' + abi['uuid'][i:i+2] for i in range(0, 32, 2)) + '};',
            'struct redfin_metal_method {const char *cls,*name,*types;};',
            'static const struct redfin_metal_method redfin_metal_methods[]={']
    for cls, methods in abi['methods'].items():
        for name, method in methods.items():
            rows.append('{' + ','.join(map(json.dumps, (cls, name[1:], method['types']))) + '},')
    return '\n'.join(rows + ['};', ''])


LOCKING = r'''
/* A device owns one unthreaded Gallium context. Every library call, including
 * compilation, destruction, surface import and different command queues, shares
 * this recursive gate. A dispatch/draw binds, submits and fences under one gate. */
static pthread_once_t redfin_mesa_once=PTHREAD_ONCE_INIT;
static pthread_mutex_t redfin_mesa_mutex;
static void redfin_mesa_init(void)
{
    pthread_mutexattr_t attr;
    if (pthread_mutexattr_init(&attr) ||
        pthread_mutexattr_settype(&attr,PTHREAD_MUTEX_RECURSIVE) ||
        pthread_mutex_init(&redfin_mesa_mutex,&attr)) abort();
    pthread_mutexattr_destroy(&attr);
}
void redfin_metal_lock(void)
{
    if (pthread_once(&redfin_mesa_once,redfin_mesa_init) ||
        pthread_mutex_lock(&redfin_mesa_mutex)) abort();
}
void redfin_metal_unlock(void)
{ if (pthread_mutex_unlock(&redfin_mesa_mutex)) abort(); }
static int redfin_metal_enter(void) {redfin_metal_lock();return 1;}
static void redfin_metal_leave(int *locked) {(void)locked;redfin_metal_unlock();}
#define REDFIN_MESA_SCOPE int rf_mesa_locked_ __attribute__((cleanup(redfin_metal_leave)))=redfin_metal_enter(); (void)rf_mesa_locked_
#define RF_MESA(member,...) ({ REDFIN_MESA_SCOPE; mesa.member(__VA_ARGS__); })
'''

FENCE_OBSERVATIONS = r'''
/* Completion evidence is emitted only after Gallium's actual fence succeeds.
 * Keep callback/timer activity separate from commands that reached the GPU. */
static pthread_once_t redfin_fence_once=PTHREAD_ONCE_INIT;
static char redfin_fence_boot[17];
static uint64_t redfin_fence_count;
static void redfin_fence_identity(void)
{
    char args[1024]={0};size_t bytes=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || !bytes || bytes>sizeof(args)) return;
    const char *nonce=strstr(args,"redfinbootid=0x");
    if (nonce && strlen(nonce+15)>=16) memcpy(redfin_fence_boot,nonce+15,16);
}
static void redfin_metal_completed(unsigned draws,unsigned computes)
{
    if ((!draws && !computes) || pthread_once(&redfin_fence_once,redfin_fence_identity) || !redfin_fence_boot[0]) return;
    uint64_t count=__atomic_add_fetch(&redfin_fence_count,1,__ATOMIC_RELAXED);
    if (count<=4 || !(count&(count-1)) || !(count%120))
        rw_print("REDFIN METAL FENCE: boot=%s sequence=%llu draws=%u computes=%u actual-finish=1\n",
            redfin_fence_boot,(unsigned long long)count,draws,computes);
}
'''


def adapt_driver(text):
    text = replace_once(text, '#include "redwood_drawable.h"',
        '#include "redwood_drawable.h"\n#include "metal-abi.h"\n#include <pthread.h>\n'
        'extern int redfin_metal_abi_ready(void);\nextern int redfin_metal_hardware_ready(void);')
    text = replace_once(text, 'static bool\nmesa_available(void)', LOCKING + FENCE_OBSERVATIONS + '\nstatic bool\nmesa_available(void)')
    text = replace_once(text, 'mesa_available(void)\n{', 'mesa_available(void)\n{\n\tREDFIN_MESA_SCOPE;')
    # Diagnostics also run from independent native command queues.
    text = replace_once(text, 'rw_print(const char *fmt, ...)\n{',
        'rw_print(const char *fmt, ...)\n{\n\tflockfile(stdout);')
    text = replace_once(text, '\tfflush(stdout);\n}', '\tfflush(stdout);\n\tfunlockfile(stdout);\n}')
    text = replace_once(text, 'if ((++rw_times_ & (rw_times_ - 1)) == 0)',
        'unsigned long rw_count_=__atomic_add_fetch(&rw_times_,1,__ATOMIC_RELAXED); \\\n\t\tif ((rw_count_ & (rw_count_ - 1)) == 0)')
    text = text.replace('if (rw_times_ > 1)', 'if (rw_count_ > 1)').replace('"time\\n", rw_times_);', '"time\\n", rw_count_);')
    text = replace_once(text,'if (!rw_said_) {','if (!__atomic_exchange_n(&rw_said_,YES,__ATOMIC_RELAXED)) {')
    text = replace_once(text,'rw_said_ = YES;','/* claimed atomically above */')
    for signature in ('rw_blend_line(unsigned attachment, unsigned format, const struct rwa_color_blend *b)',
                      'rw_blend_result(unsigned enabled_mask, unsigned write_masks)'):
        text=replace_once(text,signature+'\n{',signature+'\n{\n\tREDFIN_MESA_SCOPE;')
    text = replace_once(text, '\t*(void **)&mesa.device_open = dlsym(mesa.handle, "rwa_device_open");',
        '\tconst char *(*pairing)(void)=(const char *(*)(void))dlsym(mesa.handle,"rwa_redfin_contract");\n'
        '\tif (!pairing || strcmp(pairing(),REDFIN_METAL_PAIRING)) {\n'
        '\t\trw_print("driver/compiler source pairing refused\\n");\n'
        '\t\tdlclose(mesa.handle); mesa.handle=NULL; return false;\n\t}\n'
        '\t*(void **)&mesa.device_open = dlsym(mesa.handle, "rwa_device_open");')
    # Atomic calls on the one shared context, including void-returning functions.
    text = re.sub(r'\bmesa\.([a-z_]+)\(', r'RF_MESA(\1,', text)
    # The macro body itself must call the real table, not recurse into itself.
    text = text.replace('RF_MESA(member,__VA_ARGS__); })', 'mesa.member(__VA_ARGS__); })')
    text = replace_once(text, '+ (void)load\n{\n\tensure_spi(self);',
        '+ (void)load\n{\n\tif (redfin_metal_abi_ready()) ensure_spi(self);')
    text = replace_once(text, '- (instancetype)initWithAcceleratorPort:(io_service_t)port\n{\n\tensure_spi([self class]);',
        '- (instancetype)initWithAcceleratorPort:(io_service_t)port\n{\n'
        '\tif (!redfin_metal_abi_ready() || !redfin_metal_hardware_ready()) { [self release]; return nil; }\n'
        '\tensure_spi([self class]);')
    text = replace_once(text, '\t/* The struct Metal reads out of this device by raw pointer,',
        '\tif (_gpu == IO_OBJECT_NULL || _mesa == NULL) { [self release]; return nil; }\n\n'
        '\t/* The struct Metal reads out of this device by raw pointer,')
    # Native Redfin msm rejects pipe0. The compiler already uses MSM_PIPE_3D;
    # the upstream's separate human-readable chip query must use it as well.
    text = replace_once(text, '.pipe = 0, .param = which,', '.pipe = 0x10, .param = which,')
    text = replace_once(text, '@"Adreno 7c+ Gen 3 (chip %#x, Redwood)"',
        '@"Adreno 620 (chip %#x, Redfin)"')
    text = replace_once(text, '@"Adreno (Redwood; the GPU is not started)"',
        '@"Adreno 620 (Redfin; chip query unavailable)"')
    text = replace_once(text, 'if (_status == RW_CB_ERROR) {\n\t\treturn;\n\t}',
        'if (_status == RW_CB_ERROR || _status == RW_CB_COMPLETED) {\n\t\treturn;\n\t}')
    text = replace_once(text, '\t_status = RW_CB_COMPLETED;   /* the fence has been paid, and only now */',
        '\t_status = RW_CB_COMPLETED;   /* the fence has been paid, and only now */\n'
        '\tunsigned draws=0,computes=0;\n'
        '\tfor (RedwoodMetalWork *work in _work) { if (work->render) ++draws; else ++computes; }\n'
        '\tredfin_metal_completed(draws,computes);')
    match = re.search(r'- \(NSUInteger\)featureProfile\n\{.*?\n\}', text, re.S)
    require(match is not None, 'preferred Metal profile getter changed')
    text = text[:match.start()] + ('- (NSUInteger)featureProfile\n{\n'
        '\t/* Lowest native profile admitted by MPS; no arbitrary boot profile. */\n\treturn 1;\n}') + text[match.end():]
    require(text.count('return 256ULL << 20;') == 2, 'preferred Metal allocation bounds changed')
    text = text.replace('return 256ULL << 20;', 'return 128ULL << 20;')
    # Keep native behavior for every function belonging to another device.
    text = replace_once(text, 'static id\nrw_function_argument_encoder(id self, SEL cmd, NSUInteger index)',
        'static IMP redfin_native_argument_encoder,redfin_native_argument_encoder_reflection;\n\n'
        'static id\nrw_function_argument_encoder(id self, SEL cmd, NSUInteger index)')
    before = '''\t\trw_print("-newArgumentEncoderWithBufferIndex: on a function whose device is "
\t\t         "a %s and not ours\\n", class_getName(object_getClass(device)));
\t\treturn nil;'''
    text = replace_once(text, before,
        '\t\treturn ((id (*)(id,SEL,NSUInteger))redfin_native_argument_encoder)(self,cmd,index);')
    text = replace_once(text,
        'rw_function_argument_encoder_reflection(id self, SEL cmd, NSUInteger index, id *reflection)\n{',
        'rw_function_argument_encoder_reflection(id self, SEL cmd, NSUInteger index, id *reflection)\n{\n'
        '\tid device=((id (*)(id,SEL))objc_msgSend)(self,sel_getUid("device"));\n'
        '\tif (![device isKindOfClass:[RedwoodMetalDevice class]])\n'
        '\t\treturn ((id (*)(id,SEL,NSUInteger,id *))redfin_native_argument_encoder_reflection)(self,cmd,index,reflection);')
    text = replace_once(text, '\tinstalled = YES;\n\tclass_replaceMethod(fn,',
        '\tredfin_native_argument_encoder=method_getImplementation(class_getInstanceMethod(fn,sel_getUid("newArgumentEncoderWithBufferIndex:")));\n'
        '\tredfin_native_argument_encoder_reflection=method_getImplementation(class_getInstanceMethod(fn,sel_getUid("newArgumentEncoderWithBufferIndex:reflection:")));\n'
        '\tinstalled = YES;\n\tclass_replaceMethod(fn,')
    return text.replace('/redwood/', '/redfin/').replace('libredwoodair.dylib', 'libredfinair.dylib')


def adapt_drawable(text):
    text = replace_once(text, '#include "redwood_drawable.h"',
        '#include "redwood_drawable.h"\nextern void redfin_metal_lock(void);\nextern void redfin_metal_unlock(void);\n'
        'static int redfin_surface_enter(void){redfin_metal_lock();return 1;}\n'
        'static void redfin_surface_leave(int *p){(void)p;redfin_metal_unlock();}\n'
        '#define REDFIN_SURFACE_SCOPE int locked_ __attribute__((cleanup(redfin_surface_leave)))=redfin_surface_enter(); (void)locked_\n')
    text = replace_once(text, 'static const struct rwd_format rwd_formats[] = {',
        'static const struct rwd_format rwd_formats[] = {\n'
        '\t/* Native kCVPixelFormatType_TwoComponent8; AIR already uses R8G8. */\n'
        '\t{ 30, \'2C08\', 2, 0, "MTLPixelFormatRG8Unorm" },\n'
        '\t{ 31, \'2C08\', 2, 0, "MTLPixelFormatRG8Unorm_sRGB" },')
    for signature in ('rwd_import(void)','rwd_shared_connection(void)'):
        text=replace_once(text,signature+'\n{',signature+'\n{\n\tREDFIN_SURFACE_SCOPE;')
    text = replace_once(text, '\ttexture = import(mesa_device, want, (int)id, surface.offset, surface.rowBytes, why,\n\t    why_size);',
        '\tredfin_metal_lock();\n\ttexture = import(mesa_device, want, (int)id, surface.offset, surface.rowBytes, why,\n'
        '\t    why_size);\n\tredfin_metal_unlock();')
    return text.replace('/redwood/', '/redfin/').replace('libredwoodair.dylib', 'libredfinair.dylib')


def prepare(upstream, out, cache_path, pairing):
    upstream, out = Path(upstream), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    src = upstream / 'userland/src'
    require(bool(re.fullmatch('[0-9a-f]{64}', pairing)), 'Metal/compiler source pairing required')
    with Cache(cache_path) as cache:
        abi = derive(cache)
    (out / 'metal-abi.h').write_text(header(abi, pairing))
    (out / 'redwoodmetal.m').write_text(adapt_driver((src / 'redwoodmetal.m').read_text()))
    (out / 'redwooddrawable.m').write_text(adapt_drawable((src / 'redwooddrawable.m').read_text()))
    shutil.copy2(src / 'redwood_drawable.h', out / 'redwood_drawable.h')
    (out / 'abi.json').write_text(json.dumps(abi, indent=2) + '\n')
    return dict(native=abi, serialized_gallium=True, max_buffer_bytes=128 << 20,
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.iterdir() if p.is_file()})
