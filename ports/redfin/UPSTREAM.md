# HackiOS upstream review — 2026-10-22

## Defined packed state before executable resource analysis — 2026-10-25

Preferred graphics pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772
and kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. Review Mesa25.0.7's
nir_lower_undef_to_zero and the actual CoreAnimation initializer/optimized NIR.
V29 false attachment flags are stored correctly, but their byte loads remain
hidden behind masks of undefined neighboring bytes. Conservative early binding
analysis therefore retains disabled attachment1/2 while the original flags
say framebuffer_fetch1/has_attachment1=0/has_attachment2=0.

Use the existing legal undefined-value lowering after private-state promotion,
then fold the fully defined bits and analyze resources. Explicit constants and
NaN payloads remain exact; missing-binding and original-page checks stay strict.
All19captured actual parameter sets compile with no phantom attachment1/2
requirement; one case now takes11A620instructions. Native bool false/true/Bool3
snapshots and adjacent defined bytes in an undefined word extend the combined
hardware contract. Device correctness/FPS still need the next integrated run.

## Executable pipeline resources without changing declaration ABI — 2026-10-25

Preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 runtime validates
all declared resources at every draw. V28 proves this is too strict after real
specialization: CoreAnimation leaves its removed configuration buffer0 unbound,
but the runtime rejects the otherwise compiled draw. Review compute/render
factories, binding/count/slot checks, argument-buffer reflection and vertex fetch
construction; kernel remains8e61187098f2c26c5daee8f9f72b6416aa64b9ab.

Restrict requirements only on pipeline-owned metadata after NIR specialization.
Preserve assigned API/argument-buffer indices and retain full independent layout
queries. Trace finite descriptor choices conservatively, retain unknown dynamic
bindings, preserve all live buffer/image/atomic accesses, and rebuild NIR resource
counts and ordering groups. Match active vertex-input declarations, metadata and
dense fetch locations; never replace a live missing attribute with a quad value.
Resolve constant texture offsets in slot validation and all possible shadow sampler
slots. This follows actual executable use without weakening missing-binding checks.

Fresh native build/actual-cache ABI/signatures,34host cases,4NIR modules and27A620
compiles pass, including19actual V28 constant sets. An enhanced device contract
checks inactive high declarations, enabled missing-binding refusal and real enabled
high-slot pixels/guards. Bounded bind/no-copy diagnostics retain original ownership
and zero-offset/page checks. Device GUI/pixel results remain pending this block.

## Typed private resources and actual system specialization — 2026-10-25

Review preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 AIR's pointer,
global-planning, module-call and Gallium-finalization paths; kernel pin stays
8e61187098f2c26c5daee8f9f72b6416aa64b9ab. Actual20H392 CoreAnimation stores,
selects and reads sampler references and passes them to module helpers. Its
stores are live. The earlier corpus assumption that no pointer is stored is
insufficient once actual native function constants enable this shader.

Adapt opaque sampler/read-view references to compiler-owned descriptor indices,
carried by real private memory, phis and NIR parameters. A symbolic null never
samples an invented descriptor; guard the actual resource operation after CFG
structuring and inlining. Keep raw device-address stores and image-reference
cells unsupported explicitly. Helper calls rebuild constant offsets and pass
all dynamic SSA components instead of using definitions from another function.
Initialize real global data (including sampler wrappers and exact NaN/padding/
aggregate layouts), then use Mesa25.0.7's existing nir_lower_scratch_to_var after
inlining so constructors and private state can fold together. Numeric read-only
globals use the existing constant-data path. Dynamic vector insertion uses
Mesa's ordinary vector operation. Point-coordinate inputs retain the system
variable that the fd6 consumer can lower to its point-coordinate varying.

Fresh native compilation/actual-cache ABI/signatures and34host cases pass.
An independent host copy validates4NIR modules and compiles7variants to actual
A620 instructions without booting the phone. The host-only standalone compiler
owns the GLSL type cache and initializes driver UBO indices like the native
factory; none of those harness fixes changes the production driver. An authored
32-round contract is ready for real device pixel/guard checks. Correct system
composition and sustained FPS still require native evidence. App-launch jobs
remain disabled; actual parameter snapshots are bounded and kept in private logs.

## Native Metal function constants and AIR specialization — 2026-10-25

V26 exposed a concrete native-object error before GPU specialization ran:
_MTLFunction is an abstract base and has no bitCodeOffset. Review the actual
_MTLFunctionInternal constructor/clone/dealloc: its opaque function-data record
also contains owning plugin/archive/input references, so direct raw-struct copy
or base-class allocation is insufficient. Use its native
newFunctionWithPluginData:bitcodeType: factory with the original type/data,
then the reviewed native hash setter. The result is a fresh concrete object;
our same-size/no-ivar subclass marks required-value validation complete. Serialize
library metadata access for asynchronous callers. ABI checks now bind these
actual concrete-class selectors as well. No C++ ownership layout is reimplemented.

Preferred graphics pins remain userland906425b7/kernel8e611870. Reviewing the
actual20H392 Metal cache confirms _MTLDevice.compiler returns nil. Preferred
AIR consequently invents zero-valued function constants for its harness; that
is unsuitable for a Metal pipeline whose caller supplied real values. The
installed CoreAnimation uber-shader uses dozens of these parameters, including
packed uchar3 combiners, framebuffer access and texture/dither configuration.
This code evidence does not yet establish which parameter causes the GUI damage.

Adapt the actual _MTLLibrary synchronous/asynchronous/cache/descriptor factories
for Redfin's device only, forwarding original IMPs for other devices. Use the
native constant-value lookup/metadata and the concrete native clone factory;
retain immutable per-function values and distinguish specializations
in its actual32-byte native hash. Preserve original AIR entry names; a requested
specialized alias is a label. Compiler-only descriptor options remain explicit
refusals. No private C++ constant-storage layout is copied or guessed.

Paired native compiler/argument-layout entry points consume explicit value sets.
Preserve "absent" independently from a supplied zero for is_function_constant_defined;
undefined loads may hold zero bits but never acquire a defined predicate. Handle
four tightly packed scalar components up to256bits, including float4 and uchar3,
instead of the old64-bit-only vector limit. Preserve legacy AIR exports/harness
defaults separately. Required-value validation happens before a function is returned.
Host ownership/bounds/value tests plus native required-refusal/hash/immutable
compute/argument-buffer/async/descriptor and separate vertex/fragment pixel probes
cover the complete block. Correct system composition still requires observation.

## Fresh upstream tips reviewed without changing graphics pins — 2026-10-25

Fetched/read userland tipa79ff0772a3454fd1ef127e181e5b3bce6c9ce18 and kernel
tipd82c64a3a31cd27a0a0afbf6e213e467e44b1b4c. Relative to the frozen reviewed
pins, the entire preferred GPU/Metal/AIR code is unchanged. Userland adds
thermald/thermal_probe and boot-guard bootok work (fcc3214/a79ff07); its real
kernel pressure -> Darwin notification/state model matches the existing Redfin
adaptation and remains relevant to later thermal validation. The kernel diff
only checks7-Zip>=23 and fixes QEMU RAMFB's2048-row mode; neither replaces the
real Redfin panel geometry or temporary phone boot path. Keep reproducible
graphics pins906425b7/8e611870 for the current already built combined run.

## Shared original-page cache contract and post-logo evidence — 2026-10-25

Preferred pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. V24 proves successful native
parent views and the first correct A8 sample, followed by a stale immediate
second sample. The actual completed compositor target already contains the
checkerboard, before Redfin's native display scaling/packing.

Review the existing fd_bo_map -> redwood_drm_map -> clientMemoryForType route:
it establishes a real mapping with the surface's own cache type, marks CPU
writers and bypasses the seed/4ms skip on native submits. Imported no-copy
buffers otherwise keep only the original caller pointer and miss that contract.
Retain the BO's genuine CPU map for those original pages, including import
failure cleanup and normal BO unmap lifetime; never add a copy, forced sleep,
or assume elapsed4ms makes CPU writes visible. Probe both observed640/pitch640
and549/pitch576 layouts with four immediate fresh CPU seeds and exact guards.

Reserve32auxiliary images for post-logo draws30..512 and16for actual FINAL
targets; log later bounded draw metadata without forcing drains after image
budget exhaustion. INPUTA observations explicitly show actual A8 alpha as
grayscale, while the other roles preserve RGB. These diagnostic maps still
change timing and cannot establish ordinary rendering FPS.

## Native BO views, actual A8 semantics and completed-frame evidence — 2026-10-25

Preferred pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. V23's real CoreAnimation
requests include A8Unorm640x358/offset64/pitch640. AIR already maps Metal1 to
PIPE_FORMAT_A8_UNORM; Mesa25.0.7 fdl6 has a native A8 format, including alpha
swizzle. Add the missing frontend mapping and a native shader probe checking
alpha plus zero RGB, two fresh CPU seeds, guards and lifetime for that exact case.

An ordinary Metal buffer may be a heap-suballocated BO whose CPU address is
not a VM-page boundary. Drop that incidental restriction by creating the texture
over the actual parent's native fd_bo, retaining its real suballocation and
following fd_resource_from_handle's validated LINEAR layout/ownership setup.
Check the logical parent span and actual resource extent before alias creation;
never extend it to extra BO padding. Metadata/shape validation does not allocate
a throwaway texture. No extra wrapped surface or CPU pixel copy is needed for
buffer views; their public buffer/offset/pitch and ownership remain genuine.

Unaligned layouts retain the actual parent pipe_resource and use the same native
GPU row converter in both directions. Its common byte/word copy now preserves
the exact pixel span, including widths not divisible by4. Shared direct views
invalidate native sampler state once per command for possible fresh CPU writes;
immutable repeated reads add no raster fence. The independent external-memory
probe now identifies its precise failing stage instead of returning an opaque0.

Capture at most12auxiliary per-draw images, then preserve ordinary batching.
Reserve36images for actual full-screen IOSurface targets at command end, after
the real final fence and every resolve. Record the command/draw/surface and
capture a distinct FINAL role while its command still retains the texture.
This distinguishes a completed compositor output from an intermediate pass and
the later physical-panel capture. Optional maps still alter scheduling latency;
an observer-disabled run remains required for ordinary rendering/FPS conclusions.

## Real parent-buffer textures and ordered alias visibility — 2026-10-25

Preferred pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. V22 proves original-page
no-copy buffers and exposes the next actual CoreAnimation call: MTLBuffer's
newTextureWithDescriptor:offset:bytesPerRow:. Re-read its upstream nil stub,
native import/format mapping and Redfin's actual SweetSurface layout/wrapDelta.

Create an actual Shared single-level2D colour view over the parent's prepared
pages, with the requested offset/row layout and logical bounds. Retain/return
the real parent, offset and pitch; retain its device and native surface. Track
the parent with every command using the view, propagate known alias queries
and release the view before its parent/deallocator. Unsupported descriptor kinds
fail explicitly. No copied texture is presented as an alias.

Native parent/view bookkeeping resolves dirty converted views before raw buffer
or peer-view reads, invalidates converted snapshots after parent writes and
preserves ordered render, compute, vertex/index and blit accesses. Only actual
pending writes force an extra drain; immutable view reads keep normal batching.
Offsets not64-byte aligned and wider-format pitch constraints use the genuine
bounded GPU row converter. Reject overlapping copied rows against an independent
byte-ownership model, allowing disjoint columns of aliased textures.

Native probes cover two peer views over one parent, texture writes visible to a
subsequent raw-buffer copy, raw writes visible back through that same texture in
one command, exact outside/row guards, ordinary and external parents, nonzero
unaligned offsets/pitches and retaining the parent until both views leave.
The observer reserves most of its48image budget for full-screen output0 through
512draws/1024readback attempts; at most12auxiliary images prevent small icon/blur
passes consuming all captures before the corrupt lock screen. These diagnostic
drains still cannot establish ordinary FPS or exclude timing-sensitive bugs.

## Real external pages, complete dword tails and asynchronous resource readiness — 2026-10-25

Preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and kernel
8e61187098f2c26c5daee8f9f72b6416aa64b9ab remain reviewed pins. V21 confirms
two genuine GPU blit roundtrips, but not correct system rendering. Its mip
download exposes the final partial dword: Mesa25.0.7 fd6_ssbo_descriptor uses
R32_UINT and fdl6_buffer_view_init floors bytes/4. Allocate actual dword padding
in native Metal buffers and include only that real tail in SSBO bindings;
preserve the public length and every logical transfer bound. Narrow stores
still use the upstream subdword-atomic lowering and preserve neighboring bytes.

Re-reviewed upstream Metal resources' isComplete/waitUntilComplete stubs: their
comments depend on synchronous commit, while Redfin's adapted commit is now
asynchronous. A native per-resource GCD group now enters once per submitted
command and leaves after the actual final fence/resolve or refused-command
cleanup. Deduplicate each command's references and cover overlapping users,
waiters and early errors. This corrects a real contract; whether early resource
reuse explains the checkerboard still needs native evidence.

Re-reviewed preferred MiniIOSurface external memory and the actual Redfin
SweetSurface IOSurfaceAddress/prepare/complete/wrapDelta path. Redfin's existing
GPU import already retains that prepared descriptor and maps its real pages.
Implement no-copy Metal buffers through that path, retaining the actual surface,
original CPU pointer, caller deallocator and device. Require real zero-offset
native backing, validate page/length/options, preserve cache-mode declarations,
and release GPU references/pins before the caller's deallocator. Do not substitute
a CPU copy. Native probes exercise GPU reads/writes of those original cached
pages, outside guards and releasing the caller's object before commit.

Broaden explicitly enabled compositor capture through256real draws/48images/
512readback attempts. Read private tiled textures through actual A6xx blits into
genuine linear staging, then map the correctly typed raw alias. Reject native
refusals; never enter a CPU pixel-transfer fallback. Deduplicate equal images
and record sampled-black metadata without exhausting the image budget on blank
boot frames. Diagnostic drains/readbacks still change timing and cannot prove
ordinary FPS; the default launch policy keeps this observer disabled.

## Actual ordered Metal blits and raw-alias transfer metadata — 2026-10-25

Preferred pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. Re-reviewed redwoodmetal.m's
unserved blit encoder, retained command work and genuine _MTLCommandEncoder
init/endEncoding lifetime. V20 records actual CoreAnimation blit calls. Add a
paired152-byte request ABI, retained ordered work and a real native encoder.
Encoding never copies pixels or reports an unexecuted request complete; errors
are delivered by the ordinary command-buffer completion/slot-cleanup path.

Review Mesa25.0.7 FD6 clear_buffer/blit, raw aliases, NIR subword SSBO stores and
transfer-helper format selection. One-byte FD6 fills avoid its alignment
fallback. Copies use bounded native NIR byte/word rows and direct A6xx texture
blits; buffer/texture transfers cross an actual aligned LINEAR staging texture.
No generic Gallium CPU transfer fallback is used. Mipmaps use real GPU linear
filtering. Bounds/device/overlap/format checks precede narrowing and GPU access;
unserved advanced operations become actual command errors. Nonmultisample,
uncompressed colour resources are supported; depth/compressed/3D mip generation
and advanced fences/counters/indirect commands remain explicitly unsupported.

