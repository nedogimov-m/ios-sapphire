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


def job(enabled=True):
    require(type(enabled) is bool,'Metal startup-check policy must be boolean')
    value=dict(Label='com.redfin.metal-check',ProgramArguments=['/redfin/bin/metal-check'],
        RunAtLoad=True,KeepAlive=False,UserName='mobile',ProcessType='Background',
        StandardOutPath=LOG_PATH,StandardErrorPath=LOG_PATH,
        EnvironmentVariables={'FD_MESA_DEBUG':'gmem','RWA_SOFTWARE':'0'},
        JetsamProperties={'ActiveHardMemoryLimit':512,'InactiveHardMemoryLimit':512})
    if not enabled:value.update(Disabled=True,RunAtLoad=False)
    return value


def patch_launchd_cache(original,startup_checks=True):
    require(isinstance(original,bytes) and original.startswith(b'bplist00') and
            40<=len(original)<=16*1024**2,'bounded native launchd cache required')
    before=plistlib.loads(original);after=copy.deepcopy(before)
    jobs=after.get('LaunchDaemons');require(isinstance(jobs,dict),'native launchd jobs absent')
    found=[(k,v) for k,v in jobs.items() if isinstance(v,dict) and v.get('Label')==job()['Label']]
    previous_raster=copy.deepcopy(job());previous_raster['EnvironmentVariables']['FD_MESA_DEBUG']='sysmem'
    require(not found or found in [[(JOB_PATH,job())],[(JOB_PATH,job(False))],[(JOB_PATH,previous_raster)]],'conflicting Metal checker identity')
    require(JOB_PATH not in jobs or bool(found),'occupied Metal checker path')
    jobs[JOB_PATH]=job(enabled=startup_checks)
    if after==before:return original,dict(changed=False,startup_checks=startup_checks)
    encoded,padding=_encode_same_size(after,len(original),compact=True)
    decoded=plistlib.loads(encoded)
    for value in (before,decoded):value['LaunchDaemons'].pop(JOB_PATH,None)
    require(decoded==before,'Metal checker changed an unrelated native job')
    return encoded,dict(changed=True,padding_bytes=padding,startup_checks=startup_checks)


def inventory(bundle):
    bundle=Path(bundle);proof=json.loads((bundle/'metal-build.json').read_text())
    require(proof.get('success') and proof.get('actual_abi_compatible') and
            proof.get('max_buffer_bytes')==128<<20,'complete actual-ABI Metal bundle required')
    checks=proof.get('startup_checks_enabled',True)
    require(type(checks) is bool,'native Metal startup policy must be boolean')
    result=[]
    for target,record in proof['files'].items():
        require(target.startswith('/') and '..' not in Path(target).parts,'unsafe Metal bundle destination')
        source=bundle/record['source']
        require(bundle.resolve() in source.resolve().parents and source.is_file() and
                not source.is_symlink(),'unsafe Metal bundle source')
        require(hashlib.sha256(source.read_bytes()).hexdigest()==record['sha256'],'Metal bundle artifact changed')
        if target==JOB_PATH:require(plistlib.loads(source.read_bytes())==job(enabled=checks),'Metal bundle startup policy differs')
        result.append((source,target,record['uid'],record['mode'],record['sha256']))
    return result


