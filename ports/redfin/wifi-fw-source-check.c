/* SPDX-License-Identifier: MIT
 * Host-only regular-file front end for the exact native source/planner.
 * Private source storage is guarded/read-only; no destination or device I/O.
 * macOS: cc -O2 wifi-fw-source-check.c wifi_fw_source.c -o /tmp/wifi-fw-source-check
 * Linux: add -lcrypto.
 */
#define _DARWIN_C_SOURCE 1
#define _GNU_SOURCE 1
#include "wifi_fw_source.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <CommonCrypto/CommonDigest.h>
#else
#include <openssl/sha.h>
#endif

struct host_source {
    int fd, leased;
    struct stat before;
    struct rf_wifi_fw_blob blob;
    struct rf_wifi_fw_layout layout;
    const uint8_t *data;
};
static struct redfin_mpss_workspace workspace;
static struct rf_wifi_fw_source source;
static struct host_source host;
static int same(const struct stat *a, const struct stat *b)
{
#if defined(__APPLE__)
    if (a->st_mtimespec.tv_nsec != b->st_mtimespec.tv_nsec || a->st_ctimespec.tv_nsec != b->st_ctimespec.tv_nsec) return 0;
#else
    if (a->st_mtim.tv_nsec != b->st_mtim.tv_nsec || a->st_ctim.tv_nsec != b->st_ctim.tv_nsec) return 0;
#endif
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_size == b->st_size &&
        a->st_mtime == b->st_mtime && a->st_ctime == b->st_ctime;
}
static int check(void *opaque, const struct rf_wifi_fw_blob *b, const struct rf_wifi_fw_layout *l)
{
    struct host_source *h = opaque;
    struct stat current;
    return h == &host && !fstat(h->fd, &current) && same(&h->before, &current) &&
        !memcmp(b, &h->blob, sizeof(*b)) && !memcmp(l, &h->layout, sizeof(*l)) ? 0 : -1;
}
static int pin(void *opaque, uint64_t physical, uint64_t reserved, const uint8_t **out)
{
    struct host_source *h = opaque;
    if (h != &host || h->leased || physical != h->blob.physical || reserved != h->blob.reserved ||
        check(h, &h->blob, &h->layout)) return -1;
    h->leased = 1; *out = h->data; return 0;
}
static void unpin(void *opaque)
{ if (opaque == &host) host.leased = 0; }
static int hash(void *opaque, const uint8_t *data, size_t bytes, uint8_t output[32])
{
    if (opaque != &host || !data || !bytes || bytes > REDFIN_MPSS_MAX_BUNDLE ||
        check(&host, &host.blob, &host.layout)) return -1;
#if defined(__APPLE__)
    if (!CC_SHA256(data, (CC_LONG)bytes, output)) return -1;
#else
    if (!SHA256(data, bytes, output)) return -1;
#endif
    return check(&host, &host.blob, &host.layout);
}
static int number(const char *text, uint64_t *out)
{
    char *end;
    if (!text[0] || text[0] == '-' || text[0] == '+' || text[0] == ' ') return -1;
    errno = 0; unsigned long long value = strtoull(text, &end, 0);
    if (errno || *end || (uint64_t)value != value) return -1;
    *out = (uint64_t)value; return 0;
}
int main(int argc, char **argv)
{
    struct redfin_mpss_range excluded[REDFIN_MPSS_MAX_EXCLUSIONS];
    if (argc < 7 || (argc - 3) % 2 || (argc - 3) / 2 > (int)REDFIN_MPSS_MAX_EXCLUSIONS || strlen(argv[2]) != 64) {
        fprintf(stderr, "usage: %s BUNDLE SHA256 KERNEL_BASE KERNEL_BYTES FRAMEBUFFER_BASE FRAMEBUFFER_BYTES [BASE BYTES ...]\n", argv[0]); return 2;
    }
    size_t count = (size_t)(argc - 3) / 2;
    for (size_t i = 0; i < count; ++i)
        if (number(argv[3 + 2 * i], &excluded[i].base) || number(argv[4 + 2 * i], &excluded[i].bytes)) return 2;
    for (unsigned i = 0; i < 64; ++i) {
        unsigned digit = (unsigned)(argv[2][i] - '0');
        if (digit > 9) { if (argv[2][i] < 'a' || argv[2][i] > 'f') return 2; digit = (unsigned)(argv[2][i] - 'a' + 10); }
        host.blob.sha256[i / 2] |= (uint8_t)(digit << (i % 2 ? 0 : 4));
    }
    host.fd = open(argv[1], O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
    if (host.fd < 0 || fstat(host.fd, &host.before) || !S_ISREG(host.before.st_mode) ||
        host.before.st_size < 64 || (uint64_t)host.before.st_size > REDFIN_MPSS_MAX_BUNDLE) {
        fprintf(stderr, "source must be a regular bounded bundle\n"); if (host.fd >= 0) close(host.fd); return 1;
    }
    host.blob.bytes = (uint64_t)host.before.st_size;
    host.blob.reserved = (host.blob.bytes + RF_WIFI_FW_PAGE - 1u) & ~(RF_WIFI_FW_PAGE - 1u);
    host.blob.physical = UINT64_C(0x184000000); host.blob.boot_id = 1;
    host.layout.ram = (struct redfin_mpss_range){UINT64_C(0x180000000), UINT64_C(0x80000000)};
    host.layout.kernel_end = UINT64_C(0x182000000);
    host.layout.adt = (struct redfin_mpss_range){host.blob.physical + host.blob.reserved, 4096};
    host.layout.arguments = (struct redfin_mpss_range){host.layout.adt.base + 4096, RF_WIFI_FW_BOOT_ARGS_BYTES};
    host.layout.top = (host.layout.arguments.base + RF_WIFI_FW_BOOT_ARGS_BYTES + RF_WIFI_FW_PAGE - 1u) & ~(RF_WIFI_FW_PAGE - 1u);
    size_t guard = (size_t)getpagesize(), mapped_bytes = (size_t)host.blob.reserved + 2u * guard;
    uint8_t *mapping = mmap(NULL, mapped_bytes, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
    int error = 1;
    if (mapping != MAP_FAILED) {
        uint8_t *data = mapping + guard;
        if (!mprotect(data, (size_t)host.blob.reserved, PROT_READ | PROT_WRITE)) {
            size_t offset = 0;
            while (offset < host.blob.bytes) {
                size_t take = (size_t)host.blob.bytes - offset;
                if (take > 65536) take = 65536;
                ssize_t got = read(host.fd, data + offset, take);
                if (got < 0 && errno == EINTR) continue;
                if (got <= 0) break;
                offset += (size_t)got;
            }
            host.data = data;
            if (offset == host.blob.bytes && !mprotect(data, (size_t)host.blob.reserved, PROT_READ)) {
                const struct rf_wifi_fw_source_ops operations = {&host, check, pin, unpin, hash};
                error = rf_wifi_fw_source_open(&source, &host.blob, &host.layout, excluded, count, &workspace, &operations);
                rf_wifi_fw_source_close(&source, &operations);
            }
        }
        munmap(mapping, mapped_bytes);
    }
    close(host.fd);
    if (error) { fprintf(stderr, "native source adapter rejected bundle: status=%d\n", error); return 1; }
    printf("{\"schema\":1,\"bundle_bytes\":%" PRIu64 ",\"bundle_sha256\":\"%s\",\"phdrs\":%u,\"segments\":%u,\"assets\":%u,"
        "\"metadata_bytes\":%u,\"memory_bytes\":%" PRIu64 ",\"file_bytes\":%" PRIu64 ",\"zero_bytes\":%" PRIu64
        ",\"signature_authenticated\":false,\"hardware_started\":false}\n",
        host.blob.bytes, argv[2], workspace.plan.phdrs, workspace.plan.segments, workspace.image.assets,
        workspace.plan.metadata_bytes, workspace.plan.memory_bytes, workspace.plan.file_bytes, workspace.plan.zero_bytes);
    return 0;
}