V20's diagnostic-only CPU map reaches a bogus depth conversion because the
raw PIPE_BUFFER constructor left internal_format at NONE although the external
format is R8_UINT. Initialize the actual native internal format before layout
setup. A regression executes that constructor and Mesa's real transfer-selection
function; the old missing initializer must reproduce the conversion decision.
Offscreen native checks exercise byte fills/copies/guards, two queued real
buffer/texture/IOSurface roundtrips and mip levels, including source preservation
and command failure/recovery. Hardware correctness and actual system rendering
must still be established by the combined capture; Phone/Photos stay untouched.

## Publish native Scheduled only after genuine submission — 2026-10-25

Preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and unchanged kernel
8e61187098f2c26c5daee8f9f72b6416aa64b9ab remain reviewed pins. Re-read the native
command-buffer status, scheduling waiters and Metal/AIR deferred raster scope.
The adapted async loop inherited Scheduled immediately after encoding, while
commands_end had not yet submitted its deferred draws. A consumer observing
Scheduled could therefore reach the independent kernel display queue first.
Publish that status only after actual native submit/fence/IOSurface resolve
success, before Completed; failure retains the real Error. This is conservative
scheduling publication on the synchronous native submit backend, not a fake GPU
completion. Actual adapted ObjC executor/commit/wait/error code is exercised
against a blocked end fence and real GCD waiters. Native graphical effect remains
to be checked independently, including after disabling diagnostic drains.

## Native surface metadata and bounded compositor evidence — 2026-10-25

Preferred pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. Re-reviewed native Metal
IOSurface import/object lifetime and the remaining explicitly unserved entry
points. Imported texture wrappers now retain and return their actual IOSurface
and plane; ordinary owned textures still report no IOSurface. Unserved blit,
view, event/fence and external-buffer entry points retain native failure values
and emit bounded first-use evidence. No unsupported operation is called complete.

The actual4512-byte probe's pixels showed no mismatch, but its later padding/
tail check failed. Mesa25.0.7 imports declare slice.size0 as actual stride*rows;
extra BO allocation bytes are not an enlarged borrowed render slice. Bound
shared linear GMEM footprint by that declared slice as well as the actual BO.
Owned native padded textures retain their real backing. Guard checks now log
the exact failed source/destination/offset. This remains real GPU sysmem routing.

An explicit window-server job option enables at most32real-draw observations
and48private linear-BO thumbnails, matched to the actual boot nonce and CRC.
Only genuinely completed work is mapped. Inputs, outputs, stages, source surface
IDs, stream strides and bounded uniform/vertex words are recorded. Nonlinear
images are skipped; no fabricated pixels are substituted. Extra real fences and
CPU diagnostic readback change timing: this capture cannot establish normal FPS
or exclude a timing-sensitive bug. The default policy removes the observer flag.
A real two-stream/four-attribute/indexed/base-instance/varying/sampler pixel probe
covers the path closer to native CoreAnimation. Native behavior awaits hardware.

Phone/Photos are user-confirmed functional; automatic app launch checks are
retired. The upcoming fresh package disables both job cache and job plist and
enables only compositor readbacks; it preserves the user's foreground choices.

## Actual A620 row-layout conversion and native alias ownership — 2026-10-25

Preferred pins remain userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 and
kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab. V18 disproves direct480/4512-byte
sampling on this A620: row1 reads x8 instead of x0. Register bit fields did not
establish supported hardware alignment. Remove the sampler opt-in and preserve
ordinary freedreno import/view constraints completely.

Re-reviewed Mesa25.0.7 freedreno_resource.c native fd_bo ownership/layout/range
setup, fd_memory_barrier, fd_context access annotations and AIR's NIR finalizer,
real completion scopes and bindings. A paired raw PIPE_BUFFER import keeps the
actual IOSurface BO extent. A genuinely aligned LINEAR texture and a native
buffer alias share its actual separate BO. A bounded NIR compute grid copies
pixel rows in either direction with32-bit aligned accesses and exact bounds;
no pixel map/copy/raster operation on the CPU is introduced. All alias
transitions pay real native GPU fences and Gallium barriers. Content-valid and
dirty state are updated only after successful actual writes, under AIR's existing
serialized nonthreaded context ownership. No kernel/DMA permission expansion.

Per-command refresh and real output resolve preserve ordered passes, empty-pass
clears and native retained lifetimes. Distinct texture wrappers of one IOSurface
resolve a dirty predecessor and invalidate peer snapshots before reads. Native
compute pipelines/constants are rebound after internal conversion. The new
checker covers both exact incoming pitches twice, unaligned render outputs,
and a second wrapper reading an earlier write in the same command buffer.
Native hardware success and actual corrected GUI remain pending that capture.

## Native Metal raster/load actions and byte-pitch sources — 2026-10-25

Re-reviewed preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772:
redwoodmetal.m render encoder and tools/mesa/air/air_metal.c native draw,
attachment and framebuffer-fetch paths. Kernel remains unchanged at preferred
8e61187098f2c26c5daee8f9f72b6416aa64b9ab plus the documented Redfin overlays.
The upstream ignores scissor and most viewport/raster state and records only
attachment0 clears, at the first draw. Adapt the complete paired draw ABI and
ordered clear work so empty passes and each attachment keep their actual load
actions. Pipeline/surface references and real command fences remain native.

Mesa25.0.7 generated A6XX_TEX_CONST_2_PITCH carries the byte pitch; RB_MRT_PITCH
shifts it right6. Real CA480/4512-byte imports previously fail before sampling.
An explicit paired opt-in admits only bounded single-level linear A6xx sampler
imports, preserves actual pitch and avoids unsigned PITCHALIGN underflow.
Unaligned attachments/storage writes are refused explicitly. Other import paths
retain their requirements. Hardware suitability/correctness is pending the
new offscreen two-seed exact-pitch pixel/guard probes, not inferred from register
shape alone. Separate native MRT-clear/scissor/viewport/fetch probes and actual
GUI captures are required; earlier simple pixel probes do not prove system
composition. The native display observer creates no visible content and its
passive presentation counts are not a controlled animation benchmark.

## Preserve native failure causes and measure actual Metal stages — 2026-10-25

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and paired
userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 remain pinned. V14's native
EFAULT is not a false fence: keep the existing fail-closed DMA lifetime, but
capture owned FSR/FAR/FSYNR and bounded arena PTEs before retiring the current
thread lease. The current submitted BO list supplies the actual matching
object/offset or an explicit outside-list observation. No fault is cleared,
no unsafe retry occurs, and no incomplete fence becomes completed.

The preferred native Metal/AIR completion now records actual mach timebase
intervals for serial-queue delay, shared-context gate, command encoding and
final real finish. Only a successful native completion emits that evidence;
callbacks/timers are still separate from physical GPU presentations. This is
instrumentation, not a performance fix or a speed claim. Native byte/guard/
dependency probes remain unchanged and actual ABI/import/signature checks pass.

Google msm500b3a2059c1eec0fec08ec56add06320ea901a8 subsys-pil-tz.c reads the
ADSP subsystem failure reason using global SMEM and native DT qcom,smem-id423.
Redfin adds a bounded readonly v12/global-heap reader with allocation/source
bounds, duplicate rejection, stable payload/header reads and256byte maximum.
A pre-start observation distinguishes changed/new data from an already present
reason; nothing is cleared. Only an actual current SMP2P FATAL authorizes the
capture. No ADSP restart or additional MMIO is introduced.122selected combined
host cases and full native kernel/Mesa/AIR/plugin builds PASS; new hardware
evidence is pending. FastRPC/file service and direct VD6281 remain unfinished.

## Native GPU bins, thermal/idle DCVS and SSC startup subscription — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
redwood_adreno.c step_core_power: supply a native ascending GPU/voltage table
and use the GMU's acknowledged GX_BW_PERF_VOTE. Its315/450/550MHz table is
foreign to Redfin. Paired userland906425b75e02b4f99eb5d7bb1ef7c9583472d772
remains unchanged. Native Google msm500b3a2059c1eec0fec08ec56add06320ea901a8
kgsl_gmu.c/gmu_dcvs_set, kgsl_hfi.h and drivers/nvmem/qfprom.c establish
indices/ACK/rail dependencies and bytewise readonly fuse access. The actual
captured Redfin DT supplies all8OPPs,5speed-bin profiles, DDR use cases and
speed cell0x7801ea/two bytes/bits5..12. Only a matching actual fused bin admits
its full native table; unknown/unavailable bins retain275MHz.

A coherent snapshot from actual TSENS/QG observations drives caps through the
existing serialized GPU lease and GMU HFI queue. Invalid/stale temperatures
permit only the minimum. A separate100ms worker shares the GPU mutex/lease
and returns an idle engine to its minimum after200ms. Every vote preserves
actual native frequency/voltage/DDR pairing and requires the real matching
HFI ACK plus full surrounding ownership audits. Native msm MAX_FREQ reports
the selected bin's actual allowed maximum. This is request implementation,
not a measured physical-frequency/FPS claim.107selected combined host checks
and the full native kernel build PASS; V14 hardware is pending.

Read native Qualcomm SSC SUID/registry source at
Rivko/android-firmware-qti-sdm67020bb8ae36c93fc16bbadda0e0a83f930c0c8a271:
sns_suid_sensor.c, sns_registry_sensor.c and sns_registry.c. Native requests
append a registered update subscription. An initial empty registry list is
valid startup state; retain it with a bounded30s deadline and query actual
registry instances without default-only filtering. Importantly, this source
also documents registry initialization blocking on HLOS sdsprpc/file service.
That host dependency still needs implementation/observation; merely keeping
the subscription cannot establish registry/sensor success. No SUID, native
registry result or sample is fabricated. All downloaded source remains local.

## Native Sandbox extension ABI and ADSP cold order — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab,
xnu/files/bsd/dev/redwood_adsp.c step_header: an actually cold host2 does not
receive PAS_SHUTDOWN; INIT gets metadata in a separately owned kernel page,
then MEM_SETUP precedes destination memory access. Redfin retains its native
PAS1/host2/0x89200000/40MiB reservation and the existing CPU0 WLAN RSC/AOP
owner. A readonly cold witness, wired NC metadata with physical/readback
checks, guarded phases and immediate SMC entry/return observations implement
that order. Physical startup remains unproved until the combined capture.
The paired userland pin906425b75e02b4f99eb5d7bb1ef7c9583472d772 is unchanged.

Actual installed20H392 TCCD/library disassembly (libsystem_sandbox UUID
bee5f480cdb834ddaa8ee4e6d4ace436) confirms native issue5/consume6/release7
layouts56/24/24bytes and the authorized TCC-specific file resource "/".
The inherited local0050 policy lacks issue/consume. Redfin now transports
real opaque HMAC-SHA256 capabilities: actual native TCCD identity/platform/
CS_VALID/executable gate; private random boot key and nonce; class/resource/
UID/PID-generation scope; bounded active entries and balanced random handles,
copyout rollback and process-exit cleanup. Ordinary read/write root-file
capabilities remain rejected. Native TCC makes the permission decision; no
TCC answer, grant, DB, entitlement or native exception is replaced. This does
not implement the rest of Apple's Sandbox.63combined host cases PASS and the
complete native kernel build passes; actual Photos behavior awaits hardware.

## Native asynchronous submission, completion lifetime and TCCD attribution — 2026-10-25

Preferred graphics pins remain kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab
and userland906425b75e02b4f99eb5d7bb1ef7c9583472d772. Re-reviewed the latter's
native command/queue semaphore, callback queue and retained-reference paths.
A real GCD serial executor keeps Gallium ordering across queues while commit
returns promptly. Actual native completion controls groups, slots and late
handlers; synchronized retained callback queues permit reconfiguration, and
default callbacks run off the GPU executor. Native ivars are resolved by the
already-validated names, without racy initialization flags. The complete
native Metal/pixel/guard probe remains; no full Metal-feature claim is added.

Read-only review of installed20H392 TCCD
UUID78c8cbbeb0a33bf1accb52e15286b83c identifies native entitlement/attribution
methods and exact type encodings, without using its instruction addresses
at runtime. Capture-only observers call each original once and return its
actual result/error; even observer failures cannot replace native policy.

The source-verified Redfin PIL copy remains64KiB and fully byte-readback-
verified. Immutable DT/power checks bracket only reset-held reserved-RAM
copying; live ownership/maps/phase/source/plan remain checked inside it.
The complete contract precedes AUTH again. Host faults cover changing owner,
reset, mappings, time/phase and end-contract rejection; native hardware
speed/behavior still awaits the next complete capture.

Preferred redwood_adsp.c was read for PAS1/remote2/SMP2P/GLINK design. Its
Redwood addresses/64MiB reservation are unsuitable for Redfin's actual
0x89200000/40MiB reservation. Native sensor protocol references remain the
recorded Qualcomm SSC/CHRE sources; actual115persist registry/calibration
files are now inventoried privately. This is prerequisite research, not an
implemented or physically verified sensor backend.

## Metal command-buffer completion and native TCCD evidence — 2026-10-25

Re-reviewed preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772
redwoodmetal.m's commit/draw/retainedReferences and tools/mesa/air/air_metal.c's
per-draw finish/surface lifetime. Kernel references remain preferred
8e61187098f2c26c5daee8f9f72b6416aa64b9ab; later native-platform review pins
remain documented below. V9 proves real Metal192compute/BGRA/RG8 execution,
but its automatic six-layer workload completes only5.911physical fps despite
59.973callback Hz. Do not label a notification/callback rate as rendering FPS.

Redfin extends the paired AIR/frontend contract with a serialized command
scope: raster-only NIR (neither stage writes memory) can share the final real
fence. FD6 framebuffer/texture/image barriers preserve GPU dependencies;
compute, storage-writing stages and non-scoped callers still finish before
CPU validation. Every scope exit drains prior work and a failed completion
retires it. Gallium surface reference counting replaces premature direct
destruction; the command buffer retains encoding resources across pools and
clears attachments once per pass. A real three-draw alpha/pixel/guard probe
and host producer/consumer/failure checks accompany the implementation.

Actual20H392 CADisplay heartbeatRate is type/UUID-bound as a period, like its
refreshRate; only the independently verified90Hz panel permits1/90. Native
TCCD process/audit/CSOPS and Security batched-entitlement observations keep
all native answers and failures. They distinguish the remaining assetsd
permission cause without a fabricated entitlement, TCC bypass or suppressed
exception. New behavior awaits a complete physical capture.

## System Metal/CoreAnimation and native RG8 adaptation — 2026-10-25

