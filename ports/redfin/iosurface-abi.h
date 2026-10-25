/* SPDX-License-Identifier: MIT */
/* Public C IOSurface ABI used by iOS16.7.16. Some current iOS SDKs expose
 * only its Objective-C headers; this C diagnostic needs these seven calls. */
#ifndef REDFIN_IOSURFACE_ABI_H
#define REDFIN_IOSURFACE_ABI_H
#include <CoreFoundation/CoreFoundation.h>
#include <mach/kern_return.h>
#include <stdint.h>
#include <stddef.h>
typedef struct __IOSurface *IOSurfaceRef;
extern const CFStringRef kIOSurfaceWidth,kIOSurfaceHeight,kIOSurfaceBytesPerRow;
extern const CFStringRef kIOSurfaceBytesPerElement,kIOSurfaceAllocSize,kIOSurfacePixelFormat;
extern IOSurfaceRef IOSurfaceCreate(CFDictionaryRef);
extern uint32_t IOSurfaceGetID(IOSurfaceRef);
extern void *IOSurfaceGetBaseAddress(IOSurfaceRef);
extern size_t IOSurfaceGetAllocSize(IOSurfaceRef);
extern size_t IOSurfaceGetBytesPerRow(IOSurfaceRef);
extern size_t IOSurfaceGetWidth(IOSurfaceRef);
extern size_t IOSurfaceGetHeight(IOSurfaceRef);
extern size_t IOSurfaceGetPlaneCount(IOSurfaceRef);
extern size_t IOSurfaceGetBytesPerElement(IOSurfaceRef);
extern uint32_t IOSurfaceGetPixelFormat(IOSurfaceRef);
extern uint32_t IOSurfaceGetSeed(IOSurfaceRef);
extern size_t IOSurfaceGetBytesPerRowOfPlane(IOSurfaceRef,size_t);
extern void *IOSurfaceGetBaseAddressOfPlane(IOSurfaceRef,size_t);
extern kern_return_t IOSurfaceLock(IOSurfaceRef,uint32_t,uint32_t *);
extern kern_return_t IOSurfaceUnlock(IOSurfaceRef,uint32_t,uint32_t *);
#ifndef IOSURFACE_TYPES_H
enum {kIOSurfaceLockReadOnly=1};
#endif
#endif
