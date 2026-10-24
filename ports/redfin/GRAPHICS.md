# Redfin system graphics

The working A620 service is a prerequisite, not system acceleration. GUI3
retains the eight-core GUI/touch/WLAN profile and the native GPU owner.
GUI1/2 remain the known CPU graphics checkpoints.

`build-graphics.py` builds the pinned Mesa25.0.7/IR3 source and the preferred
EAGL compositor bridge as one bundle. It needs the installed20H392 arm64
shared cache, its subcaches and paired `.symbols`, all kept outside git.
The build derives457 GL wrappers, EAGL method signatures and the relevant
QuartzCore vtable entry. It audits every nonweak import against that cache.
Downloaded sources and all generated binaries/ABI reports stay in research.

Stock OpenGLES indexes a native context; `getMacroContextPrivate` returns
native+32. QuartzCore's dispatch offsets are relative to that returned
pointer. The bridge preserves both bases and the reserved OpenGLES TLS key.
It checks the actual image UUIDs and every selected method before replacing
any method, and requires an ES3 context reporting an actual A620 renderer.
Its surface imports use SweetSurface's separate pixel descriptor, without
the leading state page used by the preferred kernel's MiniIOSurface.

The backboardd-only loader is `/redfin/lib/libredfin-graphics.dylib`.
`gpu_userland.patch_launchd_cache(...,system_eagl=True)` preserves all other
jobs and all unrelated backboardd properties and migrates only our known
diagnostic job to System/Library/LaunchDaemons. Stock launchd filters DYLD
variables from jobs. `graphics-exec.patch` therefore appends the fixed loader
environment entry in native exec, only for the exact GUI3 and Apple's
absolute backboardd path. Native argument/pointer bounds remain enforced.
The comparison consumes native `exec_save_path`'s `executable_path=` prefix;
`ip_strings` is an Apple-vector entry rather than a bare pathname.
Both the on-disk job and launchd's binary cache must agree. Cache updates
keep their original length; existing roots require fresh extents/preimages,
offline staging, readonly native fsck and complete device readback.

Both graphics jobs use the actual20H392 ActiveHardMemoryLimit and
InactiveHardMemoryLimit keys, bounded to512MiB. The older JetsamMemoryLimit
key is deprecated by this launchd. The shader process was otherwise killed
with JETSAM_REASON_MEMORY_PERPROCESSLIMIT before submitting work. Backboardd
and gpu-render also apply the native memorystatus setter when opening the
GPU in GUI3 and verify the effective512MiB ledger limit before allocating
client buffers. This changes only those two current tasks; native fatal
limits and all other processes' policy remain in force. The kernel records
the previous/effective limits and the first buffer allocation sizes.
Backboardd
runs as mobile and cannot open the root-owned console for its spawn actions.
Its output and the shader output go to two precreated mobile-owned files in
`/private/var/mobile/Library/Logs/`. Collect these files with the launchd log
from clean, unmounted recovery after each integrated boot, binding all
userspace evidence to the fresh boot nonce and real kernel fence records.

`graphics-eagl.patch` supplies the native AMFI dyld-policy query solely to
backboardd in the exact GUI3 profile. The existing Sandbox/entitlement policy
is retained. Kernel builds can use the `redfin` board profile in the xnu
GitHub Actions workflow; its artifact includes the full source fingerprint.

Acceptance requires authenticated output for the exact boot ID: runtime
GPU submissions/fences, two shader/IOSurface pixel passes and backboardd
EAGL frames with real draws. A published service, a successful host build,
an installed bridge or a visible CPU-rendered GUI does not establish this.
This EAGL path does not implement Metal application support.

The integrated74df960d04eda813 run meets those EAGL rendering requirements:
FD620/ES3.2, both boot-bound shader/IOSurface colors,11installed methods,
real shared-surface compositor frames through180 and completed fences
through at least768. No kernel panic or GPU/SMMU fault is observed. Its
frame logs still cost about140–300ms, with substantial handing-on/waiting
and surface-refresh time. Many wrapped-surface imports fall back to copies.
An orderly shutdown stops the GPU before backboardd exits, causing one
subsequent rejected submission and userland crash. These are remaining
performance/lifecycle problems; this milestone does not establish60fps.

The next complete performance batch avoids redundant affinity switches,
publishes dirty page-table/ring ranges as batches, retains complete stable
SMMU audits through read-only snapshot callbacks and uses the preferred
seed/4ms surface-push policy. Post-fence cache invalidation applies only to
GPU-written surfaces. Prepared wrapped surfaces include their native page
delta and keep the prepared descriptor/surface alive; read-only imports
keep read-only SMMU entries. Submission READ/WRITE/DUMP flags describe msm
dependency bookkeeping and do not change those permissions. Normal shutdown retires the GPU after
process exit. Aggregate native phase timings measure the remaining cost.

An image with `--userspace-waits` uses GUI3 to inspect MobilePhone,
MobileSlideShow, callservicesd and photolibraryd at the existing bounded
sampling points. Those diagnostic images exclude screen-log payloads.
The applications' observed startup stalls are not a Metal diagnosis.

Runtime callers now use the GPU mutex's thread lease on any of the eight
proved coherent CPUs; startup/claims remain on CPU0. The wait path reads
actual completion before testing its wall deadline and makes a final
guarded sample at timeout. GPU-written timestamp pairs distinguish core
execution from CPU scheduling. An actual missing fence or fault still
retires the queue with all uncertain DMA memory held until reset.
Touch retains its existing hardware session across an HID consumer close,
then discards stale contacts when the replacement backboardd registers.

The77fdfa764956dff4 complete run passes the stronger process-bound check:
over4096actual backboardd completions and900frames, both shader pixel
passes, no submission failure or window-server crash, and87clean touch
contacts/releases. GPU timestamps average roughly3.5ms per batch, with
another4.2ms in complete software audits. Simple warm frame samples cost
14–26ms; complex samples still reach40–100ms or more. HID reconnection is
host-verified; no consumer restart occurs in this successful hardware run.
Photos remains blocked in MCCopyCheckpointValue on its main thread.

After a graphics panic the root can have pending HFS transactions. The older
strict RW publication gate requires a clean primary header, so it prevents
HFS from reaching its own replay. GUI3 alone now has a separate read-only
preflight for this installed root's initialized internal journal. It checks
both volume headers, the exact journal location, the native ring/header
bounds and checksum. Native HFS receives the original dirty header and
replays its own transactions; no clean bit or journal pointer is rewritten
by the preflight. The existing16GiB UFS write fence remains in force.