V8 physically selects preferred906425b75e02b4f99eb5d7bb1ef7c9583472d772's
Metal implementation in backboardd, creates the real CoreAnimation pipelines
and preserves the visible UI/Phone/SpringBoard. Its AIR table already maps
Metal30/31 to R8G8_UNORM/SRGB; the separate drawable table lacks native
kCVPixelFormatType_TwoComponent8/2C08. Add that exact two-byte mapping with
all existing single-plane/stride/bounds guards and an actual RG8/guard probe.
Use Redfin's kernel-required MSM_PIPE_3D0x10 in the separate chip-name query,
not the foreign pipe0/A635 marketing name. Native Metal-finish observations
are boot-bound and occur only after the real Gallium fence succeeds.

The paired kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab remains the base.
Capture-only assetsd exception observation preserves Apple's exception and
TCC/Security policies. A bounded native UIKit animation compares callbacks
with lock-protected actual completed panel copies/GPU presentations; no fake
notification-based FPS and no new display hardware operation are introduced.
These additions are fully built/host-checked; new physical results are pending.

## Native entitlement enforcement, probe admission and Redfin OSM — 2026-10-25

Hardware follow-up bfdf8d0/V7: paired906425b renderer now opens FD620 and
passes192actual commands on two queues plus4096IOSurface pixels and native
completed GPU-fence evidence. This admits testing the existing system mode;
it does not establish complete Metal coverage. Native Security validated1
and all three hardware OSM domains/thermal transitions are now observed.
Remaining assetsd abort/TCC0 requires a native service fix, not an override.
Readonly vendor-base configs identify driver candidates LSM6DSR/LIS2MDL/
BMP380/TCS3701; preferred ADSP bring-up remains a protocol reference only,
with Redfin's PAS1/40MiB reservation and native power/shared-memory bindings.

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and paired
userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 remain the baseline.
Adapt actual20H392 SecTaskEntitlementsValidated's native4201 requirement
through CS_KILL/CS_ENFORCEMENT in the existing hash-validated root branch;
no DEBUGGED status or TCC interception. Use actual8796 memorystatus commands
7/8 and signed own-process entitlement for the Metal probe, following the
already-verified Photos admission. Google500b3a2059c1eec0fec08ec56add06320ea901a8
qcom-cpufreq-hw uses freq-domain args[1]; captured Redfin DT supplies6/2/2,
independently of6/1/1CPU membership. Correct the LUT selection and strictly
validate all eight bindings. Actual Metal execution, native TCC acceptance
and big-core transitions require the next combined hardware capture.

## Actual native Metal/AIR and platform readiness — 2026-10-25

Re-reviewed preferred kernel8e611870 MiniIOMobileFramebuffer's native Metal
bundle discovery and MiniAppleKeyStore's canonical DER state. Userland
906425b75e02b4f99eb5d7bb1ef7c9583472d772 supplies redwoodmetal.m,
redwooddrawable.m and the AIR frontend/IR3/Metal patches over Mesa25.0.7.
Redfin uses the native A620 msm/IOSurface ABI and128MiB kernel allocation
bound, derives every superclass selector/UUID/ivar type from actual20H392,
and serializes the one Gallium context across concurrent native queues.
No20F66 addresses or foreign target-device architecture are copied. Source
pairing/export checks reject a mismatched compiler. Native MTLFunction
fallbacks keep the previous implementation for another device. Probe and
system discovery are both implemented with separate exact ADT modes; neither
is claimed physically working from a host build alone. Upstream's explicit
unsupported API/features remain visible and are not advertised as complete.

MiniAppleKeyStore's ss6/sls3/sr and canonical SET ordering replace inherited
ss4/sls0/unordered state; wrap material and native AES integrity are unchanged.
Google500b3a2059c1ee smb5-reg.h/smblib_get_prop_batt_health is authoritative:
status7 hard bits3:2 differ from AFP1:0/soft JEITA5:4, and a BAT_OV indication
is evaluated against measured voltage at native FV+40mV. Status5 actual
enables distinguish charging. Native limits, JEITA/safety and unknown-data
pause guards remain. Initial assetsd242fails while replacement244survives;
Photos bootstrap retries only native XPC service failure, preserving TCC and
native library creation/upgrade. RFH2 alternate capture and bounded AKS logs
preserve the evidence that the current noisy state requests had overwritten.
All118current selected host cases and complete native builds pass; the next
combined physical probe must decide actual Metal/Photos/charge behavior.

## Native Redfin power/thermal/clock and measured app refresh — 2026-10-25

Read-only review of preferred kernelHEAD
d82c64a3a31cd27a0a0afbf6e213e467e44b1b4c (relative to8e611870) finds the
7zip setup check and ramfb-mode selection, without a Redfin PMIC/thermal
backend. Retain8e611870's RedwoodBattery IOPMPowerSource publication and
adapt the native pressure-notification boundary from userland
a79ff0772a3454fd1ef127e181e5b3bce6c9ce18 thermald.c. Its expected kernel
thermal implementation is absent from these kernel snapshots. No Redwood
PM7325B/UEFI cache, guessed temperature or EPSS address is imported.

Google kernel/msm500b3a2059c1eec0fec08ec56add06320ea901a8 supplies the
actual Redfin interfaces: PM7250B SID2/QG4800/SDAMb100/ADC53100/SMB5,
tsens2xxx.c's26xx SROT/TM layout and qcom-cpufreq-hw.c's standard OSM
110/stride32/920 layout. These are bound against the captured live FDT.
Native QG code22813 corresponds to the independent4440253uV observation;
signed14 at subtype4 is4272uA. ADC5 uses the native100k table/full-scale
70e4; RRADC's Kelvin conversion and generic tsens-v2 are inappropriate.

Only the owned ADC5 configuration/conversion request, charge-enable/pause
bits and QG monotonic SOC are writable through this private adapter. A late
SPMI/ADC completion retires the adapter without reuse. Native charge limits,
JEITA and safety timers must be valid before enabling; no voltage/current
limit, protection, regulator or PMIC calibration overwrite is added. Real
TSENS pressure selects valid hardware OSM rows for6/1/1cores; hardware owns
voltage. Foreign LUT/perf state changes retire that domain. The retained
RTC6048 is read-only: Android's old epoch mapping disappeared with userdata,
so a private host-UTC/counter anchor restores calendar time without changing
the RTC/alarm. Thermal critical thresholds request native clean shutdown.
Physical battery/charging/thermal/frequency behavior still requires the next
combined hardware run; host fault models are not physical measurements.

Actual20H392 CADisplay refreshRate/hardwareRefreshRate return seconds per
frame; UIScreen maximumFramesPerSecond returns Hz. UUID/type-bound adapters
use1/90 and90 only when the framebuffer publishes the independently verified
physical90Hz result. CADisplay minimumFrameDuration is a frame count and is
left native. The camera layout keeps its measured x53.35time placement.
Native MobileWiFi Set/CopyPassword from preferred906425b's wifipw_test.c is
adapted as a persistent synthetic unjoined marker, without reading/logging
any user's password. Native HTTPS keeps system trust and uses no cookies.

Current assetsd crash's actual executable+162ec throws "assetsd requires
TCCPhotosService access" after PLPrivacy photosAccessAllowedWithScope7.
Current tccd exists and its database/home permissions are already correct.
Do not infer a permission fix from kernel XML flags: observe native SecTask/
TCC preflight and the native daemons' scoped logs; no TCC override, database
edit, fabricated entitlement or suppressed exception is added.

## Native AKS descriptor lifetime correction after physical90Hz capture — 2026-10-25

Authenticated boot3635d632d4fbfca8 proves S6E3HC2 TE60->90Hz and independent
INTF21->31frames/350ms using the source-verified FIFO path; mean TE changes
16682->11123us. Its later CPU6/profiled panic symbolicates to the inherited
AKS output helper's writeBytes/getPhysicalSegment with an unwired IOGMD.
Re-reviewed preferred8e611870 MiniAppleKeyStore::answer: prepare precedes
writeBytes and complete follows it. Adapt that lifetime for both descriptor
input and output, preserving native direction/copy-on-write, bounds and all
native failures. Regression descriptors assert wiring for every read/write,
including the actual4096byte device-state case, short copies, prepare errors
and completion errors. Keep all real crypto/integrity and publication guards.
The paired userland pin remains906425b75e02b4f99eb5d7bb1ef7c9583472d772.

## Native device bag, full-panel status bar and display-mode ABI — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab
MiniAppleKeyStore and MiniIOMobileFramebuffer, with paired userland
906425b75e02b4f99eb5d7bb1ef7c9583472d772 unchanged. Actual20H392 securityd
requests selectors10/11's two-scalar wrap/unwrap ABI. Adapt that ABI using
AES256/RFC3394 and persistent private software material, binding the native
key class into its integrity IV; do not import the upstream's fixed mixing
key or claim SEP. Platform startup consumes/removes the material's chosen
property before userspace. Native UUID/configuration/generation/prewarm and
notification-state operations, inband/descriptors and exact copy lengths are
handled. A synthetic SecItem marker exercises securityd without a Wi-Fi
password; only a subsequent boot can establish actual persistence.

Installed IOMobileFramebuffer UUIDafd11f8e008f3276bd72c0e0d96cffa6 confirms
selector72 notifications,79 GetBlock,77 absolute time and the six-halves
VsyncNotifyFunc ABI. Its callback decodes time/presentation-time/counter;
the inherited Sweet driver sent counter/time/zero. Correct that order and
publish the preferred driver's TimingElements/ColorElements/current IDs.
Actual IOMobileFramebuffer contains those property names, and QuartzCore
contains HorizontalAttributes/VerticalAttributes/SyncRate/PreciseSyncRate.
Keep the logical1125x2436canvas while filling all1080x2340physical pixels,
with the matching inverse touch transform. The tiny aspect correction fills
the formerly unused two rows; nothing is cropped from the source canvas.

Neither preferred repository contains an identified Redfin cutout adapter.
Use installed UIKitCore1242978a2c2c37818d6c9777edce2804's verified native
avoidance/layout/time-item APIs and public UIView coordinate conversion.
The runtime refuses another UUID/method ABI; the time stays outside the
source-verified [0,145)x[0,136)camera rectangle without changing global safe
areas or shrinking the whole UI. Native exec/dyld adaptation remains scoped
to GUI3, exact system executable paths and full-panel mode. AMFI checks the
actual executable vnode path and drops its acquired iocount on every exit.
Only the existing backboardd EAGL bridge and five named system UI executables
are eligible. No global injection or Metal device publication is added.

Google kernel/msm500b3a2059c1eec0fec08ec56add06320ea901a8's panel DTS,
dispcc-lito.c and pinctrl-lito.c, and msm-extra/display-drivers
ca74909cd98764454a2dacf784cda119c45a7f4c's native FIFO/interrupt/TE helpers,
are reviewed. The captured live FDT selects S6E3HC2 with matching60/90Hz
commands53:28/53:38,554MHz,14000/9000us transfer times and GPIO10 TE.
Bind its real DSI2.4/INTF1/clock/GPIO addresses into a strict builder/shim/
kernel contract. A bounded command-mode transaction uses the native FIFO,
preserves its configuration, requires fresh DMA-done and physical TE edges,
and verifies90Hz separately from DPU frame count/render FPS. It keeps the
inherited external-TE autorefresh owner; a failed measured switch rolls back
to60Hz. Unknown/video/off-clock handoffs refuse the switch. There is no new
memory-DMA allocation, display SMMU, scanout address, DSC or PLL change.
No physical90Hz result is claimed before the combined hardware capture.

Remove only two redundant immutable-payload comparisons inside each nested
runtime snapshot. The complete outer audit still checks every payload once
before accepting its tuple, before and after every real GPU submission.
Twice-read foreign/SMMU snapshots, power/caller guards and faults/fences stay.
Native Photos initialization now checks canonical filesystem paths because
its own URL manager accepts the /var spelling. An explicitly opt-in native
GUI checker opens Phone/Photos and records process/window-server survival;
it makes no call/message/account operation. Existing helper updates retain
all allocated blocks; every new zero block, complete signed file, native
readonly fsck, allocation/preimage and data-before-metadata order is checked
before applying the separately backed-up update.

## Complete A620 panel presentation and bootstrap-installation correction — 2026-10-25

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's RedwoodGPU
serialized submission/fence ownership and MiniIOMobileFramebuffer source
holds remain the baseline; paired userland906425b75e02b4f99eb5d7bb1ef7c9583472d772
is unchanged. Re-reviewed the installed Mesa25.0.7 fd6_blitter.cc,
fd6_barrier.cc/fd6_emit.h, A620 device info and a6xx/adreno_pm4 register XML.
The internal kernel presenter adapts their real 2D blit/clear/CCU sequence,
using the existing GPU mutex/current-thread lease and actual synchronous
completion checks. The public msm bridge and ordinary RAM-only mapper retain
their ABI and page permissions. A separate kernel-only mapper permits just
the independently verified fixed splash pages; it cannot map arbitrary
reserved memory. No display SMMU, DPU/DSI register or scanout address changes.

Redfin's4320-byte panel pitch is not representable by A6xx's64-byte fields.
The whole frame scales into4352-byte rows, followed by two GPU copies:
even rows use8704/8640-byte source/destination pitches; odd rows use the
same doubled pitches, a64-aligned destination32bytes before the row and
destination x=8. Every output row still has1080pixels. iPhone X canvas,
conservative camera exclusion and inverse touch geometry remain native to
Redfin. Unsupported layouts/clipping and swaps without a full base layer
take the existing CPU path. A failed physical-target completion stops CPU
pixel writes and retains both mappings and source in-use holds until reset.

Before mapping the panel, a fenced private-RAM check exercises actual BGRA
clear/scaling, all2340packed rows and prefix/tail guards. Four initial real
panel frames also compare64actual pixels to the GPU staging result. These
are runtime admission checks inside one combined boot; no hardware result
or stable60fps claim exists before that run. Metal remains separate work.

V6's new Photos executable is read back in unmounted recovery:1113bytes
differ from the signed source, every difference lies in a source-zero byte,
all nonzero source bytes and the complete catalog record match. Native
codesign verification rejects that actual file. The sparse install planner
omitted new all-zero blocks, incorrectly treating sparse-host zeros as live
device preimages. Plan every newly allocated block regardless of content,
and verify complete files through their actual extents after installation.
The native exec guard requires the original valid/signed/platform and XML
entitlement status for this one GUI3 helper before its exec event; it never
manufactures signature validity or bypasses launchd's platform check.

## Complete clock/photo-library/private-serial block — 2026-10-25

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and paired
userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 remain pinned. The runtime
source checker currently calls gm_valid in both rf_gt_rd and gm_read for
each of16clock registers. Its runtime-only metadata callbacks preserve the
same16actual GCC/GPUCC reads and allowlist; GMU space is excluded. Complete
twice-read SMMU/foreign snapshots, payload/parent/power boundary guards,
before/after-submit audit frequency and every hardware-write guard remain.
Startup callbacks, clock rates, ownership and real fences are unchanged.