def prepare_root(root,metadata,bundle):
    from ports.redfin.userland_files import prepare as prepare_files
    root=Path(root).resolve()
    prepare_files(root,metadata,[(source,target,uid,mode,digest,target.endswith('.log'))
        for source,target,uid,mode,digest in inventory(bundle)])
    path=root/'System/Library/xpc/launchd.plist'
    require(not path.is_symlink() and root in path.resolve().parents,'native launchd cache escapes root')
    build=json.loads((Path(bundle)/'metal-build.json').read_text())
    before=path.read_bytes();after,proof=patch_launchd_cache(before,startup_checks=build.get('startup_checks_enabled',True))
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
                     '-newArgumentEncoderWithBufferIndex:reflection:',
                     '-initWithName:type:libraryData:device:', '-functionConstantsDictionary'),
    'MTLFunctionConstantValuesInternal': ('-constantValueWithFunctionConstant:',),
    '_MTLFunctionInternal': ('-initWithName:type:libraryData:functionData:device:',
        '-functionData', '-bitCodeOffset', '-bitcodeType', '-setFunctionConstantSpecializationHash:',
        '-needsFunctionConstantValues', '-pluginData', '-newFunctionWithPluginData:bitcodeType:'),
    '_MTLLibrary': ('-newFunctionWithNameInternal:', '-libraryData', '-device',
        '-newFunctionWithName:constantValues:error:',
        '-newFunctionWithName:constantValues:functionCache:error:',
        '-newFunctionWithName:constantValues:pipelineLibrary:error:',
        '-newFunctionWithName:constantValues:functionCache:specializedName:error:',
        '-newFunctionWithDescriptor:error:', '-newFunctionWithDescriptor:destinationArchive:error:',
        '-newSpecializedFunctionWithDescriptorInternal:destinationArchive:functionCache:error:',
        '-newFunctionWithName:constantValues:completionHandler:',
        '-newFunctionWithName:constantValues:functionCache:specializedName:completionHandler:',
        '-newFunctionWithName:constantValues:pipelineLibrary:completionHandler:',
        '-newFunctionWithDescriptor:completionHandler:',
        '-newFunctionWithDescriptor:destinationArchive:functionCache:completionHandler:'),
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
    value_hash=native_ivars(cache,image,'_MTLFunction').get('_functionConstantSpecializationHash')
    require(value_hash and value_hash['size']==32 and value_hash['types']=='{?="key"[32C]}',
            'unreviewed actual Metal function specialization hash')
    result['ivars'].setdefault('_MTLFunction',{})['_functionConstantSpecializationHash']=value_hash
    return result


