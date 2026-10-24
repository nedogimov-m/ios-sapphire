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
jobs and all unrelated backboardd properties, installs this loader and
migrates only our known diagnostic job to System/Library/LaunchDaemons.
Both the on-disk job and launchd's binary cache must agree. Cache updates
keep their original length; existing roots require fresh extents/preimages,
offline staging, readonly native fsck and complete device readback.

`graphics-eagl.patch` supplies the native AMFI dyld-policy query solely to
backboardd in the exact GUI3 profile. The existing Sandbox/entitlement policy
is retained. Kernel builds can use the `redfin` board profile in the xnu
GitHub Actions workflow; its artifact includes the full source fingerprint.

Acceptance requires authenticated output for the exact boot ID: runtime
GPU submissions/fences, two shader/IOSurface pixel passes and backboardd
EAGL frames with real draws. A published service, a successful host build,
an installed bridge or a visible CPU-rendered GUI does not establish this.
This EAGL path does not implement Metal application support.

After a graphics panic the root can have pending HFS transactions. The older
strict RW publication gate requires a clean primary header, so it prevents
HFS from reaching its own replay. GUI3 alone now has a separate read-only
preflight for this installed root's initialized internal journal. It checks
both volume headers, the exact journal location, the native ring/header
bounds and checksum. Native HFS receives the original dirty header and
replays its own transactions; no clean bit or journal pointer is rewritten
by the preflight. The existing16GiB UFS write fence remains in force.