Actual20H392 reports now give Photos flags0x22004001/category1, but the
same zero-section assertion. Assetsd survives its former TCC abort. Native
501-owned PhotoData contains only Thumbnails; the library registry only
Syndication.photoslibrary. The first-library initializer obtains the native
system URL/well-known identifier and calls installed Photos create/open
APIs with verified selector types and paired cache UUIDs. Existing store
candidates take the open path. Its mobile-only GUI3 job requests native
own-PID512MiB, logs actual results and does not invent a schema or assets.
Hardware creation and Photos UI remain unproved before the combined run.

For the user's serial/App Store/Apple ID request, an explicit private config
supplies this Pixel's real boot-transport serial to root/chosen and standard
IOPlatformSerialNumber properties. Copies must match and be bounded/NUL-
terminated; no raw identifier goes into git or public reports. No Apple
ECID/certificate is fabricated. Re-reviewed paired mkjobs.py's account/
apsd/mobileactivationd findings: native activation/certificates remain
separate from local serial publication. Account login is not established.
Also reviewed redwoodmetal.m/tools/mesa/air: substantial compute/render/
resource and AIR-to-NIR/ir3 code exists, with documented unsupported features.
Its Redfin/20H392 adaptation and actual evidence are still future work.

## Complete presentation pipeline and native process identity — 2026-10-25

Re-reviewed preferred kernel 8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
MiniIOMobileFramebuffer presenterMain/presenter/show, helperMain/drawRows/
drawLayer and frame-interval reporting. Redfin adopts one separate presenter
and three row helpers, retaining its own bounded SweetSurface descriptors,
pixel/state separation, camera exclusion and inverse touch mapping. One
queued swap retains its actual in-use references; a busy slot leaves the
latest pending swap intact. Each helper has its own blend workspace and
disjoint full rows; source lifetime extends through the complete join.
Pixel writes, including power-off clearing, remain serialized. Source holds
can retire after the CPU copy because Redfin's preserved panel framebuffer
does not DMA-fetch the copied source surfaces. No upstream display/SMMU
private layout or direct scanout is imported.

The notification timer advances an absolute phase independently of the
presenter; a late callback skips elapsed periods without accumulating copy
time or generating a catch-up burst. Started threads retain the service for
the boot lifetime, as the preferred persistent worker model requires. A
failed helper/presenter start retains the complete scalar/synchronous path.
Bounded aggregate timing distinguishes copy work, queue delay and intervals;
none alone establishes measured hardware vblank or stable 60fps.

The actual assetsd crash states "requires TCCPhotosService access", although
its stock signature requests com.apple.private.tcc.allow/Photos. Its native
report has flags0x22000001/category0: the current root-volume platform policy
does not appear in that process metadata. Re-reviewed preferred miniamfi's
signature entitlement ownership and actual8796 MAC/CS_OPS_STATUS/category
interfaces. Redfin accepts the actual root vnode's pinned mount as well as
MNT_ROOTFS, sets CS_ENTITLEMENTS_VALIDATED only for its existing root policy
with a native hash-checked parsed XML object, and publishes the corresponding
platform validation category through the native setter. Other categories,
non-root signatures and the entitlement dictionary are preserved. Scoped
native logs identify assetsd/Photos/tccd's effective flags and Photos key.
No TCC database edit, invented entitlement or Apple binary patch is used.
Whether this resolves the observed TCC denial remains a hardware question.
Paired userland 906425b75e02b4f99eb5d7bb1ef7c9583472d772 is unchanged.

## Native MobileCheckpoint cache and bracketed snapshot reads — 2026-10-25

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and paired
userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 remain the graphics baseline.
Re-reviewed the latter's mkjobs.py CommCenter findings: even the selected
noncellular job eventually crashes on absent AppleIPAppender/AppleBasebandPCI.
Keep it disabled rather than introducing that known loop to answer Phone's
voicemail worker. Phone's sampled main thread is in its normal run loop.

Actual20H392 libMobileCheckpoint's MCCopyCheckpoint path returns its native
NSDictionary cache directly when stat mtime seconds AND nanoseconds match
the installed Checkpoint.xml. A missing cache sends synchronous command0 to
checkpointd; that is Photos' observed main-thread wait. Redfin seeds the
verbatim installed XML dictionary, with mobile ownership and its destination
filesystem timestamp. The offline HFS helper copies contentModDate through
updateCatalog; it does not convert a host extraction date or invent image
capabilities. Checkpointd itself already starts. Its own underlying wait is
not yet observed; a bounded sample now targets it in place of callservicesd.

Redfin retains complete twice-read global/CB0/CB1 snapshots and the original
foreign-state comparisons on every submission. Only nested read callbacks
lose their redundant CX/GX power reads: the serialized caller/context lease
stays mandatory, full parent/source/power checks bracket the snapshot, and
the outer audit now closes with another full guard and payload check after
its final TTBR reads. All hardware-write guards and DMA bounds remain.
Paired graphics userland is unchanged; Metal remains separate work.

## Runtime caller ownership, final fence reads and GPU timestamps — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
RedwoodGPU synchronous mutex ownership and redwood_adreno.c ring_time/
redwood_gpu_submit. Native runtime I/O does not migrate each caller to one
CPU. Redfin now retains CPU0 for every hardware startup/claim, then permits
only the GPU mutex's current-thread lease on one of the eight proved GUI
CPUs. Parent args/power/firmware and complete foreign SMMU audits remain;
the scoped caller lease is required for each non-CPU0 parent check. An
unproved CPU, changed caller or overlapping lease cannot activate hardware.

The previous wait loop could skip reading a completed fence after being
descheduled beyond its wall deadline. The new common wait helper observes
actual completion first and once again at timeout; a missing fence/fault
still retires the queue and retains DMA memory. Failure logs now contain
the actual fence/rptr/status/poll/time values. Preferred CP_REG_TO_MEM of
the19.2MHz CP_ALWAYS_ON_COUNTER brackets each IB batch, with WAIT_FOR_IDLE
before its end timestamp and the existing real cache-flush fence last.
This separates GPU execution from host scheduling delay without a fake
completion or GPU reset/recovery path.

The observed backboardd restart also closes its HID client; the existing
worker exited withEPIPE. Bounded reconnection retains that same verified
SPI/hardware lease, releases old contact state, waits for a real consumer
and discards stale queue data before new DOWNs. No sensing/rail restart is
introduced, and the original session deadline and fatal hardware errors
remain in force. Hardware stability/performance still needs the next run.

## msm dependency flags are distinct from page permissions — 2026-10-25

The975c644bc72f03ae integrated run rejects every submit withEINVAL22;
there is no runtime fence or shader pixel pass, despite EAGL's queued-frame
counters. The new readonly-allocation/submit-WRITE cross-check was wrong.
Reviewed Mesa25.0.7 freedreno_priv.h RING_FLAGS, msm_bo.c and
msm_ringbuffer_sp.c: command BOs are GPU_READONLY and dependency flags can
still include READ|WRITE|DUMP. Preferred kernel8e611870 RedwoodGPU::submit
likewise does not reject that combination. The correction retains metadata
bounds/presumed-address checks and actual readonly SMMU AP bits. Native
client-bound completed-fence lines distinguish backboardd's work from the
standalone shader process; queued GL frame counters alone are insufficient.

## Complete graphics/boot performance batch — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
RedwoodGPU::submit seed/4ms surface-cache policy, client-mapping treatment
and prepared surface retention. Redfin adopts that push policy, invalidates
only GPU-written surfaces after real synchronous completion, and permits
native prepared wrapped ranges with SweetSurface's wrapDelta rather than
MiniIOSurface's leading state page. Read-only wrapped pages retain read-only
GPU permissions. No asynchronous
completion or foreign fault recovery is introduced.

The runtime still makes complete stable global/CB0/CB1 snapshots before and
after each submission and compares every foreign word. Their read-only
callbacks use a bracketed CPU0/fixed-power epoch to avoid recursively
revalidating every parent on each register read. Table construction batches
cache-line publication before the same native ASID0 TLB synchronization;
ring publication cleans only the changed spans. Hardware writes keep their
full guards. CPU affinity switches occur only when actual migration is
required. GPU retirement moves after normal process exit.

The latest native capture's firmware copy alone costs20243ms. Redfin's
serialized GUI firmware worker now caches traversal of its pinned immutable
boot ADT; the existing value comparisons and source/owner/CPU/epoch guards
still run against live bytes. A bounded cache miss uses the original native
lookup. Native PAS4/MPSS copy/readback/GLINK/WLFW ordering and all aperture
fences stay unchanged. New phase timestamps make firmware/station delay
measurable. Hardware timing, wrapped-surface results and60fps remain pending
the complete combined run. Paired userland906425b75e02b4f99eb5d7bb1ef7c9583472d772
remains byte-identical.

## Saved exec path and bounded native graphics memory admission — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
RedwoodGPUUserClient::initWithTask and gemNew. Redfin now borrows the owning
task during synchronous init/start in the same way; its kernel/shared/WC
BO allocation flags already match. No change to GPU memory ownership or
allocation accounting is inferred from the diagnostic's per-process kill.
Actual XNU8796 exec_save_path stores executable_path= before the pathname;
the scoped insertion predicate must consume this native prefix.

Actual8796 memorystatus_set_memlimit_properties and its ledger update are
reviewed. GUI3's two graphics clients set512MiB fatal active/inactive limits
through that native setter and require the effective limit before allocation.
The helper remains in the setter's translation unit, outside DEVELOPMENT,
and cannot operate on another task. No global Jetsam bypass is introduced.
The existing userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 stays installed.
Hardware shader/system drawing/Metal still require actual evidence.

## Stock launchd filtering and graphics bootstrap correction — 2026-10-25

Reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
`redwood.patch` exec_inject_env/exec_extract_strings path. The current
20H392 launchd file log explicitly filters DYLD_INSERT_LIBRARIES from jobs;
AMFI permission alone does not supply the variable. Redfin now adapts the
native argument insertion point to one fixed loader, exact GUI3 and the
absolute /usr/libexec/backboardd path plus its basename. It keeps ordinary
NCARGS/string/pointer accounting and adds no configurable/global injection.
The earlier job EnvironmentVariables insertion is removed.

The same native file log proves backboardd's posix_spawn EACCES with its
new console redirections, and gpu-render's Jetsam per-process-limit kill.
The final bootstrap uses precreated501-owned logs and the actual launchd
ActiveHardMemoryLimit/InactiveHardMemoryLimit keys (512MiB each), rather
than its deprecated JetsamMemoryLimit key. Original Apple job properties,
all other jobs, kernel global memory policy and the full graphics block
remain retained. Hardware EAGL/shader results still require the next full
integrated capture; native HFS replay/clean shutdown are now observed.

## First system graphics panic: preserve high physical address bits — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab,
`xnu/redwood.patch`'s `pmap_sync_page_attributes_phys` hunk. The first
integrated20H392 graphics run reaches GPU BO creation in gpu-render, then
panics when a cache-mode change truncates1fc598000 tofc598000. Actual
frozen-kernel disassembly shows `lsl w0,w20,#14` before flush_dcache;
source casts the result of a32-bit ppnum_t shift. The preferred exact fix
casts pp to vm_offset_t before shifting. The Redfin overlay preserves
cache maintenance, WIMG changes and physical-aperture validation. It does
not change GPU mappings or reduce the installed EAGL/system graphics block.

## Complete system EAGL integration for 20H392 — 2026-10-25

Reviewed preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772:
`userland/src/eagl.c`, `gl_osmesa.c`, `redwood_gl.h`, `eagl_slots.txt`,
`userland/mkeagl.py` and the function-uniform hook in `src/inject.c`.
The MIT shader/IOSurface adaptations are kept together in the private build;
`eagl_userland.py` records and applies the Redfin source adaptations, with
the upstream license included. None of inject.c's 20F66 addresses, input
replacement or prototype Metal device is copied.

The initial interpretation of the 32-byte dispatch difference is superseded:
actual20H392 `getMacroContextPrivate` returns native-context+32. All457 GL
wrappers use the native context, with their first argument at+32; QuartzCore
uses the macro table with its context at+0. Subtracting that prefix gives
the preferred macro offsets. The adapter derives every stub, both ObjC
method signatures and the QuartzCore uniform vtable entry from this root's
paired arm64 cache/local symbols. It checks image UUIDs, exact method RVAs
and signatures before installing11methods. Its native prefix also supports
the reserved OpenGLES TLS key and class current-context methods. A private
copy of the actual QuartzCore uniform data page supplies the preferred
shader-less function parameters; the original function is still called.

Reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab's
`xnu/files/bsd/kern/kern_minimac.c`, AMFI request0x5a. Our previous policy
has no handler namedAMFI. The adaptation admits that native dyld query
only for backboardd in the exact GUI3 profile; other callers/requests retain
ENOPOLICY. The only inserted library is a minimal loader in backboardd's
existing job. It requires the published native A620/runtime ABI before
opening the Mesa bridge. GUI1/2 retain the existing graphics path.

The rendering diagnostic migrates its exact known cache key from Library
to System/Library/LaunchDaemons, matching the actual stock bootstrap scan.
The complete block is implemented before its combined build/verification;
system drawing and Metal remain unproved until actual hardware evidence.

## A620 persistent GUI3 / Mesa / IOSurface bridge — 2026-10-24

Reviewed kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab again, now
`iokit/Kernel/RedwoodGPU.cpp`, the retained-buffer/IB/fence/parameter methods
in `redwood_adreno.c`, and the native msm1.7 ABI. New service uses that
userspace interface with Redfin's proven native CB0/SID0/ASID0 owner.
Its first implementation serializes submissions and waits for the actual
GPU-written cache-flush fence. Mapping or completion loss pins backing
descriptors until reset. It omits the upstream optional reset/recovery path.
The kernel-side adaptation retains APSL2.0 attribution.

Reviewed paired graphics userland906425b75e02b4f99eb5d7bb1ef7c9583472d772:
`tools/mk-mesa.sh`, `tools/mesa/freedreno-darwin.patch`, the ES profile and
three IR3 fixes, `redwood-drm`, and `userland/src/gl_osmesa.c`. Mesa25.0.7
source archive is SHA256592272df3cf01e85e7db300c449df5061092574d099da275d19e97ef0510f8a6.
Build targets arm64/iOS16 and keeps all binaries under ignored research.
The newer a79ff077 userland review remains the general source pin; the
paired906425b graphics source is explicitly selected for this interface.

20H392's SweetSurface keeps state and pixels in separate descriptors, unlike
the preferred MiniIOSurface's page prefix. Import adapts that difference and
holds the original surface reference. A standalone iOS ES shader diagnostic
imports an actual IOSurface, draws twice with boot-bound colors and validates
both GL readback and the surface's CPU view; software rendering is refused.
The system's original OpenGLES/Metal libraries are not replaced by this batch.
Host checks and native builds pass; GUI3/rendering hardware evidence is pending.

First GUI3 capture reaches the GMU/global-SMMU boundary, then native XNU
`arm/io_map.c` exhausts its fixed8MiB permanent `io_submap` at a16KiB CB
mapping. It panics with KERN_NO_SPACE/NOFAIL, before any GPU DMA. Reviewed
`ml_io_map_unmappable` in `arm64/machine_routines.c`: it selects general
kernel-map DATA VA and the caller's exact IO7/NC6 attributes. All retained
GPU/GMU MMIO, CMD-DB and host DMA-alias mappings now use this native API;
no VM pool size, protected-bank access or device memory attribute is weakened.