def header(abi, pairing):
    rows = ['/* Generated from the installed cache; no upstream instruction addresses. */',
            '#include <stdint.h>', '#define REDFIN_METAL_PAIRING ' + json.dumps(pairing),
            '#define REDFIN_METAL_FUNCTION_HASH_OFFSET '+str(abi['ivars']['_MTLFunction']['_functionConstantSpecializationHash']['offset']),
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

EXECUTION = r'''
/* A native -commit enqueues work; it must not wait for the GPU on the window
 * server's submitting thread. One serial worker preserves Gallium's device
 * ordering across native queues, while the command group's lifetime gives
 * every waiter the same actual completion, including error exits. */
#include <dispatch/dispatch.h>
static pthread_once_t redfin_execution_once=PTHREAD_ONCE_INIT;
static dispatch_queue_t redfin_execution_queue;
static dispatch_semaphore_t redfin_execution_slots;
static void redfin_execution_init(void)
{
    dispatch_queue_attr_t attr=dispatch_queue_attr_make_with_qos_class(
        DISPATCH_QUEUE_SERIAL,QOS_CLASS_USER_INTERACTIVE,0);
    redfin_execution_queue=dispatch_queue_create("com.redfin.metal.commands",attr);
    /* One executing and one queued command. Apply backpressure at commit,
     * while preserving the native queue's requested allocation capacity.
     * Never discard a command or signal a completion before its real fence. */
    redfin_execution_slots=dispatch_semaphore_create(2);
    if (!redfin_execution_queue || !redfin_execution_slots) abort();
}
static void redfin_metal_schedule(dispatch_group_t group,dispatch_block_t work)
{
    /* The caller entered the completion group before publishing Committed.
     * A concurrent waiter must also cover time spent awaiting admission. */
    if (!group || !work || pthread_once(&redfin_execution_once,redfin_execution_init)) abort();
    dispatch_semaphore_wait(redfin_execution_slots,DISPATCH_TIME_FOREVER);
    dispatch_async(redfin_execution_queue,^{
        @try {work();}
        @finally {
            dispatch_semaphore_signal(redfin_execution_slots);
            dispatch_group_leave(group);
        }
    });
}
'''

FENCE_OBSERVATIONS = r'''
/* Completion evidence is emitted only after Gallium's actual fence succeeds.
 * Keep callback/timer activity separate from commands that reached the GPU. */
static pthread_once_t redfin_fence_once=PTHREAD_ONCE_INIT;
static char redfin_fence_boot[17];
static uint64_t redfin_fence_count;
static mach_timebase_info_data_t redfin_fence_timebase;
static void redfin_fence_identity(void)
{
    if (mach_timebase_info(&redfin_fence_timebase)) return;
    char args[1024]={0};size_t bytes=sizeof(args);
    if (sysctlbyname("kern.bootargs",args,&bytes,NULL,0) || !bytes || bytes>sizeof(args)) return;
    const char *nonce=strstr(args,"redfinbootid=0x");
    if (nonce && strlen(nonce+15)>=16) memcpy(redfin_fence_boot,nonce+15,16);
}
static uint64_t redfin_phase_us(uint64_t start,uint64_t end)
{
    uint64_t n=redfin_fence_timebase.numer,d=redfin_fence_timebase.denom;
    if (!n || !d || end<start || end-start>UINT64_MAX/n) return 0;
    return (end-start)*n/d/1000;
}
static void redfin_metal_completed(unsigned draws,unsigned computes,uint64_t queued,
    uint64_t worker,uint64_t acquired,uint64_t finishing,uint64_t finished)
{
    if ((!draws && !computes) || pthread_once(&redfin_fence_once,redfin_fence_identity) || !redfin_fence_boot[0]) return;
    uint64_t count=__atomic_add_fetch(&redfin_fence_count,1,__ATOMIC_RELAXED);
    if (count<=4 || !(count&(count-1)) || !(count%120))
        rw_print("REDFIN METAL FENCE: boot=%s sequence=%llu draws=%u computes=%u actual-finish=1 queue-us=%llu gate-us=%llu encode-us=%llu final-fence-us=%llu total-us=%llu\n",
            redfin_fence_boot,(unsigned long long)count,draws,computes,
            (unsigned long long)redfin_phase_us(queued,worker),
            (unsigned long long)redfin_phase_us(worker,acquired),
            (unsigned long long)redfin_phase_us(acquired,finishing),
            (unsigned long long)redfin_phase_us(finishing,finished),
            (unsigned long long)redfin_phase_us(queued,finished));
}
static void redfin_metal_io_completed(const uint64_t before[4],const uint64_t after[4])
{
    if(!before||!after||!redfin_fence_boot[0])return;
    for(unsigned i=0;i<4;++i)if(after[i]<before[i])return;
    uint64_t count=__atomic_load_n(&redfin_fence_count,__ATOMIC_RELAXED);
    if(count && (count<=4 || !(count&(count-1)) || !(count%120)))
        rw_print("REDFIN METAL IO: boot=%s sequence=%llu actual-finish=1 io-scope=process submit-calls=%llu submit-io-us=%llu allocation-calls=%llu allocation-io-us=%llu\n",
            redfin_fence_boot,(unsigned long long)count,
            (unsigned long long)(after[0]-before[0]),(unsigned long long)((after[1]-before[1])/1000),
            (unsigned long long)(after[2]-before[2]),(unsigned long long)((after[3]-before[3])/1000));
}
'''


def adapt_driver(text):
    text = replace_once(text, '#include "redwood_drawable.h"',
        '#include "redwood_drawable.h"\n#include "metal-abi.h"\n#include "graphics-memory-report.h"\n#include <pthread.h>\n#include <mach/mach_time.h>\n'
        'extern int redfin_metal_abi_ready(void);\nextern int redfin_metal_hardware_ready(void);')
    text = replace_once(text, 'static bool\nmesa_available(void)', LOCKING + EXECUTION + FENCE_OBSERVATIONS + '\nstatic bool\nmesa_available(void)')
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
    text = replace_once(text,'\tint (*finish)(struct rwa_device *, char *, size_t);',
        '\tint (*finish)(struct rwa_device *, char *, size_t);\n'
        '\tint (*commands_begin)(struct rwa_device *, char *, size_t);\n'
        '\tint (*commands_end)(struct rwa_device *, char *, size_t);\n'
        '\tint (*raster_statistics)(struct rwa_device *,uint64_t *,size_t);\n'
        '\tint (*submission_statistics)(struct rwa_device *,uint64_t *,size_t);')
    text = replace_once(text,'\t*(void **)&mesa.finish = dlsym(mesa.handle, "rwa_finish");',
        '\t*(void **)&mesa.finish = dlsym(mesa.handle, "rwa_finish");\n'
        '\t*(void **)&mesa.commands_begin = dlsym(mesa.handle, "rwa_commands_begin");\n'
        '\t*(void **)&mesa.commands_end = dlsym(mesa.handle, "rwa_commands_end");\n'
        '\t*(void **)&mesa.raster_statistics = dlsym(mesa.handle,"rwa_redfin_raster_stats");\n'
        '\t*(void **)&mesa.submission_statistics = dlsym(mesa.handle,"rwa_redfin_submission_stats");')
    text = replace_once(text,'if (mesa.device_open == NULL || mesa.compute_create == NULL || mesa.dispatch == NULL ||',
        'if (mesa.commands_begin == NULL || mesa.commands_end == NULL || mesa.raster_statistics == NULL || mesa.submission_statistics == NULL ||\n'
        '\t    mesa.device_open == NULL || mesa.compute_create == NULL || mesa.dispatch == NULL ||')
    text = replace_once(text,'- (void)commit\n{\n\tchar why[512] = { 0 };',
        '- (void)commit\n{\n\tREDFIN_MESA_SCOPE;\n\tchar why[512] = { 0 };\n'
        '\tif (_status>=RW_CB_COMMITTED) return;\n'
        '\tif (mesa.commands_begin([[_queue device] mesaDevice],why,sizeof(why))) {\n'
        '\t\t[self failWith:why];[self redwoodReturnSlot];[self redwoodDeliverHandlers];return;\n\t}\n\t@try {')
    text = replace_once(text,'done:\n\t/* The queue\'s slot goes back here',
        'done:;\n\t} @finally {\n'
        '\t\tuint64_t redfin_fence_at=mach_absolute_time();\n'
        '\t\tif (mesa.commands_end([[_queue device] mesaDevice],why,sizeof(why))) [self failWith:why];\n'
        '\t\telse if (_status!=RW_CB_ERROR) {\n'
        '\t\t\t_status=RW_CB_COMPLETED;\n'
        '\t\t\tunsigned draws=0,computes=0;\n'
        '\t\t\tfor (RedwoodMetalWork *work in _work) {if(work->render) ++draws;else ++computes;}\n'
        '\t\t\tredfin_metal_completed(draws,computes,_redfinQueuedTicks,redfin_worker_at,redfin_acquired_at,redfin_fence_at,mach_absolute_time());\n'
        '\t\t\tif(redfin_io_start_valid && (draws||computes)) {\n'
        '\t\t\t\tuint64_t redfin_io_end[4]={0};\n'
        '\t\t\t\tif(!mesa.submission_statistics([[_queue device] mesaDevice],redfin_io_end,4))\n'
        '\t\t\t\t\tredfin_metal_io_completed(redfin_io_start,redfin_io_end);\n\t\t\t}\n'
        '\t\t}\n\t}\n'
        '\t/* The queue\'s slot goes back here')
    # retainedReferences:YES applies during encoding as well as execution.
    # An autoreleased set*Bytes buffer must survive its encoder's pool.
    text = replace_once(text,'NSMutableArray *_work;','NSMutableArray *_work;\n\tNSMutableArray *_redfinResources;')
    text = replace_once(text,'\t_work = [[NSMutableArray alloc] init];',
        '\t_work = [[NSMutableArray alloc] init];\n\t_redfinResources = [[NSMutableArray alloc] init];')
    text = replace_once(text,'\t[_work release];','\t[_work release];\n\t[_redfinResources release];')
    text = replace_once(text,'- (void)recordWork:(RedwoodMetalWork *)work\n{',
        '- (void)redfinRetainResource:(id)resource\n{\n\tif (resource) [_redfinResources addObject:resource];\n}\n\n'
        '- (void)recordWork:(RedwoodMetalWork *)work\n{')
    require(text.count('_pipeline = state;')==2,'preferred compute/render pipeline binding changed')
    text=text.replace('_pipeline = state;','_pipeline = state; [_commandBuffer redfinRetainResource:state];')
    for slot,argument in [('buffers','buffer'),('textures','texture'),('samplers','sampler'),
                          ('vertexBuffers','buffer'),('fragmentBuffers','buffer'),
                          ('fragmentTextures','texture'),('fragmentSamplers','sampler')]:
        line='\t_'+slot+'[index] = '+argument+';'
        text=replace_once(text,line,line+'\n\t[_commandBuffer redfinRetainResource:'+argument+'];')
    for line,argument in [('\t_depthStencilState = state;','state'),
                          ('\t\t_color[i] = texture;','texture'),
                          ('\t\t_depth = ztex != nil ? ztex : stex;','_depth'),
                          ('\twork->indexBuffer = indexBuffer;','indexBuffer')]:
        text=replace_once(text,line,line+'\n\t[_commandBuffer redfinRetainResource:'+argument+'];')
    text=replace_once(text,'\twork->clearsStencil = _clearsStencil;',
        '\twork->clearsStencil = _clearsStencil;\n'
        '\t/* Load actions belong to the pass, once before its first draw. */\n'
        '\t_clears = _clearsDepth = _clearsStencil = NO;')
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
        '\tif (_gpu == IO_OBJECT_NULL || _mesa == NULL || strcmp(RF_MESA(device_name,_mesa),"FD620")) { [self release]; return nil; }\n\n'
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
    text = adapt_execution(text)
    from ports.redfin.metal_raster_userland import adapt as adapt_raster
    text = adapt_raster(text)
    from ports.redfin.metal_resource_userland import adapt as adapt_resources
    text = adapt_resources(text)
    from ports.redfin.metal_blit_userland import adapt as adapt_blit
    text = adapt_blit(text)
    from ports.redfin.metal_buffer_userland import adapt as adapt_buffers
    text = adapt_buffers(text)
    from ports.redfin.metal_completion_userland import adapt as adapt_completion
    text = adapt_completion(text)
    from ports.redfin.metal_buffer_texture_userland import adapt as adapt_buffer_textures
    text = adapt_buffer_textures(text)
    from ports.redfin.metal_function_constants_userland import adapt as adapt_constants
    text = adapt_constants(text)
    # Bounded own-task observations bracket real system pipeline compilation.
    # The stock daemon has no memorystatus setter entitlement; its existing
    # kernel admission already proves a fatal 512 MiB limit in V30.
    point='\tstruct rwa_render_info info = { 0 };'
    text=replace_once(text,point,point+'''
    static unsigned redfin_pipeline_ordinal;
    unsigned redfin_pipeline_number=__atomic_add_fetch(&redfin_pipeline_ordinal,1,__ATOMIC_RELAXED);
    BOOL redfin_memory_sample=redfin_pipeline_number<=4 ||
        (redfin_pipeline_number<=1024 && !(redfin_pipeline_number&(redfin_pipeline_number-1)));
    if(redfin_memory_sample)redfin_graphics_memory_report("pipeline-before",redfin_pipeline_number);
    (void)pthread_once(&redfin_fence_once,redfin_fence_identity);
    uint64_t redfin_pipeline_requested=mach_absolute_time();
''')
    point='\tif (render == NULL) {'
    text=replace_once(text,point,
        '''    uint64_t redfin_pipeline_call_us=redfin_phase_us(redfin_pipeline_requested,mach_absolute_time());
    static unsigned redfin_slow_pipeline_reports;
    BOOL redfin_pipeline_report=redfin_memory_sample || (redfin_pipeline_call_us>=20000 &&
        __atomic_fetch_add(&redfin_slow_pipeline_reports,1,__ATOMIC_RELAXED)<16);
    if(redfin_pipeline_report && redfin_fence_boot[0])
        rw_print("REDFIN METAL PIPELINE TIME: boot=%s ordinal=%u call-us=%llu success=%u vertex=%.80s fragment=%.80s\\n",
            redfin_fence_boot,redfin_pipeline_number,(unsigned long long)redfin_pipeline_call_us,
            render!=NULL,vertex?[[vertex name] UTF8String]:"generated",[[fragment name] UTF8String]);
    if(redfin_memory_sample)redfin_graphics_memory_report("pipeline-after",redfin_pipeline_number);
'''+point)
    text += '''
/* Private readonly evidence for the paired native pixel checker. */
int redfin_metal_raster_statistics(id device,uint64_t *counts,size_t words)
{
    REDFIN_MESA_SCOPE;
    if (!counts || words!=2 || ![device isKindOfClass:[RedwoodMetalDevice class]] ||
        !mesa.raster_statistics) return -1;
    return mesa.raster_statistics([device mesaDevice],counts,words);
}
'''
    return text.replace('/redwood/', '/redfin/').replace('libredwoodair.dylib', 'libredfinair.dylib')


def adapt_execution(text):
    """Keep native asynchronous submission, completion and callback lifetimes."""
    # Native queues can be created or reconfigured while the worker completes
    # another buffer. Resolve the ABI-guarded ivars without a racy looked flag.
    helpers={
        'static dispatch_semaphore_t\nredwood_queue_semaphore(id queue)': '''
    Class base=objc_getClass("_MTLCommandQueue");
    Ivar ivar=base ? class_getInstanceVariable(base,"_commandBufferSemaphore") : NULL;
    return ivar ? (dispatch_semaphore_t)object_getIvar(queue,ivar) : nil;
''',
        'static Ivar\nredwood_completion_ivar(void)': '''
    Class base=objc_getClass("_MTLCommandQueue");
    return base ? class_getInstanceVariable(base,"_completionQueue") : NULL;
''',
        'static void\nredwood_clear_semaphore_debt(id commandBuffer)': '''
    Class base=objc_getClass("_MTLCommandBuffer");
    Ivar ivar=base ? class_getInstanceVariable(base,"_needsCommandBufferSemaphoreSignal") : NULL;
    if (ivar) *(unsigned char *)((char *)commandBuffer+ivar_getOffset(ivar))=0;
''',
    }
    for signature,body in helpers.items():
        start=text.index(signature+'\n{');end=text.index('\n}\n',start)+3
        text=text[:start]+signature+'\n{'+body+'}\n'+text[end:]
    text=replace_once(text,'\tNSUInteger _outstanding;', '\t_Atomic(NSUInteger) _outstanding;')
    text=replace_once(text,'\tNSUInteger _made, _returned;', '\t_Atomic(NSUInteger) _made, _returned;')
    text=replace_once(text,'\tNSUInteger _status;',
        '\t_Atomic(NSUInteger) _status;\n\t_Atomic(BOOL) _redfinFinalized;\n\tdispatch_group_t _redfinExecution;\n\tuint64_t _redfinQueuedTicks;')
    text=replace_once(text,'\t[queue redwoodTookSlot];',
        '\t[queue redwoodTookSlot];\n\t_redfinExecution=dispatch_group_create();\n'
        '\tif (!_redfinExecution) {[self release];return nil;}')
    text=replace_once(text,'\t[_redfinResources release];',
        '\t[_redfinResources release];\n\tif (_redfinExecution) dispatch_release(_redfinExecution);')
    text=replace_once(text,'\tif (_status>=RW_CB_COMMITTED) return;\n','')
    text=replace_once(text,'- (void)commit\n{\n\tREDFIN_MESA_SCOPE;',
        '- (void)commit\n{\n\t@synchronized(self) {\n'
        '\t\tif (_status>=RW_CB_COMMITTED) return;\n'
        '\t\tdispatch_group_enter(_redfinExecution);\n\t\t_status=RW_CB_COMMITTED;\n'
        '\t\t_redfinQueuedTicks=mach_absolute_time();\n'
        '\t\tredfin_metal_schedule(_redfinExecution,^{\n'
        '\t\t\t@autoreleasepool {[self redfinExecute];}\n\t\t});\n\t}\n}\n\n'
        '- (void)redfinExecute\n{\n\tuint64_t redfin_worker_at=mach_absolute_time();\n'
        '\tREDFIN_MESA_SCOPE;\n\tuint64_t redfin_acquired_at=mach_absolute_time();\n'
        '\tuint64_t redfin_io_start[4]={0};\n'
        '\tBOOL redfin_io_start_valid=RF_MESA(submission_statistics,[[_queue device] mesaDevice],redfin_io_start,4)==0;')
    text=replace_once(text,'done:;\n\t} @finally {',
        'done:;\n\t} @catch (NSException *exception) {\n'
        '\t\t[self failWith:exception.reason.UTF8String ?: "Metal execution raised an exception"];\n'
        '\t} @finally {')
    text=replace_once(text,'[self failWith:why];[self redwoodReturnSlot];[self redwoodDeliverHandlers];return;',
        '[self failWith:why];_redfinFinalized=YES;[self redwoodReturnSlot];[self redwoodDeliverHandlers];return;')
    text=replace_once(text,'\t/* The queue\'s slot goes back here',
        '\t_redfinFinalized=YES;\n\t/* The queue\'s slot goes back here')
    start=text.index('- (void)waitUntilCompleted\n{');end=text.index('\n- (void)waitUntilScheduled { }',start)
    text=text[:start]+'''- (void)waitUntilCompleted
{
    NSUInteger status=_status;
    if (_redfinFinalized || status<RW_CB_COMMITTED) return;
    /* The executing block leaves this group only after its real final GPU
     * fence and every refusal/exception cleanup path. No caller may fence a
     * different buffer on the same Gallium context on behalf of this one. */
    dispatch_group_wait(_redfinExecution,DISPATCH_TIME_FOREVER);
}
'''+text[end:]
    text=replace_once(text,'- (void)waitUntilScheduled { }',
        '- (void)waitUntilScheduled {if (_status<RW_CB_SCHEDULED && _status>=RW_CB_COMMITTED) [self waitUntilCompleted];}')
    # Raster work can still be only Gallium commands at the end of the
    # encoding loop. Publishing Scheduled there lets a display consumer
    # acquire the kernel GPU queue before that work has even been submitted.
    # The native submit is synchronous; publish only after its real finish
    # and every IOSurface resolve, immediately before Completed.
    text=replace_once(text,'\t_status = RW_CB_SCHEDULED;   /* submitted; the fence below is what makes it completed */\n','')
    text=replace_once(text,'\t\t\t_status=RW_CB_COMPLETED;',
        '\t\t\t_status=RW_CB_SCHEDULED; /* actual submit/fence/IOSurface resolve have succeeded */\n'
        '\t\t\t_status=RW_CB_COMPLETED;')
    # A late completed handler must still wait while work is only scheduled.
    start=text.index('- (void)addCompletedHandler:');end=text.index('\n}\n',start)+3
    method=text[start:end]
    method=replace_once(method,'if (_status >= RW_CB_SCHEDULED)', 'if (_redfinFinalized)')
    text=text[:start]+method+text[end:]
    # Default callbacks run off the shared GPU executor as well: a callback
    # may submit a different command buffer and wait for it without blocking
    # the worker that must execute that next buffer.
    text=replace_once(text,'\thandler(self);\n}',
        '\tdispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{handler(self);});\n}')
    text=replace_once(text,'\tdispatch_queue_t queue = [_queue redwoodCompletionQueue];',
        '\tdispatch_queue_t queue=nil;\n\t@synchronized(_queue) {\n'
        '\t\tqueue=[_queue redwoodCompletionQueue];\n\t\tif (queue) dispatch_retain(queue);\n\t}')
    text=replace_once(text,'\t\tdispatch_async(queue, ^{ handler(self); });',
        '\t\tdispatch_async(queue, ^{ handler(self); });\n\t\tdispatch_release(queue);')
    for signature in ['- (void)addScheduledHandler:','- (void)addCompletedHandler:',
                      '- (void)redwoodDeliverHandlers\n','- (void)failWith:',
                      '- (void)setCompletionQueue:']:
        start=text.index(signature);end=text.index('\n}\n',start)+3
        method=text[start:end];brace=method.index('{')
        method=method[:brace+1]+'\n\t@synchronized(self) {'+method[brace+1:-2]+'\t}\n}\n'
        text=text[:start]+method+text[end:]
    text=replace_once(text,'- (NSError *)error { return _error; }',
        '- (NSError *)error {@synchronized(self) {return [[_error retain] autorelease];}}')
    text=replace_once(text,'- (void)failWith:(const char *)reason\n{\n\t@synchronized(self) {',
        '- (void)failWith:(const char *)reason\n{\n\t@synchronized(self) {\n\t[_error release];')
    # The dispatch refusal also owns the same error-property synchronization.
    needle='''\t\t\t_error = [[NSError errorWithDomain:@"RedwoodMetal" code:2
\t\t\t\t\t\t  userInfo:@{ NSLocalizedDescriptionKey:
\t\t\t\t\t\t\t      [NSString stringWithUTF8String:why] }]
\t\t\t\t     retain];'''
    text=replace_once(text,needle,'\t\t\t@synchronized(self) {\n'+needle+'\n\t\t\t}')
    return text


def adapt_drawable(text):
    # Accept the actual native row pitch. Paired AIR converts unaligned
    # IOSurfaces through bounded GPU buffer copies into genuine textures.
    first=text.index('\t/*\n\t * a6xx\'s minimum pitchalign is 6')
    last=text.index('\tuint64_t least;',first)
    text=text[:first]+text[last:]
    first=text.index('\tif (surface->rowBytes % align != 0) {')
    last=text.index('\n\tif (surface->size <',first)
    text=text[:first]+text[last:]
    text = replace_once(text, '#include "redwood_drawable.h"',
        '#include "redwood_drawable.h"\nextern void redfin_metal_lock(void);\nextern void redfin_metal_unlock(void);\n'
        'static int redfin_surface_enter(void){redfin_metal_lock();return 1;}\n'
        'static void redfin_surface_leave(int *p){(void)p;redfin_metal_unlock();}\n'
        '#define REDFIN_SURFACE_SCOPE int locked_ __attribute__((cleanup(redfin_surface_leave)))=redfin_surface_enter(); (void)locked_\n')
    text = replace_once(text, 'static const struct rwd_format rwd_formats[] = {',
        'static const struct rwd_format rwd_formats[] = {\n'
        '\t{ 1, \'A008\', 1, 0, "MTLPixelFormatA8Unorm" },\n'
        '\t/* Native kCVPixelFormatType_TwoComponent8; AIR already uses R8G8. */\n'
        '\t{ 30, \'2C08\', 2, 0, "MTLPixelFormatRG8Unorm" },\n'
        '\t{ 31, \'2C08\', 2, 0, "MTLPixelFormatRG8Unorm_sRGB" },')
    text = replace_once(text,'if (surface.pixelFormat != fourcc) {',
        '/* Native QuartzCore uses LA08 for its two-channel glyph masks.\n'
        '\t * Metal reads the same two bytes as R/G; retain the native bits. */\n'
        '\tint rg8_alias=(want->pixel_format==30 || want->pixel_format==31) &&\n'
        '\t    (surface.pixelFormat==\'LA08\' || surface.pixelFormat==\'2C08\') && bytes_per_pixel==2;\n'
        '\tif (surface.pixelFormat != fourcc && !rg8_alias) {')
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
    shutil.copy2(Path(__file__).with_name('metal-raster.h'),out/'redfin_metal_raster.h')
    shutil.copy2(Path(__file__).with_name('metal-blit.h'),out/'redfin_metal_blit.h')
    shutil.copy2(Path(__file__).with_name('metal-buffer-import.h'),out/'redfin_metal_buffer_import.h')
    shutil.copy2(Path(__file__).with_name('metal-function-constants.h'),out/'redfin_metal_function_constants.h')
    shutil.copy2(Path(__file__).with_name('iosurface-abi.h'),out/'iosurface-abi.h')
    (out / 'redwoodmetal.m').write_text(adapt_driver((src / 'redwoodmetal.m').read_text()))
    (out / 'redwooddrawable.m').write_text(adapt_drawable((src / 'redwooddrawable.m').read_text()))
    shutil.copy2(src / 'redwood_drawable.h', out / 'redwood_drawable.h')
    (out / 'abi.json').write_text(json.dumps(abi, indent=2) + '\n')
    return dict(native=abi, serialized_gallium=True, max_buffer_bytes=128 << 20,
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.iterdir() if p.is_file()})
