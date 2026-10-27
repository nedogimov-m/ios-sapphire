"""One source inventory for full and runtime-only Metal pairing."""
import hashlib
from pathlib import Path


def metal_sources(root,upstream):
    ROOT=Path(root);upstream=Path(upstream)
    metal_sources=[upstream/'userland/src'/name for name in
                   ('redwoodmetal.m','redwooddrawable.m','redwood_drawable.h')]
    metal_sources += [ROOT/'ports/redfin'/name for name in
                      ('metal_userland.py','metal_raster_userland.py','metal_resource_userland.py','metal_blit_userland.py','metal_buffer_userland.py','metal_completion_userland.py','metal_buffer_texture_userland.py','metal-buffer-view-object.inc','metal-resource-completion.inc','metal-buffer-object.inc','iosurface-abi.h','metal-blit-encoder.inc','metal-raster.h','metal-guard.m','metal-check.m','metal-raster-check.inc','metal-vertex-check.inc','metal-blit-check.inc','metal-buffer-check.inc','metal-buffer-texture-check.inc','metal-alpha-check.inc','metal-check.metal')]
    metal_sources += [ROOT/'ports/redfin'/name for name in ('metal_function_constants_userland.py','metal-function-constants-object.inc','metal-function-constants.h','metal-function-constants-check.inc')]
    metal_sources += [ROOT/'ports/redfin'/name for name in ('metal-resource-check.c','metal-resource-check.ll')]
    metal_sources += [ROOT/'ports/redfin/graphics-memory-report.h']
    metal_sources += [ROOT/'ports/redfin/metal-half-check.inc']
    metal_sources += [ROOT/'ports/redfin'/name for name in
                      ('metal-translation-cache.h','metal-cache-check.inc')]
    metal_sources += [ROOT/'ports/redfin'/name for name in
                      ('metal-ordering.h','metal-ordering-check.inc')]
    metal_sources += [ROOT/'ports/redfin'/name for name in
                      ('metal-bindings.h','metal-bindings-check.inc')]
    metal_sources += [ROOT/'ports/redfin'/name for name in
                      ('metal_queued_userland.py','metal-queued.h','metal-queued-check.inc','metal-queued-resource-check.inc','metal-frontend-profile.h')]
    metal_sources += [ROOT/'ports/redfin/metal-ubo-extents-check.inc']
    metal_sources += [ROOT/'ports/redfin/metal-physical-check.inc']
    metal_sources += [ROOT/'ports/redfin/metal-surface-cache-check.inc']
    metal_sources += [ROOT/'ports/redfin/compositor-policy.h',ROOT/'ports/redfin/gui-profile.h']
    metal_sources += [ROOT/'ports/redfin/surface-padding.h',ROOT/'ports/redfin/surface-padding-check.inc']
    metal_sources += [ROOT/'ports/redfin/retained-memory.h']
    metal_sources += [ROOT/'ports/redfin'/name for name in
                      ('metal-scheduling.h','metal-scheduling-check.inc')]
    return metal_sources


def metal_pairing(root,upstream,fingerprint):
    return hashlib.sha256(fingerprint.encode()+b''.join(
        p.read_bytes() for p in metal_sources(root,upstream))).hexdigest()


def metal_plugin_command(root,clang,sdk,metal,binary):
    root,metal=Path(root),Path(metal)
    return [clang,'-target','arm64-apple-ios16.0','-isysroot',sdk,
        '-bundle','-O2','-fno-omit-frame-pointer','-Wno-deprecated-declarations',
        '-Werror=incompatible-pointer-types','-Werror=incompatible-function-pointer-types',
        '-I'+str(metal),'-I'+str(root/'ports/redfin'),metal/'redwoodmetal.m',metal/'redwooddrawable.m',
        root/'ports/redfin/metal-guard.m','-framework','Foundation','-framework','CoreFoundation',
        '-framework','IOKit','-framework','Metal','-framework','IOSurface','-lobjc','-o',binary]