## Complete A620 GPU command-chain adaptation — 2026-10-24

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`,
`redwood_adreno.c` steps17–21, allocations/streams/ring/SQE/zap/commands.
The complete opt-in mode5 adapts those interfaces to A620 with native msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`. Newly reviewed native references
include `msm_bus_arb_rpmh.c`, `msm_bus_fabric_rpmh.c`, `msm_kgsl.h`, and
the PIL relocation/allocation/authentication path. Captured FDT is checked
against DT pin `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`.

A620 uses275MHz/64, native DDR case5 and all13bandwidth rows, UBWC3,
FIFO10000/TSE-skip disable and hang3ffff. It has the native user SID0/mask401
route. The initial A642L split-mask400 adaptation is superseded after Redfin
HYP rejects it: schema3 uses the exact native single SID0/mask401 group.
CB0 is allocated independently
of the proven GMU CB1; foreign/secure state is audited. The native generic
PAS13 node has no memory-region, so its relocatable ELF receives an owned
1MiB-aligned allocation/4KiB span. This replaces the unsafe assumption that
the unaligned bootloader reservation is a writable zap destination. Both
SCM transport and PAS result must succeed; the upstream inherited-zap fallback
is deliberately not used. Native crypto BCM proxy floors are retained.

The same review now follows preferred native ordering as a complete profile:
reserve SMR0 for GPU, select SMR1 for GMU, obtain GX/OOB, mask local GPU
interrupts, then bind the GPU group before the native single CP start.
Standalone GMU modes keep their proven first-free choice. Runtime audits
use the unchanged GMU lease before GPU mapping, then the joint exact lease.

The v6 capture obtains all performance/BW/core/start ACKs and fresh GX/OOB,
then stalls before any logged GPU route or command. Re-review of native
`adreno.c:_adreno_start()` reveals a separate CPU→GPU_CFG HIGH request before
wakeup. The captured Redfin FDT binds APPS1→598 through SH4/SN10/CN0;
the initial adaptation only supplied GPU-initiated traffic votes. Schema4
adds the exact native CPU configuration client and both SN10/CN0 in the GMU
CNOC table. After GX/OOB, native fence ALLOW and exact access breadcrumbs
precede the first GPU CSR access. The v6 cause is not proven until validated.

The v7 capture validates CPU CFG votes and real RBBM CSR read/write, then
stalls precisely storing SQE_CNTL3. Native `adreno_a6xx.c:a6xx_rb_start()`
and preferred step20 only release SQE with CNTL1 after core/ring/SQE setup.
Schema5 removes the extra HALT3 request, retains fresh cold-domain ownership,
and admits exactly one native start after complete mapping/configuration.

Reviewed again for the first CB0 run: preferred `space_on()` verifies S2CR
type/context with mask300ff and preserves HYP control of other fields.
The GPU mapping now follows that readback mask and keeps the full observed
word in later audits. Native `arm_smmu_context_asid()` uses CB+1 while the
preferred standalone owner uses CB. The completed mapping review aligns our
standalone CB0 to preferred ASID0, distinct from proven GMU ASID1; schema2
binds it explicitly. This source alignment is not evidence of the earlier
unidentified readback failure's cause. Typed-map diagnostics record the step.

Actual source now includes the complete HFI/performance/bandwidth/GX/SQE/
signed-zap/ME_INIT/unsecure/memory-write chain before its integrated tests.
An early HFI-ready bit is accepted after reset release, matching the already
observed A650 firmware behavior. Current preferred userland pins remain
`a79ff0772a3454fd1ef127e181e5b3bce6c9ce18` and paired graphics-ABI reference
`906425b75e02b4f99eb5d7bb1ef7c9583472d772`; this batch installs no graphics
userland and makes no Metal-capability claim. Details: [GPU-COMMANDS.md](GPU-COMMANDS.md).

## A620 CM3/PDC/RSC/HFI start adaptation — 2026-10-24

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`,
`redwood_adreno.c` steps15/16, `block_uncached()` and HFI receive/send.
The separate explicit `--gmu-firmware-start`/redfinsmmu4 profile now adapts
that complete bring-up to A620 using native msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`: `adreno_a6xx_gmu.c`,
`kgsl_hfi.c/.h`, `a6xx_reg.h`, `kgsl_gmu.c` and newly reviewed `adreno.c`
local interrupt masking. DT remains pinned at
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`; actual captured FDT is validated.

A620 programs its own PDC instruction memory and TCS1/TCS3 commands using
runtime-validated CMD-DB xo/cx/mx and optional vrm.soc. RSC uses native
A650-family code and hidden TCS data80000000. These replace upstream's
AOP-programmed PDC and80000021 assumptions. The native RSC aperture is
4KiB: only contained TCS0/1 status/control are inspected; generic helper's
TCS2/3 outside the range are not touched. Inherited RSC sleep, if observed,
uses the native wake handshake before programming, with no retry.

HFI and log gain a verified contiguous uncached host view as upstream;
cached aliases are cleaned/invalidated before use and not accessed after
CM3 can write. Native HFI has4descriptors, not upstream's17. Version request
uses v2 header/16-byte padding; ACK checks full original header, status,
bounds and native2.0 version compatibility. No dependency on deprecated
v1 ACK ID126. Initial IRQ masks follow native `adreno_gmu_mask_and_clear_irqs`;
GIC remains disabled and host queues are polled. Lifecycle checks distinguish
held reset, fresh firmware completion and HFI startup; all owned SMMU/foreign
state is audited at transitions. Only one reset release is provided.

This profile sends no performance/bandwidth table, CORE_FW_START, GX request,
GPU CP command or PAS call and publishes no graphics/Metal capability. No
preferred userland ABI was changed; source snapshots remain those reviewed
below. Hardware CM3/HFI evidence is pending; host tests/build are not DMA proof.

First17464e8 hardware run reaches hidden RSC CMD0_ADDR: native zero write
reads back82204514. Native/upstream do not require zero destination readback;
the local protocol now preserves that behavior for the three hidden ADDR
registers while still checking data/uCode, actual PDC resource destinations
and control fields. No reset release or permission bypass was attempted.

Start-v2 validates RSC/PDC instruction words and native RSC data/control.
PDC MSGID10108 reads10100: command length byte is fixed/RAZ; native does
not require its echo. The local checker now requires native WRITEbit16 and
RESP_REQbit8, preserving all ARC destination/data and control verification.
RSC idle preflight also uses both native AMC_ENABLE16 and TRIGGER24 bits.

Project upstream preference, 2026-10-23: the user designates
[oosexgang/hackios-xnu-kernel][kernel] and
[oosexgang/hackios-xnu-userland][userland] as the most stable source repositories.
These are the primary references for ongoing GPU, display geometry/camera-cutout
and userland work. The review below identifies the exact snapshots already read.

Read-only review of two release snapshots, kept under ignored
`research/hackios-upstream/`. No upstream patch, prebuilt library or Apple
artifact was installed by this review.

| Repository | Pinned HEAD | History |
| --- | --- | --- |
| [hackios-xnu-kernel][kernel] | `8e61187098f2c26c5daee8f9f72b6416aa64b9ab` | Initial release `4ab189d`, then license; both 2026-10-22 |
| [hackios-xnu-userland][userland] | `906425b75e02b4f99eb5d7bb1ef7c9583472d772` | Initial release `89779df`, then license; both 2026-10-22 |

These are source snapshots, not a series of independently validated fixes.
The kernel contains XNU changes, platform drivers, a UEFI/loader path and
LinuxKPI/ath11k support. Userland contains its own init/APFS image builder,
injection libraries, job/test scenarios, an EAGL/Mesa bridge, a prototype
Metal implementation and shader-analysis tools. Its README declares Apple
files absent. Preserve per-file licenses and dependency notices when porting;
the userland's own code is MIT, while external dependencies have their own
licenses.

## Compatibility boundary

Reviewed 2026-10-24: preferred userland commit
`906425b75e02b4f99eb5d7bb1ef7c9583472d772`, `userland/mkjobs.py:287` removes
`_LimitLoadToDeviceTree` from selected jobs, explicitly explaining wifid's
absent `wlan` node. Redfin's real 20H392 cache retains the wifid gate
`[wlan, marconi-wifi]`, while the validated native GUI ADT has neither node.
The manual capture executes Preferences but never wifid; the user reports
a gray Wi-Fi switch with working touch. `wifi_userland.py` adapts this
upstream policy to **com.apple.wifid only**, preserves all other jobs and
properties, validates the stock program/startup/Mach-service identity, and
keeps the binary cache's exact length with offset-table padding. The fresh
Redfin root builder applies it after the generic root tweaks. No invented
Apple DT node or legacy `wifi=1`/modem path is introduced. The existing-root
update was backed up, bounded to its freshly resolved file allocation and
verified by full readback. The subsequent authenticated capture confirms
wifid executes once, discovers en0 and issues Apple80211 capability, power
and channel queries before the GUI cap. Manual Settings connection and
actual network data remain unverified.

After the user reports the same gray switch, the manual capture confirms
88 contacts/releases, two Preferences executions and the same ten initial
wifid driver queries, without a scan/power-set/join request before shutdown.
The next diagnostic adapts the same upstream `mkjobs.py` stdout/stderr and
`OS_ACTIVITY_DT_MODE=YES` policy to wifid alone. It is an explicit opt-in;
fresh-root preparation retains the normal logging policy. Equal binary
plist containers are shared to fit the additional keys within the current
file size, with full decoded-tree verification and preserved unrelated jobs.
This adds evidence, not speculative replies for optional Apple80211 ioctls.

Reviewed 2026-10-24: pinned Google SEC source
`0701b191882dc408104ad8af9e2f5eb2bf34c297`, `sec_ts.c:330..430`, retries
completed reads with bad sync/echo/checksum; `:2337..2350` clears a lost
event queue. Redfin's event session now distinguishes a malformed completed
reply from a GENI fault. It releases held contacts, drops the uncertain
queue with the existing bounded clear, and requires a validated empty reply.
It never replays consumed events. Hardware errors, ownership loss, failed
clear and a bad resynchronization reply remain final. This adapts native SEC
semantics; the preferred kernel's Goodix IC protocol is not substituted.

Reviewed 2026-10-23: the same pinned kernel's `redwood_adreno.c` step9
reads CB0, while step13 prepares a separate GMU context1. Redfin's new
explicit read-only CB0/1 observer uses native Lito's 64KiB resource, global
offset0x8000 and 4KiB context pages. It reads two stable passes, never follows
inherited TTBRs and introduces no context writes, firmware or iOS ABI change.
Hardware observes both translations disabled, faults zero and nonzero
residual configuration. This is observation, not a context-ownership grant.

Rechecked 2026-10-23: kernel HEAD remains `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`.
Userland now has HEAD `a79ff0772a3454fd1ef127e181e5b3bce6c9ce18`; its two
functional additions are `fcc3214` (thermald/bootok) and `a79ff07`
(standalone thermal probe). Reviewed changes cover thermal polling/sysctl,
pressure notifications, the launchd job and boot guard; they do not add an
A620 backend or update the private iOS16.5 graphics ABI. They depend on
`kern.redwood.thermal` and the upstream custom root/var-store, so they are not
installed into Redfin's Apple launchd/HFS root. The older paired source pin
below remains the graphics-ABI reference. The existing `redwood_adreno.c`
steps5/6 confirm clocks are enabled before GMU CSR inspection; step11 compares
PAS_SUPPORTED for known images and warns that all-zero responses alone can
be inconclusive. Redfin's raw4/13 query responses remain zero, not a successful
firmware-authentication result.

| | Upstream snapshot | Redfin |
| --- | --- | --- |
| Platform | POCO X5 Pro/redwood, SM7325, Adreno 642L, WCN6750 | Pixel 5, SM7250, Adreno 620v2, legacy ICNSS/MPSS WLAN path |
| Apple userland | iOS 16.5, 20F66, iPhone10,3 | iOS 16.7.16, 20H392, iPhone10,3 |
| XNU base | 8796.121.2 | 8796.141.3 |
| Root setup | Custom stage0/init, APFS volumes and recreated `/var` | Apple launchd, persistent journaled HFSX |

`inject.c`, `inject_sb.c` and `inject_media.c` contain 20F66 shared-cache
addresses; `eagl_slots.txt`, HID callbacks and Apple80211 structures also
describe private 16.5 interfaces. A matching model identifier does not prove
ABI compatibility. No injection, private-ABI replacement or prebuilt dylib
should be enabled before a separate 20H392 ABI proof. Their injection also
depends on `kern.exec_inject` and permissive dyld/AMFI policy; accepting an
unsigned executable does not grant its entitlements.

The root builder and daemon deny list are not suitable replacements for our
working boot. LaunchServices already passed Redfin's observed MobileGestalt
Wi-Fi identity wait; upstream provides no demonstrated additional fix or
LS database seed for that problem. Its job tools are useful as read-only
Mach-service/provider and OS/App-cryptex availability audits.

Reviewed 2026-10-24 against the actual 20H392 userland: MobileGestalt's
Bluetooth address data helper at `0x19c56883c` reads
`IODeviceTree:/chosen/mac-address-bluetooth0` through the CFData-checked
property helper `0x19c55b368`. Without it, it tries the IOService name
`bluetooth` and the factory `BMac` path, then repeats while neither exists.
The IOServiceMatching/IOServiceNameMatching/GetMatchingService calls were
resolved against the same cache's IOKit exports. The user's newly reported
About/Wi-Fi pane freezes are consistent with that missing identity; an
actual blocked Settings stack has not yet been captured. The existing
Wi-Fi chosen-property policy is extended with a separate stable six-byte
local-unicast Bluetooth identity, without importing Apple hardware nodes or
publishing a BT driver. The preferred upstream snapshots remain the source
reference, but no matching 20H392 identity-wait fix was found there. This
is a local ABI adaptation, not proof of functional Bluetooth or GUI Wi-Fi.
The subsequent manual test still freezes both panes; the identity fallback
is not established as their active blocker. The next local diagnostic uses
XNU's existing resident-only frame reader and scheduler lock to copy only
nonrunnable waiting threads, with a 200ms total budget. It does not import
upstream's single-core sampling assumptions into the eight-core GUI.

Reviewed again 2026-10-24 at preferred kernel
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`:
`xnu/files/iokit/Kernel/MiniIONetworkStack.cpp` documents and implements
the exact newly observed block. Actual Redfin waiting stacks show
`SCNetworkInterfaceCopyAll` → `__wait_for_IOKit_to_quiesce` →
`SCDynamicStoreNotifyWait` in wifid, while Preferences waits in
`MobileWiFi::_wifi_manager_open`. Apple's configd tag1241.140.6, commit
`3e58490132f08916564af041ed1c818514a01a46`, independently confirms
InterfaceNamer's stackCallback opens IONetworkStack before quietCallback
can publish the ready network state. Redfin now adapts upstream's minimal
IONetworkStack and user client under IOResources, in its existing WLAN
registry translation unit. It starts before the native WLAN interface is
published. Native BSD KPI already assigns en0, so unsupported naming writes
are refused as in upstream; no synthetic dynamic-store ready key or
userland binary patch bypasses the real InterfaceNamer flow. Runtime
validation succeeds: configd opens the service, both waiting snapshots
contain no IOKit-quiescence wait, wifid issues scan/join requests, and the
native station completes WPA2 association/four-way exchange and bidirectional
Ethernet traffic. The user confirms Settings connection and actual internet.

