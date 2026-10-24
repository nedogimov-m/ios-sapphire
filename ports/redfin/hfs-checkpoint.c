/* SPDX-License-Identifier: MIT */
/* Offline seed for the stock 20H392 MobileCheckpoint cache. Use only on an
 * unmounted staging image. The caller audits allocations and runs native
 * readonly fsck before installing any changed ranges on the device. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
/* The pinned HFS library predates Darwin's current stat header guards. Its
 * equivalent definitions must not collide with the SDK's macro spellings. */
#undef S_ISTXT
#undef UF_COMPRESSED
#include <hfs/hfsplus.h>
#include <hfs/hfslib.h>

#define XML "/System/Library/CoreServices/Checkpoint.xml"
#define CACHE "/private/var/mobile/Library/Caches/Checkpoint.plist"
#define PARENT "/private/var/mobile/Library/Caches"
#define LIMIT (1024 * 1024)
char endianness;

static int plain_file(const HFSPlusCatalogRecord *record)
{
    if (!record || record->recordType != kHFSPlusFileRecord) return 0;
    const HFSPlusCatalogFile *f = (const HFSPlusCatalogFile *)record;
    return (f->permissions.fileMode & 0170000) == 0100000 &&
        !(f->permissions.ownerFlags & UF_COMPRESSED) &&
        f->dataFork.logicalSize && f->dataFork.logicalSize <= LIMIT && !f->resourceFork.logicalSize;
}

static int same_bytes(Volume *v, HFSPlusCatalogFile *file, const void *bytes, size_t size)
{
    if (file->dataFork.logicalSize != size) return 0;
    io_func *raw = openRawFile(file->fileID, &file->dataFork, (HFSPlusCatalogRecord *)file, v);
    unsigned char *copy = malloc(size);
    if (!raw || !copy) return 0;
    int ok = READ(raw, 0, size, copy) && !memcmp(copy, bytes, size);
    free(copy); CLOSE(raw); return ok;
}

int main(int argc, char **argv)
{
    struct stat image;
    if (argc != 3 || lstat(argv[1], &image) || !S_ISREG(image.st_mode)) return 2;
    uint16_t one = 1;
    endianness = *(unsigned char *)&one ? IS_LITTLE_ENDIAN : IS_BIG_ENDIAN;
    FILE *input = fopen(argv[2], "rb");
    if (!input || fseeko(input, 0, SEEK_END)) return 3;
    off_t size = ftello(input);
    if (size <= 0 || size > LIMIT) return 3;
    rewind(input);
    unsigned char *bytes = malloc((size_t)size);
    if (!bytes || fread(bytes, 1, (size_t)size, input) != (size_t)size) return 3;
    rewind(input);
    io_func *io = openFlatFile(argv[1]);
    Volume *v = io ? openVolume(io) : NULL;
    if (!v || !(v->volumeHeader->attributes & 0x100) || (v->volumeHeader->attributes & 0x800)) return 4;
    HFSPlusCatalogRecord *r = getRecordFromPath(XML, v, NULL, NULL);
    if (!plain_file(r)) return 5;
    HFSPlusCatalogFile source = *(HFSPlusCatalogFile *)r;
    if (source.permissions.ownerID || source.permissions.groupID ||
        !same_bytes(v, (HFSPlusCatalogFile *)r, bytes, (size_t)size)) return 5;
    free(r);
    r = getRecordFromPath(PARENT, v, NULL, NULL);
    if (!r || r->recordType != kHFSPlusFolderRecord) return 6;
    free(r);
    r = getRecordFromPath(CACHE, v, NULL, NULL);
    unsigned created = r == NULL;
    if (!created) {
        if (!plain_file(r)) return 7;
        HFSPlusCatalogFile *f = (HFSPlusCatalogFile *)r;
        if (f->permissions.ownerID != 501 || f->permissions.groupID != 501 ||
            (f->permissions.fileMode & 07777) != 0644 || f->contentModDate != source.contentModDate ||
            !same_bytes(v, f, bytes, (size_t)size)) return 7;
        fclose(input);
    } else {
        if (!add_hfs(v, createAbstractFileFromFile(input), CACHE)) return 8;
        r = getRecordFromPath(CACHE, v, NULL, NULL);
        if (!plain_file(r)) return 9;
        HFSPlusCatalogFile *f = (HFSPlusCatalogFile *)r;
        f->permissions.ownerID = f->permissions.groupID = 501;
        f->permissions.fileMode = (f->permissions.fileMode & ~07777) | 0644;
        /* Native HFS contentModDate is a 1904-epoch field. Copy it directly;
         * both stat nanoseconds are zero on this filesystem. */
        f->contentModDate = source.contentModDate;
        if (!updateCatalog(v, r)) return 10;
    }
    free(r);
    r = getRecordFromPath(CACHE, v, NULL, NULL);
    if (!plain_file(r)) return 11;
    HFSPlusCatalogFile *f = (HFSPlusCatalogFile *)r;
    if (f->permissions.ownerID != 501 || f->permissions.groupID != 501 ||
        (f->permissions.fileMode & 07777) != 0644 || f->contentModDate != source.contentModDate ||
        !same_bytes(v, f, bytes, (size_t)size)) return 11;
    uint32_t cnid = f->fileID;
    free(r);
    r = getRecordFromPath(XML, v, NULL, NULL);
    if (!r || memcmp(r, &source, sizeof(source)) ||
        !same_bytes(v, (HFSPlusCatalogFile *)r, bytes, (size_t)size)) return 12;
    free(r); free(bytes);
    closeVolume(v);
    if (fflush((FILE *)io->data) || fsync(fileno((FILE *)io->data))) return 13;
    CLOSE(io);
    printf("{\"created\":%u,\"cnid\":%u,\"bytes\":%lld,\"uid\":501,\"gid\":501,"
           "\"mode\":420,\"content_mod_date\":%u,\"mtime_nsec\":0,\"source_unchanged\":true}\n",
           created, cnid, (long long)size, source.contentModDate);
    return 0;
}
