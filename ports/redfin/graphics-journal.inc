/* SPDX-License-Identifier: APSL-2.0
 * GUI3 crash recovery for the existing, fenced16GiB HFSX root. These are
 * read-only preflights; native HFS still sees the original dirty header and
 * validates/replays its transaction records. Never clear a disk attribute,
 * reset a journal or change the existing UFS command/write window here.
 */
#include <arm64/redfin_gui_profile.h>

/* REDFIN_GRAPHICS_JOURNAL_TEST_BEGIN */
static uint32_t rf_gj_le32(const uint8_t *p)
{return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint64_t rf_gj_le64(const uint8_t *p)
{return rf_gj_le32(p)|(uint64_t)rf_gj_le32(p+4)<<32;}
static uint64_t rf_gj_be64(const uint8_t *p)
{return (uint64_t)redfin_rw_be32(p)<<32|redfin_rw_be32(p+4);}
static bool rf_gj_headers(const uint8_t *primary,unsigned pn,const uint8_t *alternate,unsigned an)
{
    if(!primary || pn!=512 || !alternate || an!=512 ||
       (redfin_rw_be32(primary+4)&0x100u) || memcmp(primary+8,"HFSJ",4) ||
       redfin_rw_be32(primary+40)!=4096 || redfin_rw_be32(primary+12)!=129)return false;
    uint8_t structural[512];memcpy(structural,primary,sizeof(structural));
    /* Reuse the strict existing signature/geometry/flags validator. Only
     * this local validation copy supplies its clean-bit precondition; the
     * actual device header is unchanged and is passed dirty to native HFS. */
    structural[6]|=1u;
    return redfin_rw_hfs(structural,sizeof(structural),alternate,an);
}
static bool rf_gj_location(const uint8_t *jib,unsigned bytes,uint64_t *offset,uint64_t *size)
{
    if(!offset || !size)return false;
    *offset=*size=0;
    if(!jib || bytes<52 || redfin_rw_be32(jib)!=1)return false; /* internal, initialized journal */
    for(unsigned i=4;i<36;i++)if(jib[i])return false; /* no external device signature */
    uint64_t at=rf_gj_be64(jib+36),length=rf_gj_be64(jib+44);
    /* Exact journal installed with this root, independently read after panic. */
    if(at!=532480 || length!=8388608 || at>REDFIN_RW_BLOCKS*UFS_BLOCK-length)return false;
    *offset=at;*size=length;return true;
}
static bool rf_gj_header(const uint8_t *h,unsigned bytes,uint64_t expected_size)
{
    if(!h || bytes<512 || rf_gj_le32(h)!=0x4a4e4c78u || rf_gj_le32(h+4)!=0x12345678u ||
       rf_gj_le64(h+24)!=expected_size)return false;
    uint64_t start=rf_gj_le64(h+8),end=rf_gj_le64(h+16);
    uint32_t list=rf_gj_le32(h+32),header=rf_gj_le32(h+40);
    if(header<512 || header>UFS_BLOCK || (header&(header-1)) ||
       list<header || list>BOUNCE_SIZE || (list%header) || list>expected_size-header ||
       start<header || start>expected_size || end<header || end>expected_size ||
       (start&511u) || (end&511u))return false;
    /* Native hfs_journal.c calc_checksum, over the original44-byte header;
     * the checksum field itself is zero during calculation. */
    uint32_t sum=0;
    for(unsigned i=0;i<44;i++)sum=(sum<<8)^(sum+(i>=36 && i<40?0:h[i]));
    return (uint32_t)~sum==rf_gj_le32(h+36);
}
/* REDFIN_GRAPHICS_JOURNAL_TEST_END */

static int redfin_graphics_journal_prepare(const uint8_t *primary,const uint8_t *alternate)
{
    const char *args=PE_boot_args();unsigned bytes=0;uint64_t nonce=0;
    if(!args)return EINVAL;
    while(bytes<608 && args[bytes])bytes++;
    if(bytes==608 || !redfin_gpu_gui_profile(args,bytes+1,&nonce) ||
       !rf_gj_headers(primary,512,alternate,512))return EINVAL;
    uint32_t journal_block=redfin_rw_be32(primary+12);
    int error=ufs_read_blocks(su.first_block+journal_block,1);if(error)return error;
    const uint8_t *data=(const uint8_t *)(su.dma+DMA_BOUNCE);
    uint64_t offset=0,size=0;
    if(!rf_gj_location(data,UFS_BLOCK,&offset,&size))return EINVAL;
    error=ufs_read_blocks(su.first_block+offset/UFS_BLOCK,1);if(error)return error;
    if(!rf_gj_header(data,UFS_BLOCK,size))return EINVAL;
    printf("REDFIN UFS JOURNAL: boot=%016llx validated internal journal offset=%llu size=%llu start=%llu end=%llu; native HFS replay required\n",
        (unsigned long long)nonce,(unsigned long long)offset,(unsigned long long)size,
        (unsigned long long)rf_gj_le64(data+8),(unsigned long long)rf_gj_le64(data+16));
    return 0;
}
