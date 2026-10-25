/* SPDX-License-Identifier: MIT */
/* Stage the reviewed GUI bundle in an ordinary private HFSX image. No device
 * path, deletion, compressed-file rewrite, truncation or metadata clean-bit
 * manipulation is supported. The caller must back up/read back/fsck the
 * full staged result before its separate bounded device update. */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <hfs/hfsplus.h>
#include <hfs/hfslib.h>

char endianness;
struct target {const char *path;unsigned uid,mode;};
static const struct target targets[]={
    {"/redfin/bin/photos-init",0,0755},
    {"/redfin/bin/gui-check",0,0755},
    {"/redfin/lib/libredfin-ui.dylib",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.photos-init.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.gui-check.plist",0,0644},
    {"/private/var/mobile/Library/Logs/redfin-ui.log",501,0600},
    {"/private/var/mobile/Library/Logs/redfin-gui-check.log",501,0644},
};
int main(int argc,char **argv)
{
    if (argc<4 || (argc-2)%2) return 2;
    struct stat image;
    if (lstat(argv[1],&image) || !S_ISREG(image.st_mode) || image.st_size!=16LL*1024*1024*1024) return 3;
    uint16_t one=1;endianness=*(unsigned char *)&one ? IS_LITTLE_ENDIAN : IS_BIG_ENDIAN;
    io_func *io=openFlatFile(argv[1]);if (!io) return 4;
    Volume *volume=openVolume(io);if (!volume) return 5;
    if (volume->volumeHeader->signature!=0x4858 || volume->volumeHeader->blockSize!=4096) return 6;
    for (int i=2;i<argc;i+=2) {
        const struct target *target=NULL;
        for (unsigned j=0;j<sizeof(targets)/sizeof(targets[0]);++j)
            if (!strcmp(targets[j].path,argv[i+1])) target=&targets[j];
        if (!target) return 7;
        struct stat source;
        if (lstat(argv[i],&source) || !S_ISREG(source.st_mode) || source.st_size<=0 || source.st_size>4*1024*1024) return 8;
        HFSPlusCatalogRecord *record=getRecordFromPath(target->path,volume,NULL,NULL);
        uint32_t old_id=0,old_blocks=0;HFSPlusExtentRecord old_extents;
        memset(old_extents,0,sizeof(old_extents));
        if (record) {
            if (record->recordType!=kHFSPlusFileRecord || target->uid==501) return 9;
            HFSPlusCatalogFile *file=(HFSPlusCatalogFile *)record;
            if (file->permissions.ownerID!=target->uid || file->permissions.groupID!=target->uid ||
                (file->permissions.fileMode&07777)!=target->mode || (file->permissions.ownerFlags&UF_COMPRESSED) ||
                file->resourceFork.logicalSize || (uint64_t)(source.st_size+4095)/4096<file->dataFork.totalBlocks) return 10;
            old_id=file->fileID;old_blocks=file->dataFork.totalBlocks;
            memcpy(old_extents,file->dataFork.extents,sizeof(old_extents));free(record);
        }
        FILE *input=fopen(argv[i],"rb");if (!input) return 11;
        if (!add_hfs(volume,createAbstractFileFromFile(input),target->path) ||
            !chmodFile(target->path,target->mode,volume) || !chownFile(target->path,target->uid,target->uid,volume)) return 12;
        record=getRecordFromPath(target->path,volume,NULL,NULL);
        if (!record || record->recordType!=kHFSPlusFileRecord) return 13;
        HFSPlusCatalogFile *file=(HFSPlusCatalogFile *)record;
        if (file->dataFork.logicalSize!=(uint64_t)source.st_size ||
            file->dataFork.totalBlocks!=(uint64_t)(source.st_size+4095)/4096 ||
            file->permissions.ownerID!=target->uid || file->permissions.groupID!=target->uid ||
            (file->permissions.fileMode&07777)!=target->mode || (old_id && old_id!=file->fileID)) return 14;
        for (unsigned j=0;j<8 && old_extents[j].blockCount;++j)
            if (file->dataFork.extents[j].startBlock!=old_extents[j].startBlock ||
                file->dataFork.extents[j].blockCount<old_extents[j].blockCount) return 15;
        printf("Staged %s bytes=%llu CNID=%u retained-blocks=%u allocated-blocks=%u\n",target->path,
            (unsigned long long)file->dataFork.logicalSize,file->fileID,old_blocks,file->dataFork.totalBlocks);
        free(record);
    }
    closeVolume(volume);CLOSE(io);return 0;
}
