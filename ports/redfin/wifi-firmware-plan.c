/* SPDX-License-Identifier: MIT
 * Host-only front end for the exact native Redfin MDT planner.
 * Reads a regular metadata file; performs no device I/O, firmware copy or PAS.
 */
#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE 1
#include "wifi_firmware.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int number(const char *text, uint64_t *value)
{
    char *end;
    if (!text[0] || text[0] == '-' || text[0] == '+' || text[0] == ' ')
        return -1;
    errno = 0;
    unsigned long long parsed = strtoull(text, &end, 0);
    if (errno || *end || (uint64_t)parsed != parsed) return -1;
    *value = (uint64_t)parsed;
    return 0;
}

static int changed(const struct stat *a, const struct stat *b)
{
#if defined(__APPLE__)
    if (a->st_mtimespec.tv_nsec != b->st_mtimespec.tv_nsec ||
        a->st_ctimespec.tv_nsec != b->st_ctimespec.tv_nsec) return 1;
#else
    if (a->st_mtim.tv_nsec != b->st_mtim.tv_nsec ||
        a->st_ctim.tv_nsec != b->st_ctim.tv_nsec) return 1;
#endif
    return a->st_size != b->st_size || a->st_mtime != b->st_mtime ||
        a->st_ctime != b->st_ctime || a->st_ino != b->st_ino || a->st_dev != b->st_dev;
}

int main(int argc, char **argv)
{
    struct redfin_mpss_range excluded[REDFIN_MPSS_MAX_EXCLUSIONS];
    struct redfin_mpss_plan plan, scratch;
    struct stat before, after;
    uint8_t metadata[REDFIN_MPSS_MAX_MDT];
    size_t count, bytes, done = 0;
    int fd, error;
    if (argc < 6 || (argc - 2) % 2 || (argc - 2) / 2 > (int)REDFIN_MPSS_MAX_EXCLUSIONS) {
        fprintf(stderr, "usage: %s modem.mdt KERNEL_BASE KERNEL_BYTES FRAMEBUFFER_BASE FRAMEBUFFER_BYTES [BASE BYTES ...]\n", argv[0]);
        return 2;
    }
    count = (size_t)(argc - 2) / 2;
    for (size_t i = 0; i < count; ++i) {
        if (number(argv[2 + i * 2], &excluded[i].base) ||
            number(argv[3 + i * 2], &excluded[i].bytes)) {
            fprintf(stderr, "invalid excluded range\n");
            return 2;
        }
    }
    fd = open(argv[1], O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) { fprintf(stderr, "cannot open metadata\n"); return 1; }
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size < 52 ||
        before.st_size > REDFIN_MPSS_MAX_MDT) {
        fprintf(stderr, "metadata must be a regular file of 52..65536 bytes\n");
        close(fd); return 1;
    }
    bytes = (size_t)before.st_size;
    while (done < bytes) {
        ssize_t got = read(fd, metadata + done, bytes - done);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) { fprintf(stderr, "metadata read failed\n"); close(fd); return 1; }
        done += (size_t)got;
    }
    if (fstat(fd, &after) || changed(&before, &after)) {
        fprintf(stderr, "metadata changed during read\n"); close(fd); return 1;
    }
    close(fd);
    error = redfin_mpss_plan(metadata, bytes, excluded, count, &plan, &scratch);
    if (error) { fprintf(stderr, "native MDT planner rejected input: status=%d\n", error); return 1; }
    printf("{\"schema\":1,\"pas_id\":4,\"metadata_bytes\":%u,\"phdrs\":%u,\"source_base\":%" PRIu64
        ",\"physical_base\":%" PRIu64 ",\"memory_bytes\":%" PRIu64 ",\"entry_address\":%" PRIu64
        ",\"file_bytes\":%" PRIu64 ",\"zero_bytes\":%" PRIu64 ",\"segments\":[",
        plan.metadata_bytes, plan.phdrs, plan.source_base, plan.physical_base,
        plan.memory_bytes, plan.entry_address, plan.file_bytes, plan.zero_bytes);
    for (uint32_t i = 0; i < plan.segments; ++i) {
        const struct redfin_mpss_segment *segment = &plan.segment[i];
        printf("%s{\"index\":%u,\"flags\":%u,\"source_address\":%u,\"file_bytes\":%u,\"memory_bytes\":%u,\"physical_address\":%" PRIu64 "}",
            i ? "," : "", segment->index, segment->flags, segment->source_address,
            segment->file_bytes, segment->memory_bytes, segment->physical_address);
    }
    puts("]}");
    return 0;
}
