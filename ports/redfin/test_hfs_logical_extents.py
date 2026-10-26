"""Actual host HFS writer must preserve mappings across8/16/24 extent boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_display_geometry import function

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class HFSLogicalExtentsTests(unittest.TestCase):
    def test_actual_writer_emits_logical_keys_big_endian_payloads_and_zero_partial_tails(self):
        package=ROOT/'research/hfsplus'
        source=package/'hfs/rawfile.c'
        if not source.is_file():self.skipTest('host HFS source fixture absent')
        body=function(source.read_text(),'int writeExtents(RawFile* rawFile) {')
        prefix=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <hfs/hfsplus.h>
char endianness;
static unsigned emitted,removed;static int remove_ok=1,add_ok=1;
static uint32_t logical_keys[8];static unsigned char contents[8][64];
int removeExtents(RawFile *file){assert(file);++removed;return remove_ok;}
int addToBTree(BTree *tree,BTKey *raw,size_t bytes,unsigned char *data) {
 HFSPlusExtentKey *key=(HFSPlusExtentKey *)raw;
 assert(tree&&bytes==64&&emitted<8&&key->fileID==366782&&key->forkType==0);
 assert(key->keyLength==sizeof(*key)-sizeof(key->keyLength));
 logical_keys[emitted]=key->startBlock;memcpy(contents[emitted],data,64);++emitted;
 return add_ok;
}
void flipExtentRecord(HFSPlusExtentRecord *record) {
 for(unsigned i=0;i<8;++i) {
  (*record)[i].startBlock=__builtin_bswap32((*record)[i].startBlock);
  (*record)[i].blockCount=__builtin_bswap32((*record)[i].blockCount);
 }
}
static uint32_t be32(const unsigned char *p){return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
'''
        suffix=r'''
int main(void) {
 for(unsigned n=0;n<=39;++n) {
  Extent extents[40]={0};HFSPlusForkData fork={0};Volume volume={0};RawFile file={0};
  file.id=366782;file.forkData=&fork;file.volume=&volume;volume.extentsTree=(BTree *)1;
  for(unsigned i=0;i<n;++i){extents[i].startBlock=20000+i*127;extents[i].blockCount=i+1;extents[i].next=i+1<n?&extents[i+1]:NULL;}
  file.extents=n?extents:NULL;emitted=removed=0;remove_ok=add_ok=1;
  assert(writeExtents(&file)&&removed==1&&emitted==(n>8?(n-8+7)/8:0));
  uint32_t logical=0;
  for(unsigned i=0;i<8;++i) {
   assert(fork.extents[i].startBlock==(i<n?extents[i].startBlock:0));
   assert(fork.extents[i].blockCount==(i<n?extents[i].blockCount:0));
   if(i<n)logical+=extents[i].blockCount;
  }
  for(unsigned group=0;group<emitted;++group) {
   assert(logical_keys[group]==logical);
   for(unsigned j=0;j<8;++j) {
    unsigned i=8+8*group+j;
    assert(be32(contents[group]+8*j)==(i<n?extents[i].startBlock:0));
    assert(be32(contents[group]+8*j+4)==(i<n?extents[i].blockCount:0));
    if(i<n)logical+=extents[i].blockCount;
   }
  }
  if(n>8) {
   emitted=removed=0;volume.extentsTree=NULL;
   assert(!writeExtents(&file)&&!removed&&!emitted);
   volume.extentsTree=(BTree *)1;remove_ok=0;
   assert(!writeExtents(&file)&&removed==1&&!emitted);
   remove_ok=1;add_ok=0;emitted=removed=0;
   assert(!writeExtents(&file)&&removed==1&&emitted==1);
  }
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'writer.c';path.write_text(prefix+body+suffix)
            binary=Path(folder)/'writer'
            result=subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',
                '-Wno-macro-redefined','-I',str(package/'includes'),str(path),'-o',str(binary)],
                capture_output=True,text=True)
            if result.returncode:self.fail(result.stderr)
            subprocess.run([str(binary)],check=True,capture_output=True)


if __name__=='__main__':unittest.main()
