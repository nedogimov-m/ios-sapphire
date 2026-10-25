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
    {"/redfin/bin/thermald",0,0755},
    {"/redfin/bin/network-check",0,0755},
    {"/redfin/bin/sensor-check",0,0755},
    {"/redfin/firmware/native-sensors.bundle",0,0600},
    {"/redfin/bin/gpu-render",0,0755},
    {"/redfin/lib/libOSMesa.8.dylib",0,0644},
    {"/redfin/lib/libglapi.0.dylib",0,0644},
    {"/redfin/lib/libredfin-ui.dylib",0,0644},
    {"/redfin/lib/libredfin-graphics.dylib",0,0644},
    {"/redfin/lib/libredfin-eagl.dylib",0,0644},
    {"/redfin/lib/libredfin-refresh.dylib",0,0644},
    {"/redfin/lib/libredfin-diagnostic.dylib",0,0644},
    {"/redfin/lib/libredfinair.dylib",0,0644},
    {"/redfin/lib/redfin-check.metallib",0,0644},
    {"/redfin/bin/metal-check",0,0755},
    {"/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal",0,0755},
    {"/System/Library/Extensions/RedfinMetal.bundle/Info.plist",0,0644},
    {"/System/Library/Extensions/RedfinMetal.bundle/_CodeSignature/CodeResources",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.metal-check.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.apple.backboardd.plist",0,0644},
    {"/private/var/mobile/Library/Logs/redfin-metal-check.log",501,0600},
    {"/System/Library/LaunchDaemons/com.redfin.photos-init.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.gui-check.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.thermald.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.network-check.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.sensor-check.plist",0,0644},
    {"/System/Library/LaunchDaemons/com.redfin.gpu-render.plist",0,0644},
    {"/private/var/mobile/Library/Logs/redfin-ui.log",501,0600},
    {"/private/var/mobile/Library/Logs/redfin-refresh.log",501,0600},
    {"/private/var/mobile/Library/Logs/redfin-gui-check.log",501,0644},
    {"/private/var/log/redfin-thermald.log",0,0600},
    {"/private/var/log/redfin-network-check.log",0,0600},
    {"/private/var/log/redfin-sensor-check.log",0,0600},
    {"/private/var/mobile/Library/Logs/redfin-native-tcc.log",501,0600},
    {"/private/var/mobile/Library/Logs/redfin-native-assetsd.log",501,0600},
};

/* This host HFS library writes overflow keys using physical block numbers;
 * native HFS expects logical fork offsets. New small programs must therefore
 * get one complete free run, never the allocator's fragmented first-fit path.
 * This changes only the ordinary allocation hint. The native allocator still
 * allocates/zeros every block and maintains its bitmap/counters; the caller
 * subsequently verifies complete extents and native readonly fsck. */
static int stage_contiguous(Volume *volume,uint32_t needed)
{
    uint32_t total=volume->volumeHeader->totalBlocks;
    if (total!=4194304 || !needed || needed>8192) return 0;
    size_t bytes=(total+7u)/8u;unsigned char *bitmap=malloc(bytes);
    if (!bitmap) return 0;
    if (!READ(volume->allocationFile,0,bytes,bitmap)) {free(bitmap);return 0;}
    uint32_t start=0,count=0;
    /* Leave room for ordinary catalog/extent-tree growth before file data. */
    for (uint32_t block=1;block<total-1;++block) {
        if (bitmap[block/8]&(0x80u>>(block%8))) {count=0;continue;}
        if (!count) start=block;
        if (++count==needed+16) {
            volume->volumeHeader->nextAllocation=start;free(bitmap);return 1;
        }
    }
    free(bitmap);return 0;
}

