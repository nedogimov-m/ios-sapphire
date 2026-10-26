/* SPDX-License-Identifier: MIT */
/* Fresh owned pixels only. The caller decides eligibility before allocation;
 * a live cached allocation is never remapped with different attributes. */
static IOBufferMemoryDescriptor *sweet_redfin_owned_memory(uint32_t bytes,
    bool write_combined)
{
    IOBufferMemoryDescriptor *memory = NULL;
    if ((uint64_t)OSAddAtomic64(bytes, (volatile SInt64 *)&sweet_surface_wired) +
        bytes <= SWEET_SURFACE_WIRED_MAX) {
        IOOptionBits options = kIODirectionInOut | kIOMemoryKernelUserShared;
        if (write_combined) options |= kIOMapWriteCombineCache;
        memory = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
            options, bytes, page_size);
    }
    if (memory && memory->getLength() != bytes) OSSafeReleaseNULL(memory);
    if (!memory) OSAddAtomic64(-(SInt64)bytes, (volatile SInt64 *)&sweet_surface_wired);
    return memory;
}