## Five porting targets

Kernel source references below are relative to `xnu/files/`; userland C
sources are under `userland/src/` in the respective pinned repository.

1. **GENI FIFO transport reference for SEC touch.**
   Kernel `bsd/dev/redwood_goodix.c:263` provides clock/DFS/GENI sequencing,
   and `:507` bounds FIFO operations. Local `SE_IRQ_EN` status enables at
   `:437` are needed even when polling with the GIC IRQ masked. Re-derive
   Lito SE0 clocks, pins, SPI mode 3 and SEC framing from [TOUCH.md](TOUCH.md)
   and [TOUCH-SPI.md](TOUCH-SPI.md); do not copy Goodix firmware, reset or
   power operations. The normalized input queue (`redwood_input.c:113`)
   and `rwtouch` can inform later replay tests, but the userland HID bridge
   needs its own ABI proof. Do not import the loader-return escape gesture
   or the hardware-starting `redwood_input_init()` wholesale.

2. **IOSurface allocation fallback, after observing a required format.**
   Kernel `iokit/Kernel/MiniIOSurface.cpp:460` substitutes BGRA when allocating
   `w30r`, `l10r`, `w30R` surfaces, and one-plane BGRA for `b3a8`; it does not
   convert existing packed pixel bytes. These names are absent from SweetSurface.
   First capture the actual 20H392 request, prove callers honor the reported
   format, and verify layout/stride/bounds before extracting this fallback. This is
   not evidence that our current BGRA path needs changing, nor permission
   to replace the existing IOSurface ABI.

3. **BSD networking and a serialized station boundary.**
   Kernel `bsd/sys/redwood_net.h`, `bsd/dev/redwood_net.c:292` and
   `bsd/sys/redwood_sta.h` separate Ethernet frames/ifnet from radio work.
   `iokit/Kernel/RedwoodWLAN.cpp` publishes the properties configd and wifid
   use for Wi-Fi discovery and DHCP. Adapt these only after Redfin firmware,
   association, keys and the frame path work; the WCN6750/ath11k backend is
   not Redfin's ICNSS/MPSS backend. Re-derive Apple80211 ioctl layouts for
   20H392 and remove the one-link/fixed-`en0` assumption before USB coexistence.
   The bounded QMI codec (`redwood_qmi.c:388`, `:526`, `:844`) is a separate
   candidate behind a Redfin QRTR transport; upstream host checks do not
   prove that transport. Userland `net_test.m`, `keychain_test.c` and
   `wifipw_test.c` provide layered validation. Verify the handwritten
   IPConfiguration MIG ABI; let configd own DHCP when its service exists.

4. **Mesa/freedreno's Darwin GPU contract, after an A620 backend.**
   Kernel `iokit/Kernel/RedwoodGPU.cpp:733`/`:930` and userland
   `tools/mesa/redwood-drm/` describe buffer allocation/mapping, submission
   and fences for Mesa. They require a working **Redfin Adreno 620 backend**:
   source-proven power/GMU/firmware sequencing, owned SMMU mappings, bounded
   submission and verified RAM output; see [GPU.md](GPU.md). Upstream's
   SC7280/642L `redwood_adreno.c` and a660 firmware are incompatible with
   A620 bring-up. This custom msm-DRM-like bridge is not an implementation
   of Apple's IOGPU ABI. Keep inherited `gpu=0` until the separate hardware
   contract is proved.

5. **A separate CPU OSMesa experiment, planned only.**
   `gl_osmesa.c:95` recognizes softpipe/llvmpipe and declines GPU surface
   import; `eagl.c:674`/`:795` demonstrate ordinary IOSurface CPU upload and
   BGRA readback. This path has **no A620 prerequisite**. The first proposed
   contract is our own standalone `libGL` wrapper and executable drawing a
   coloured quad into an owned CPU buffer with checked pixel output.
   No wrapper or experiment has been implemented or installed. It does not
   require Apple filesystem writes, daemon injection or renderer changes.
   Adapting the private EAGL table and our SweetSurface/display path would
   be later, separately proved work; no performance improvement is assumed.

Keep the prototype Metal plugin unadvertised. It lacks major operations,
and publishing Metal capability changes CoreAnimation's renderer choice.
Upstream's workaround for missing system metallibs modifies a 16.5 static
device array; it is not a portable Redfin fix. There is no new XNU DWC3
driver in these snapshots: loader/UEFI USB transport does not replace the
Redfin PHY, clock and DMA work in [USB.md](USB.md).

## A620 GMU memory/context adaptation — 2026-10-24

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`,
`redwood_adreno.c` step13 and `space_on()`: clean owned tables, program a
disabled context, synchronize TLB, publish S2CR then valid SMR, and verify
hypervisor-mediated readback. Redfin now adapts this sequence to the native
64KiB aperture, CB1, stream5/mask `0x400`, A620 firmware memory map and
native noncached page attributes. Global controls and foreign routes stay
outside the write interface; initial faults are refused rather than cleared.

Native Google msm `500b3a2059c1eec0fec08ec56add06320ea901a8` was rechecked
for `arm-smmu.c` context setup, mandatory atomic ATS1PR writes and PAR
interpretation, `arm-smmu-regs.h` FSR fault/FORMAT separation, and
`io-pgtable-arm.c` 39-bit/4KiB/36-bit-PA NC walks. The Lito DT remains pinned
at `afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`. XNU supplies wired zeroed
contiguous allocations and verified physical pairs; no bootloader TTBR or
upstream A660 firmware is reused. The private inventory's A650-family GMU
image is bound by recorded SHA256 before power writes.

The preferred userland snapshots remain `a79ff0772a3454fd1ef127e181e5b3bce6c9ce18`
and `906425b75e02b4f99eb5d7bb1ef7c9583472d772`; this stage does not change
their ABI or publish graphics capability. CM3/GX stay stopped while the
memory profile verifies every payload and owned ATS translation. Native
firmware execution/HFI, GPU command output and the actual20H392 graphics
bridge remain unfinished; see [GPU-SMMU.md](GPU-SMMU.md).

After memory-v1's TCM readback refusal, rechecked native
`adreno_a6xx_gmu.c:a6xx_gmu_fw_start`: cold boot writes `GENERAL_7=1` before
loading TCM. Redfin schema2 includes that retained-memory prerequisite and
keeps the preferred upstream step13 mapping/ATS before step14 TCM transfer.
Upstream step16's AOP-programmed PDC must still not be copied: A620's native
`pdc_in_aop` is false, and native RSC hidden TCS data is `0x80000000`, unlike
upstream's `0x80000021`. Those differences are review findings for the later
CM3 startup, not hardware changes in this memory profile.

The v1/v2 failures exposed a local adaptation error, not an upstream defect:
`space_on()` uses a single-instruction `wr()` asm, whereas the local combined
barrier/store string incorrectly used semicolon separators. Darwin dropped
everything after the first semicolon. Word and atomic ATS helpers now use
newlines; actual Darwin ARM64 opcode checks cover both widths and zero
values, including the separate native XNU object. Readback ownership guards
remain unchanged; no HYP permission or register-mask bypass was added.

Memory-v3 confirms real CB1 stores but TCR2 retains reserved bits6:5.
Schema3 now compares native active TCR2/TCR/SCTLR fields and retains full
observed words for later exact audits. Native `arm-smmu.c` only programs
CONTEXTIDR for AArch32 short descriptors; that unused store is removed from
the AArch64 sequence. The inherited snapshot value stays audited. Tests
include the captured reserved-bit behavior and refusal of altered PASIZE,
walk cacheability, TTBR1 ASID selection, stall and memory-type override.

Native hardware memory-v4 also reports SCTLR.ASIDPNE RAZ (`0x1027→0x27`),
with all other active controls accepted. Schema4 records that readback and
continues requiring TCR2.AS, TTBR0 ASID1 and TCR.A1=0. The preferred
upstream checks SCTLR.M rather than whole-word ASIDPNE equality; the local
fault/IRQ/stall/endian/memory-type checks remain more explicit.

Memory-v5 accepts the full owned context/route sequence but generic ATS
returns PAR0. Rechecked the native `arm_smmu_device_cfg_probe()` condition:
SMMUv2 ID0.ATOSNS bit26 disables generic translation operations; Redfin's
captured `0x4c017e05` sets it. Native `qsmmuv500_iova_to_phys_hard` uses
the separate TBU ECATS path. Schema5 therefore skips unsupported generic
ATS, preserving explicit unavailability rather than inventing a successful
translation or accessing a new TBU debug range. DMA proof remains for
actual CM3/HFI traffic or a separately adapted native ECATS implementation.

Authenticated source54e9dbe/memory-v6 now passes owned memory/context/route
and all7firmware payload readbacks with CM3 reset held. No new upstream
commit or userland ABI was imported. The next adaptation remains native
A620 PDC/RSC (not the AOP-programmed upstream variant), CM3 completion and
fresh HFI traffic; readback alone is not claimed as DMA/Metal support.

## Display fit and camera geometry review — 2026-10-23

Rechecked both pinned HEADs in the table above. Kernel
`iokit/Kernel/MiniIOMobileFramebuffer.cpp:583`, `:603` and `:723` implement
pixel-center bilinear sampling, checked source rectangles and projection of
the complete logical canvas onto the physical panel. Redfin's older CPU path
instead cropped at source 20,48 and ignored source rectangle dimensions.
`display-fit.patch` now applies the reviewed scaling policy to Redfin's
existing SweetSurface and 20H392 swap record. It does not import the upstream
MiniIOSurface/IOFramebuffer ABI, injection code or a different device identity.

A case-insensitive search for `notch`, `cutout` and `safe.?area` in the pinned
kernel's `xnu/files` and userland's `userland/src` found no dedicated override.
The full-canvas scaler is published; a dedicated camera-cutout fix has not
been identified in these public snapshots.

The physical front-camera exclusion is independently source-backed by
Google's [Redfin Android overlay](https://android.googlesource.com/device/google/redfin/+/62df7438508565dfc05fab923e84f0704f5a0f07/redfin/overlay/frameworks/base/core/res/res/values/config.xml#208),
reviewed at commit `62df7438508565dfc05fab923e84f0704f5a0f07`.
The Apache-2.0 resource specifies a radius-40 circle centered at 81,77 and
the conservative rectangle `[0,145) × [0,136)`, anchored to the left edge.
Its portrait status-bar height is also 136px. `redfinfit=2` therefore fits the
complete 1125×2436 iPhone X canvas into 1017×2204 pixels at 31,136 and paints
the margins black. `redfinfit=1` fits into the complete panel without the
camera exclusion. Both modes inverse-map SEC touch through the same checked
viewport. The default remains the legacy crop.

Nine host tests pass, including actual patched presentation/HID methods,
independent bilinear pixels, immutable guarded source memory, clipping,
malformed extents, margin gestures and ASan/UBSan. Physical alignment,
rounded corners and on-device scaling throughput remain unverified;
[DISPLAY.md](DISPLAY.md) records the exact contract and next bounded test.

## Native GPU and Wi-Fi firmware boundaries — 2026-10-23

The preferred HackiOS snapshots remain unchanged. Their GPU/Mesa and network
interfaces are the later integration targets, while native Lito dependencies
are derived from the pinned Google sources above. Commits `de80451` and
`13f403b` add the A620 GMU firmware/HFI planner and reset-held 200MHz
clock/counter/TCM helper; `52137f3` corrects its CX proof to use the live-DT
separate hardware-status register. These helpers have host validation;
GMU firmware execution, GPU commands and rendering are not established.

Commit `05f371f` validates Redfin's native MPSS firmware layout and PAS4
lifecycle. The private base-vendor inventory has 35 program headers/33 load
segments/31 assets and a 0x8c000000+0x11800000 reserved span. Its endpoint
0x9d800000 does not overlap Redfin's actual 0xa0000000 splash reservation.
This adapts native ICNSS/MPSS dependencies; upstream Redwood WPSS/PAS6 and
ath11k are different hardware. See [WiFi.md](WiFi.md) and [GMU.md](GMU.md).

Reviewed again, 2026-10-23: kernel
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`, `redwood_image.c` and
`redwood_wifi.c` step6. Their resident plain-firmware mechanism informs the
separate Redfin MPSS source probe. Redfin keeps its bounded flat segment,
native PAS4 layout, original PHDR indices, complete live exclusions and
read-only source lease; it does not import Redwood's APFS dependency,
WPSS/PAS6 destinations or WCN6750 radio backend. Local build144832 and host
preflight establish the new source-only profile; hardware results belong
in NOTES.md, independently of upstream's stage descriptions.

## Native PIL integration review — 2026-10-23