static int metal_directory(Volume *volume,int resources)
{
    const char *parent="/System/Library/Extensions";
    static const char *paths[]={"/System/Library/Extensions/RedfinMetal.bundle",
        "/System/Library/Extensions/RedfinMetal.bundle/_CodeSignature"};
    HFSPlusCatalogRecord *record=getRecordFromPath(parent,volume,NULL,NULL);
    if (!record || record->recordType!=kHFSPlusFolderRecord) {free(record);return 0;}
    HFSPlusCatalogFolder *folder=(HFSPlusCatalogFolder *)record;
    int valid=folder->permissions.ownerID==0 && folder->permissions.groupID==0;
    free(record);if (!valid) return 0;
    for (unsigned i=0;i<(resources ? 2u : 1u);++i) {
        const char *path=paths[i];
        record=getRecordFromPath(path,volume,NULL,NULL);
        if (!record) {
            if (!newFolder(path,volume) || !chmodFile(path,0755,volume) || !chownFile(path,0,0,volume)) return 0;
            record=getRecordFromPath(path,volume,NULL,NULL);
        }
        if (!record || record->recordType!=kHFSPlusFolderRecord) {free(record);return 0;}
        folder=(HFSPlusCatalogFolder *)record;
        valid=folder->permissions.ownerID==0 && folder->permissions.groupID==0 &&
            (folder->permissions.fileMode&07777)==0755;
        free(record);if (!valid) return 0;
    }
    return 1;
}
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
        int sensor_firmware=!strcmp(target->path,"/redfin/firmware/native-sensors.bundle");
        uint64_t maximum=sensor_firmware ? 32u*1024*1024 :
            (!strcmp(target->path,"/redfin/lib/libredfinair.dylib") || !strcmp(target->path,"/redfin/lib/libOSMesa.8.dylib")) ? 16u*1024*1024 : 4u*1024*1024;
        if (lstat(argv[i],&source) || !S_ISREG(source.st_mode) || source.st_size<=0 || (uint64_t)source.st_size>maximum) return 8;
        if(sensor_firmware) {
            HFSPlusCatalogRecord *parent=getRecordFromPath("/redfin",volume,NULL,NULL);
            if(!parent||parent->recordType!=kHFSPlusFolderRecord){free(parent);return 19;}
            HFSPlusCatalogFolder *folder=(HFSPlusCatalogFolder *)parent;
            int valid=folder->permissions.ownerID==0&&folder->permissions.groupID==0;
            free(parent);if(!valid)return 19;
            parent=getRecordFromPath("/redfin/firmware",volume,NULL,NULL);
            if(!parent) {
                if(!newFolder("/redfin/firmware",volume)||!chmodFile("/redfin/firmware",0700,volume)||
                    !chownFile("/redfin/firmware",0,0,volume))return 19;
                parent=getRecordFromPath("/redfin/firmware",volume,NULL,NULL);
            }
            if(!parent||parent->recordType!=kHFSPlusFolderRecord){free(parent);return 19;}
            folder=(HFSPlusCatalogFolder *)parent;
            valid=folder->permissions.ownerID==0&&folder->permissions.groupID==0&&(folder->permissions.fileMode&07777)==0700;
            free(parent);if(!valid)return 19;
        }
        int metal_resource=!strcmp(target->path,"/System/Library/Extensions/RedfinMetal.bundle/_CodeSignature/CodeResources");
        if ((!strcmp(target->path,"/System/Library/Extensions/RedfinMetal.bundle/RedfinMetal") ||
             !strcmp(target->path,"/System/Library/Extensions/RedfinMetal.bundle/Info.plist") || metal_resource) &&
            !metal_directory(volume,metal_resource)) return 18;
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
        uint32_t wanted=(uint32_t)((source.st_size+4095)/4096);
        if (wanted>old_blocks && !stage_contiguous(volume,wanted-old_blocks)) return 16;
        if (!add_hfs(volume,createAbstractFileFromFile(input),target->path) ||
            !chmodFile(target->path,target->mode,volume) || !chownFile(target->path,target->uid,target->uid,volume)) return 12;
        record=getRecordFromPath(target->path,volume,NULL,NULL);
        if (!record || record->recordType!=kHFSPlusFileRecord) return 13;
        HFSPlusCatalogFile *file=(HFSPlusCatalogFile *)record;
        if (file->dataFork.logicalSize!=(uint64_t)source.st_size ||
            file->dataFork.totalBlocks!=(uint64_t)(source.st_size+4095)/4096 ||
            file->permissions.ownerID!=target->uid || file->permissions.groupID!=target->uid ||
            (file->permissions.fileMode&07777)!=target->mode || (old_id && old_id!=file->fileID)) return 14;
        if (!old_id && (file->dataFork.extents[0].blockCount!=file->dataFork.totalBlocks ||
            file->dataFork.extents[1].blockCount)) return 17;
        for (unsigned j=0;j<8 && old_extents[j].blockCount;++j)
            if (file->dataFork.extents[j].startBlock!=old_extents[j].startBlock ||
                file->dataFork.extents[j].blockCount<old_extents[j].blockCount) return 15;
        printf("Staged %s bytes=%llu CNID=%u retained-blocks=%u allocated-blocks=%u\n",target->path,
            (unsigned long long)file->dataFork.logicalSize,file->fileID,old_blocks,file->dataFork.totalBlocks);
        free(record);
    }
    closeVolume(volume);CLOSE(io);return 0;
}