Continued the preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
`redwood_wifi.c` review for its serialized worker and later GLINK/QRTR stages.
Redfin's actual MPSS boot remains derived from Google msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`: `peripheral-loader.c`,
`subsys-pil-tz.c`, `scm.c`, `msm_bus_arb_rpmh.c` and
`msm_bus_fabric_rpmh.c`. Reviewed Lito bus definitions at DT commit
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4`, `qcom/lito-bus.dtsi`,
and verified every selected route/member against the saved live Redfin FDT.

The native peripheral loader passes region_start to PAS metadata init;
metadata-at-MPSS-base is therefore source-backed. The two PIL bandwidth
clients require six APPS BCMs (CE0/SN6/SN0/SH0/MC0/ACV), with native CMD-DB
geometry and the APPS ACV bit. Redfin now implements these before its
PAS4/SMP2P boot sequence; Redwood's PAS6/RF backend is not substituted.
Software/native-build results and pending device execution are recorded
separately in NOTES.md. Upstream's WLAN/ifnet remains a later consumer.

The subsequent hardware run proves all native bandwidth/AOP prerequisites
but stops on transition to an extra initial PAS shutdown. Re-reviewing the
same Google's native cold PIL confirms INIT/MEM_SETUP is first. Redfin's
corrected caller therefore stages metadata in an explicitly reserved high-RAM
scratch page and requires SMC64; it grants MPSS write authority only after
successful same-session INIT/MEM_SETUP. This adapts metadata storage to
Redfin's high-only XNU RAM and removes the unneeded cold shutdown. The scratch
pointer's acceptance by TrustZone is still a device question; native code and
the preferred HackiOS PAS6 result cannot establish it for MPSS4.

The corrected high metadata route is now verified by Redfin PAS4 INIT,
MEM_SETUP, complete copy/readback, AUTH and a new SMP2P ready/handover0x6.
For the following transport work, re-reviewed the same preferred kernel's
`redwood_wifi.c` GLINK/QRTR frame and worker interfaces alongside Google's
native `qcom_glink_smem.c`. Redfin binds its own live PID1, IPCC2/signal0,
SMEM478/479/480 and IPCRTR, using bounded allocation/rings and a continued
native ready lease. No Redwood WPSS geometry is imported. The first stage
discovers QRTR/WLFW services; its hardware evidence is recorded separately.

Native GLINK/IPCRTR/QRTR is now observed on Redfin, including bidirectional
HELLO and remote servreg/sysmon announcements. Legacy ICNSS additionally
needs APPS pd-mapper/TFTP, which the preferred WCN6750/WPSS backend does not
provide. Reviewed Sapphire's host-service wire contracts in0121 and the
captured native `modemuw.jsn`, retaining only bounded servreg/TFTP logic and
the actual Redfin WLAN domain. Partition tables, UFS/EFS/RMTFS, pool addresses
and assignment code are excluded. The captured WLAN files stay private and
read-only; base-vendor compatibility remains a live firmware question. The
preferred kernel's WLFW/QMI framing and native `icnss_qmi.c` inform the next
CAP0x24 query, without importing ath11k/WCN6750 hardware or radio settings.

After the first host-service hardware run, reviewed native IPA's
`drivers/platform/msm/ipa/ipa_v3/{ipa.c,ipa_i.h}` at the same Google pin.
Its SMP2P response uses complete bit0/APPS clock-vote bit1. Redfin's absent
APPS IPA vote can be acknowledged once through the owned outbound entry,
without asserting an aggregate power reading or touching IPA registers.
The live FDT's IPA entry/consumer-bit route is bound explicitly. The saved
modemr.jsn root_pd metadata adds only its actual servreg/GPS services; absent
PDR/dump services are preserved. The previous root metadata and the reviewed
Sapphire IPA wire behavior are cross-checks, not replacement hardware IDs.

RMTFS review, 2026-10-23: Google pin's
`drivers/uio/msm_sharedmem/msm_sharedmem.c` and `secure_buffer.c`, plus
[linux-msm/rmtfs b30a3eb38f9af283f18dbd3c7755653efc52c094](https://github.com/linux-msm/rmtfs/tree/b30a3eb38f9af283f18dbd3c7755653efc52c094)
`qmi_rmtfs.{h,c}`, `rmtfs.c`, `sharedmem.c`. Redfin's UIO client1 allocates
0x280000bytes dynamically, then shares HLOS/MSS permissions; its reg0 is not
an MMIO/RAM address to reuse. Allocation replies are64bit, IOVEC physical
fields32bit. The next observer returns explicit unavailability only: it
cannot grant a handle, DMA buffer or storage access. No upstream partition
table, EFS writer, ignored assignment failure or guessed pool is imported.
The extra captured base-vendor JSONs contain no PDR-enable/dump-disable
service; those absent responses remain grounded in the actual inventories.

RMTFS implementation review after hardware OPEN demand, 2026-10-23: the same
Google `msm_sharedmem.c` chooses HLOS3/MSS_MSA15, permissions6, for Redfin's
client1 without `qcom,vm-nav-path`. Its `secure_buffer.c`, `secure_buffer.h`
and `scm.c` establish two 24-byte destination records, seven arguments and
the ARM64 extended-argument buffer for MP0x0c/ASSIGN0x16. No NAV permission
or inherited Sapphire pool is used. The linux-msm/rmtfs pin above supplies
the OPEN/CLOSE/ALLOC/IOVEC/GET_DEV_ERROR wire contracts and read-only shadow
semantics. Their partition contents and storage writer are not imported.
Four native Redfin partitions are captured twice through verified offline
recovery; only private, hash-bound snapshots and volatile shadows enter the
temporary image. A top-down free-DRAM allocation is checked against the
actual live FDT, Image, DTB and XNU RAM by the shim before zeroing/claiming
the guarded low buffer. Assignment failures remain failures; buffers and
mappings remain retained until the platform resets. Hardware results are
recorded separately in NOTES.md.

Legacy WLFW setup review, 2026-10-23: Google pin
`500b3a2059c1eec0fec08ec56add06320ea901a8`, `icnss.c`, `icnss_qmi.c`,
`wlan_firmware_service_v01.{c,h}` and `include/linux/soc/qcom/qmi.h`.
The observed CAP error90 is `QMI_ERR_INCOMPATIBLE_STATE_V01`. Native order
is IND_REGISTER0x20 (client0x4b4e454c), MSA_INFO0x2d, MSA_READY0x2e,
then CAP0x24. MSA_INFO has at most two13-byte wire records. Redfin's
captured live ICNSS references `pil_wlan_fw_region@8ba00000`,2MiB,
`removed-dma-pool`/`no-map`; `qcom,hyp_enabled` is absent. The native driver
therefore skips `hyp_assign_phys` for this fixed MSA. The new optional QMI
handshake preserves that behavior, validates every returned subregion, and
does not map/zero MSA on the CPU or enable WLAN clocks, supplies or mission
mode. The shim independently requires that exact fixed reservation in its
actual FDT hardware view before validating the handoff. Reviewed preferred
kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`, `redwood_wlfw.c`:
its WCN6750 indication/HOST_CAP/CAP order is useful protocol context, but
does not replace Redfin's legacy MSA exchange or native client/instance IDs.

ICNSS supply review after CAP succeeds, 2026-10-23: the same pinned
`icnss_get_vreg_info`, `icnss_vreg_on`, `icnss_get_clk_info` and
`rpmh-regulator.c` establish the consumer/provider split. Actual Redfin
overrides `vdd-cx-mx-config` to0/0 (provider init voltage352mV) and both
3.3V-chain requests to3000..3312mV. XO/RFA use native1800/1304mV defaults.
All five providers are PMIC5 LDO VRM resources with native LPM selector4;
the optional XO pin clock has no live DT binding. CAP TLV0x1b is the optional
signed32-bit chain capability; native ICNSS skips chain1 for value1.
The observer binds these exact DT inputs and reads the five named VRM
records twice through the already-owned read-only CMD-DB mapping. Queued
inherited TCS entries retain their enabled/idle metadata; they are not a
measurement of current aggregate regulator outputs. No WLAN VRM/PMIC/clock
write is added in this observation stage.

The subsequent native observer confirms VRM addresses40800/42100/41d00/
41a00/41900 for ldoa1/ldoa14/ldoc2/ldoc11/ldoc10, aux0x100/4bytes and
zero priorities. The optional power profile pins these exact records and
the reviewed PMIC5 provider/consumer sequence: final352/1800/1304/3000/
3000mV requests, native LPM mode4, then enable1 for each selected supply.
CX352mV emulates its provider initialization, which native ICNSS's0/0
consumer override preserves. Missing chain capability retains native two
chains; reported1x1 omits chain1. Only the already-owned DRV2 ACTIVE slot is
used, with the base ARC/BCM/AOP ledger retained and the same live MPSS child
checking every write/poll. Uncertain requests remain held until reset.

After the first power run accepted all15 requests without FW_READY,
reviewed the same native `wlfw_dynamic_feature_mask_send_sync_msg` and
generated codec. Native defaults register rejuvenation TLV0x19/u32=1 and,
after power, send message0x3b/TLV0x10/u64 mask1. Response previous/current
masks are independent optional u64 fields. The power-only profile now
performs that exchange; valid QMI errors remain recorded without changing
the separately successful CAP identity. Native rejuvenation indication0x39
quarantines this bounded epoch until platform reset instead of claiming an
unperformed recovery. Pin-result indications preserve their actual fields.

## Physical WLAN PMIC observation review — 2026-10-24

Rechecked Google's native ICNSS post-CAP order at
`500b3a2059c1eec0fec08ec56add06320ea901a8`: supplies/optional clock, then
dynamic feature mask. Those requests already succeed on Redfin; their ACKs
do not establish physical regulator outputs. At the same pin,
`spmi-pmic-arb.c` supplies v5 EE0 observer offsets, duplicate-APID selection
and EXT_READL encoding; `qpnp-revid.h` identifies PM8150/PM8150L subtypes
`1e/1f`. Rechecked `pm8150.dtsi`/`pm8150l.dtsi` at DT pin
`afc98e2bb0716a57bf4f8d2b6191378dd7123ce4` against the saved live SIDs0/1/4/5.

Re-reviewed Qualcomm firmware
`20bb8ae36c93fc16bbadda0e0a83f930c0c8a271`:
`pm_config_common.c`, `pm_ldo_driver.c` and `pm_pwr_alg.c`. Its explicit
type-LDO/subtype>=30 branch establishes the unified raw register layout,
including configured40/41 and VALID42/43 mV, mode45, enable46 and status08.
The common4000/stride100 map and already observed SID1 ordering support the
PM8150 candidates. SID5's WLAN supply pages remain candidate attribution;
this firmware is not a Redfin target table or authorization for a regulator
write. The new optional observer reuses the existing SPMI mappings and
checks the live native MPSS child before every read command/poll. It adds
no PMIC/GPIO/clock write, RSC vote, memory assignment or readiness policy.

The first authenticated physical run reads SID4 `0x2751`, so its `pm8150l`
live-DT label does not establish the PM8150L identity `0x1f51`. Rechecked
the Google pin's `qpnp-revid.c` and Linux v6.12 commit
`adc218676eef25575469234709c2d87185ca223a`
`include/soc/qcom/qcom-spmi-pmic.h`; neither names subtype27. The revised
raw observer pins the authenticated `0x2751` identity without assigning an
unverified model name. The per-peripheral type/subtype check still controls
the generic unified read layout; neither model matching nor a DT label
grants power policy or new PMIC write authority.

After all PMIC snapshots succeed without FW_READY, rechecked native ICNSS
`register_fw_error_notifications`/`register_early_crash_notifications` at
the same Google pin. The actual FDT maps inbound SMP2P entry `wlan` bit0
to force-error-fatal and bit1 to early-crash. The bounded peer parser already
reads/validates both complete stable snapshots, including this entry; it now
retains its raw presence/index/value for diagnostics. No additional SMEM or
MMIO read, interrupt registration, acknowledgement, recovery or readiness
decision is added. A zero value remains distinct from an absent entry.

MSA diagnostic review, 2026-10-24: the same native `icnss_qmi.c`
`msa_ready_ind_cb` preserves optional hang-data offset/length, caps it at
400 bytes and maps that firmware-announced window. `icnss.c` copies it on
an early crash. Redfin now retains the optional fields and has a separate
opt-in timeout observer. Its pure planner requires successful MSA/CAP and
an accepted nonsecure region covering every whole16KiB mapped page, while
the fixed reservation remains shim verified. It rejects secure, missing,
overlapping, oversized, partial-page or unaccepted windows. The native
adapter maps only that bounded read-only Normal-NC alias, takes two samples,
and releases only its local alias. It introduces no MSA clearing, permission
assignment, DMA grant, power write or readiness decision. Default setup and
PMIC profiles do not perform this MSA CPU read.

Reviewed Linux v6.12 `adc218676eef25575469234709c2d87185ca223a`
`drivers/net/wireless/ath/ath10k/{qmi.c,snoc.c}` after the zero hang result.
For WCN3990, this client sends HOST_CAP daemon_support0 and, after MSA,
downloads the selected BDF and sends CAL_REPORT before firmware readiness.
Native Google's kernel ICNSS flow does not contain those transfers, so its
Android userspace host service and actual Redfin board selection are the
next references. No generic ath10k BDF, CRC-error workaround, permission
assignment or hardware geometry has been imported by this comparison.

## Redfin DMON/BDF reference review — 2026-10-24

Google redbull `3595d0b214eeeddf87e2c37477e3e74f831eca82`
`init.hardware.rc` starts `/vendor/bin/cnss-daemon -n -l`. Statically
reviewed that Redfin binary from TheMuppets' pinned
`proprietary_vendor_google_redfin` commit
`30c82c83bc03b0dfc83dd6d6a041f51fc35ebfab`, SHA256
`9d38f1d7cf6b1b34e6f03fefbfd87135eb5938f1573e65fefeb3dad905318af7`.
It remains private/ignored and was never executed or installed. Its embedded
mini-debug symbols identify `wlfw_adrastea_init`, registration, CAP,
BDF_DOWNLOAD and CAL_REPORT, permitting a bounded disassembly review.

The daemon registers a distinct DMON client `444d4f4e`, waits for MSA,
queries CAP and sends BIN BDF before its calibration report. Its
`wlfw_send_bdf_download_req` at f590 selects prefix `bdwlan-u` for the
actually observed chip4320. With absent-board fallbackff it tries hardware,
revision/radio variants then `bdwlan-u-redfin.bin`; only that canonical
fallback and the separate non-u file exist in the captured base listing.
The new profile binds the canonical26328-byte u file and its captured SHA256,
without claiming the unproved active Android/COW or OTA-config view.
Native BIN messages use file_id0, full original total_size, sequential
segments, type0 and a final end flag. The empty calibration list explicitly
reports no cache; cal_remove_supported0 matches the native default.

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
`redwood_wlfw.c`'s resident-file/QMI transfer interface. Redfin uses its own
legacy BIN ABI and full total_size rather than Redwood's ath11k remaining-
size/ELF convention or board IDs. Chunks2048 fit the established Redfin
QRTR queue and are within the native6144-byte variable-data limit.
The bounded DMON profile subscribes to FW/MSA only (the mainline notification
subset) and promises no calibration download/update or persistent cache.
Every ACK must succeed, including final CRC; no CRC-error exemption, retry,
mission mode, new memory assignment, DMA or partition writer is added.

## Native SNOC data-plane entry review — 2026-10-24

Reviewed Linux v6.12 `adc218676eef25575469234709c2d87185ca223a`
`ath10k/snoc.c:932..1105`, `qmi.c:380..505`, and native Google msm
`500b3a2059c1eec0fec08ec56add06320ea901a8`
`icnss.c:2372..2394`/`icnss_qmi.c:1358..1437`. The source order is
power, WLAN_CFG, acknowledged WLAN_MODE mission, optional read-index
memory, CE initialization, then interrupt/RX servicing. Firmware readiness
alone is not permission to access WLAN registers or use inherited rings.

Re-reviewed the preferred kernel snapshot
`8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
`wifi/lx/src/lx_bus.c` and `lx_80211.c`: retain its separation between
bus servicing, station/WPA2 and Ethernet/iOS layers, adapting the ath10k
SNOC backend instead of its WCN6750 ath11k windows, MSI or ring ABI.
The station layer remains a later consumer of a proven packet path.

The captured native ICNSS binding is WLAN `18800000+800000`, APPS SMMU
SIDc0/mask1, host IOVA `a0000000+10000000`, and12 CE SPIs. Its named
IPA IOVA aperture `b0000000+10000` is separate; neither it nor the retained
RMTFS allocation grants CE RAM. APPS SMMU has no optional clock/static-CB
binding in this capture and is independently readable in the bounded USB
profile. The new post-readiness observer pins that established layout,
double-reads every SMR/S2CR and each CB's SCTLR/CBAR/CBA2R/FSR, and counts
latent references even when the SMR is invalid. It never reserves a CB,
changes routes, acknowledges faults, touches TCU/TBU/CE or authorizes DMA.

The follow-on explicit mission profile uses native WLFW WLAN_CFG23 and
WLAN_MODE22 with successful matching ACKs, transaction6/7 on the existing
kernel port. The12 target-pipe,21 service-pipe (including native sentinel)
and12 legacy shadow-register entries match Linux's WCN3990 tables and the
inherited `xnu/patches/0122` layout. Reviewed native QMI descriptors confirm
one-byte array counts, five serialized u32 fields per target entry, and
u16 CE/offset pairs; host-only reserved fields are not on the wire.
Mission0/hw_debug0 follow native ICNSS. Unknown/failed ACKs never grant CE
access. Fresh complete SMMU snapshots retain WLAN unmatched and preserve
the foreign routes/contexts before/after both requests.

Reviewed ath10k `hw.c:190..337`/`ce.c` at the same pinned Linux commit and
inherited `0123`'s mission-before-CE entry. Only after mission ACK and a
100ms settling interval, serviced by the same GLINK worker, may the adapter
double-read the12 CE banks at WLAN+240000 and the wrapper. This is still
a read-only register observation, with no ring/RRI programming, buffers,
host route, DMA or station registration. The preferred upstream's bus/
station separation remains the software reference for the packet stage.

[kernel]: https://github.com/oosexgang/hackios-xnu-kernel/tree/8e61187098f2c26c5daee8f9f72b6416aa64b9ab
[userland]: https://github.com/oosexgang/hackios-xnu-userland/tree/906425b75e02b4f99eb5d7bb1ef7c9583472d772

## Complete native packet/station/GUI composition — 2026-10-24

Reused the preferred kernel's pinned `bsd/dev/redwood_{net,sta,apple80211}.c`,
`bsd/sys/redwood_{net,sta}.h`, `iokit/Kernel/RedwoodWLAN.cpp` and
`wifi/lx/src/lx_wpa.{c,h}`. The adapted Redfin sources retain the serialized
station requests, BSD Ethernet boundary, Apple80211 events/ioctls and
SystemConfiguration registry discovery. Interface units/names are selected
from free BSD names instead of assuming en0. The IOCTL layouts originate
from upstream's iOS16.5 review; their actual20H392 behavior is still a device
validation item. No Apple binary or daemon from another release is copied.

The inherited `TopazModem.cpp` already contains ath10k-compatible
CE/HTC/WMI/HTT, scan, management, association and Ethernet code from
patches0122/0123/0129/0130. A narrow native callback boundary reuses those
software layers while Redfin owns PAS4, GLINK, power, MMIO and memory.
The legacy modem startup, fixed E0000000 pool, SM6225 SMMU/WLAN addresses
and filesystem firmware/EFS paths remain disabled by modem0/wifi0.
Redfin WMI uses the actual service-ready RF-chain count (at most two).
The preferred WPA2 engine adds its checked lengths, MIC/nonce/replay/key
unwrap and group-key path; duplicate message3 retransmits message4 without
reinstalling keys. Join names/keys are not printed by the native join path.

The WLAN-only context adapts the reviewed native non-static allocator and
the proven USB AArch64 bypass sequence: retain all latent references,
claim one disabled unreferenced NS bank and one invalid stream slot, then
disable SCTLR, set CBA2R1/CBAR10000, publish TRANS and finally SIDc0/mask1.
Each uncertain write or foreign-state change stops without retry/release.
Reviewed again2026-10-24 after the actual WLAN refusal: native FSR
FORMAT[10:9] reports AArch642 (`0x400`) immediately after CBA2R.RW64=1.
The already validated `usb-context-format-status.patch` accounts for this
read-only status. WLAN now predicts that same field only in its owned bank;
all fault bits, other owned fields and foreign contexts remain exact. No
FSR acknowledgement or new store is introduced. The actual-C/C++ lease
model now emulates this hardware side effect, rather than a plain RAM bank.
The separate16MiB DMA32 buffer has two16KiB guards; its complete proposed
range is checked against the actual Image/DTB, XNU, all live reservations
and retained RMTFS before the shim initializes it. RMTFS is never spare CE
RAM. Native callbacks admit only the host CE fields, owned ring addresses
and three reviewed TX shadows; firmware-side ring geometry stays intact.

Reviewed again2026-10-24: Linuxv6.12 `ce.h` defines WCN3990's
`CE_DESC_ADDR_MASK=GENMASK_ULL(34,0)`; `ce.c` posts masked addresses and
returns RX through the saved transfer context. The native Redfin receive
guard now compares those address bits to its exact posted buffer while
retaining the actual2048-byte bound. The CPU uses only its own buffer
pointer. Upper completion control/metadata is not a new DMA pointer.
The completion barrier precedes remaining descriptor/payload loads; rejected
descriptors log length, raw address/flags and the expected posted address.

Reviewed again2026-10-24 after real HTC/WMI/HTT, ifnet publication and scan:
native `snoc.c:host_ce_config_wlan` distinguishes the host side of each CE
from its live firmware side. Runtime audits now protect only the host's
source/destination base/size and the owned CTRL1 subfields, plus the separate
host RRI address. Firmware-owned ring configuration and indices remain live;
CTRL1 writes must preserve the current unowned bits. Whole APPS SMMU and
DMA guards stay exact. Refusals identify the responsible SMMU/CE/RRI field.
Native `wmi-tlv.h:wmi_tlv_rdy_ev` confirms the24-byte ABI/MAC/status layout;
the observed zero firmware MAC is not a private-ABI offset fix. One local
unicast address is chosen for this boot when firmware supplies no usable
address, consistently before vdev/station/ifnet publication. A nonzero READY
status never grants native readiness.

Read-only userland review2026-10-24 at `906425b75e02b4f99eb5d7bb1ef7c9583472d772`:
`userland/src/net_test.m` supplies getifaddrs/SystemConfiguration, DNS/TCP/TLS
checks and a bounded interface wait. Its `wifi` job keys off legacy `wifi=1`
and uses a handwritten IPConfiguration MIG20011 fallback only when configd
has no service. Redfin GUI deliberately keeps legacy wifi0; the companion
job/prebuilt is therefore not imported as-is. Stock service discovery must
be assessed before introducing that optional fallback, and its20H392 Mach
layout remains a separate validation item. No helper/job or Apple binary
is installed by this review.

Reviewed again2026-10-24 after station-v7: QMI's native target table declares
CE5 PIPEDIR_OUT (target destination, HTT/IPA); live firmware changes its
destination base to MSA after HTT setup. Redfin's APPS/IPA-disabled profile
therefore leaves both CE5 rings to firmware, neither posts nor polls host RX
there, and uses one shared host-ring table in the software and hardware owner.
Native CE5/6 without APPS queues receive no CTRL1/RRI-enable writes either.
Station-v8b also observes firmware installing CE8's destination in MSA.
Native target comments identify CE8 as target-to-uMC and CE11 as autonomous
qcache; this profile requests no pktlog/diagnostic consumers. APPS now owns
only HTC/WMI/HTT queues0..4 and HTT receive9/10, leaving5/6/7/8/11 entirely
untouched. The readonly audit reports all mismatched owned fields together
before refusing, while retaining resources and issuing no additional DMA
doorbells. These native files are pinned at Linuxv6.12
`adc218676eef25575469234709c2d87185ca223a`.
The generic host_ce_config_wlan CE5 receive entry is not suitable authority
for this observed mission profile. The exact-source CE model now checks
that CE5's firmware registers are preserved, plus real RX and TX code paths.
Native `ce.c:shadow_sr_wr_ind_addr` independently confirms the existing
0/3/4 shadow addresses32000/3200c/32010; QMI array order is not their index.

The pinned SEC source's IO_RETRY_CNT3 and1ms retry wait now apply only to
discarded queue-resynchronization reads, after releasing held contacts.
Live coordinate batches are never replayed. The two-CS open HID-session read
keeps preemption disabled with CPU IRQs enabled and existing bounded GENI
loops. A measured gap accompanies invalid replies; scheduling latency is
still a candidate, not a proven Wi-Fi cause.
XNU8796 `clock.c:_clock_delay_until_deadline_with_leeway` confirms that
`delay()` can block; preemption-disabled callers select `machine_delay_until`.
This applies to sensing initialization as well as subsequent event reads.

GUI2 composes these resources with the existing GUI8 root/display/touch
profile. It uses the same bounded boot-argument length, frozen CPU/root
checks and cached shim return. Touch completes its DRV2 power setup first;
then a permanently bound CPU0 WLAN worker imports that stable handoff,
retains the established votes and services GLINK/RMTFS and packet rings
throughout the GUI run. Other CPUs submit queued station/frame requests.
The existing ordinary GUI1 and diagnostic profiles keep their own gates.
No GPU/Metal work is moved ahead of working GUI Wi-Fi.
## Native90Hz bridge pairing and system-library API correction — 2026-10-25

Preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab and userland
906425b75e02b4f99eb5d7bb1ef7c9583472d772 remain pinned. Rebuild both
Redfin loader/EAGL adapters with the current shared GUI-profile header;
store its digest and adapter-source digests with the verified Mesa bundle.
An old profile rejects90Hz before insertion even when the kernel/panel pass.

Actual20H392 Photos initWithPhotoLibraryURL: and
createOrUpgradeLibraryUsingOptions:error: supply the ordinary system Media
library's native creation/upgrade path. Its native well-known identifier0
is intentional and cannot be used in the named-library class methods.
Retain the native URL/canonical path guards and propagate native failures.
CoreServices8d42103dbd59308d9d2c2082b39738e7 supplies the async LS launch
selector/configuration and BOOL/NSError completion ABI; FrontBoardServices
exports the native foreground/unlock option keys. Unattended captures
request the ordinary no-passcode transition and preserve authorization or
lock failures in the result. No passcode bypass, schema synthesis or
account operation is added. App/window-server survival still needs a real run.



## Native GMEM and Redfin SSC integration review — 2026-10-25

Re-reviewed preferred kernel8e61187098f2c26c5daee8f9f72b6416aa64b9ab
`bsd/dev/redwood_adsp.c` and shared Wi-Fi/AOP/SMEM ownership. Retain its native
PAS/ready/GLINK/QRTR sequence and avoid LPASS MMIO. Redfin instead uses its
actual40MiB reservation0x89200000, PAS1, remote2,443/429 and IPCC3/0,3/2.
One existing CPU0 WLAN owner services both remotes; typed LCX/LMX votes preserve
CMD-DB/inherited floors and use the established RSC/AOP manager. Foreign TCS
and modem heap state remain intact. Firmware uses readonly private root bytes,
complete hash checks/readback and actual signed PAS authentication; a failed
phase cannot publish sensors or retry uncertain hardware.

Preferred userland906425b75e02b4f99eb5d7bb1ef7c9583472d772 remains the
AIR/Metal/EAGL source. Mesa25.0.7 native freedreno GMEM/resource dependencies
and actual batch counters replace Redfin's forced sysmem/per-draw barrier.
Counters are read only under the paired serialized context after its real
fence, using freedreno's own context-access discipline. The two-pass guarded
pixel probe validates actual producer/consumer visibility on the device.

SSC wire contracts reviewed from Qualcomm definitions at
Rivko/android-firmware-qti-sdm67020bb8ae36c93fc16bbadda0e0a83f930c0c8a271
and Android CHRE77beed6007208e42009a789eab55df13f9069e0b see/sns_qmi_client.
QMI400/v1, native protobuf SUID discovery, real attribute/rate/availability,
registry fragment readback, integer-only units and counter epochs are adapted
without inventing identities or samples. Firmware/calibration and extracted
JSNs remain private. Google msm500b3a2059c1eec0fec08ec56add06320ea901a8
`drivers/input/misc/vd6281/vd6281_module.c`/`i2c-qcom-geni.c` are reviewed
for the still-unimplemented separate VD6281 path; SSC does not claim it.


## Imported linear GMEM backing and native submission timing — 2026-10-25

Preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab` and userland
`906425b75e02b4f99eb5d7bb1ef7c9583472d772` remain the reviewed sources.
Re-reviewed the latter's `tools/mesa/redwood-drm/redwood_drm.c` native
IOKit call boundary and its paired AIR/Metal command execution. Observe
actual allocation/submit calls without changing requests, results or fence
semantics; snapshots are process totals, and encode time can include internal
blocking submissions. The Redfin WLAN metadata handoff now explicitly
preserves/restores CPU0 binding using the existing shared GUI owner helpers;
all radio writes remain on its established separate CPU0 worker.

Mesa 25.0.7, archive SHA256
`592272df3cf01e85e7db300c449df5061092574d099da275d19e97ef0510f8a6`,
`src/freedreno/fdl/fd6_layout.c` explicitly requires a 16x4 GMEM transfer
footprint. Imported linear storage in `freedreno_resource.c` instead records
stride times actual height, while `a6xx/fd6_resource.cc` accepts the linear
modifier without enforcing padded backing. For an attachment whose real
allocation cannot cover the rounded four-row transfer, select actual A620
sysmem rendering even when a debug GMEM request is set. Preserve the original
BO mapping/guards and retain GMEM for sufficiently backed attachments. The
native Metal checker exercises the observed 1065x282/BPR4288/1212416-byte
shape and requires actual pixels, retained tail guards and counter-proven
sysmem routing. Matching the previous fault to this old surface's BO remains
a hypothesis until actual runtime evidence establishes it.


## Native HFI lifetime and Metal backlog/attachment state — 2026-10-25

Re-reviewed preferred kernel `8e61187098f2c26c5daee8f9f72b6416aa64b9ab`
and userland `906425b75e02b4f99eb5d7bb1ef7c9583472d772` against the
observed V16 failure. Native HFI carries a 12-bit request sequence; its ring
indices and every exchange remain bounded. Redfin's diagnostic sent>=64 and
messages>=128 guards incorrectly imposed a boot lifetime on runtime DVFS.
Use independent64-bit observation totals and a 1..4095 sequence cycle with
one outstanding request, bounded stale-queue drain and exact native echoed
header/consumer checks. An actual refusal is logged as such rather than
reported as an absent ACK. No failed request is retried or falsely completed.

The paired AIR base-level attachment contract is unchanged. Cache its native
pipe_surface with the texture, preserving actual resource/reference lifetime
through command completion and dropping local references on partial creation
failure. Mesa25.0.7 freedreno_state.c:fd_set_framebuffer_state dirties all
framebuffer/draw state when those surface identities change; an identical
render target need not recreate that state at every draw.

Keep the real Metal superclass's requested command-buffer allocation capacity.
Bound only the executor's admitted work to one running plus one queued
command, applying backpressure at commit. Enter its completion group before
publishing Committed, covering admission waits as well as the real GPU fence;
return admission only after execution exits. Preserve native queue ordering,
work/resources and completion callbacks; never drop an old queued frame.
