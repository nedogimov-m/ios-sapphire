"""Execute actual native physical-ring/runtime/worker code with host receivers."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ports.redfin.test_usb_owned_route import added_file

HERE=Path(__file__).resolve().parent


class GPUPhysicalTests(unittest.TestCase):
    def compile_run(self,source,cpp=False):
        with tempfile.TemporaryDirectory(prefix='redfin-physical-') as directory:
            directory=Path(directory);extension='cpp' if cpp else 'c'
            path=directory/('contract.'+extension);path.write_text(source)
            built=subprocess.run(['c++' if cpp else 'cc','-std=c++17' if cpp else '-std=c11',
                '-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                '-Wno-missing-field-initializers',
                '-I'+str(HERE),'-I'+str(HERE/'include'),str(path),'-o',str(directory/'contract')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            result=subprocess.run([str(directory/'contract')],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            return result.stdout

    def test_actual_physical_packets_ring_wrap_counter_and_slot_bounds(self):
        self.compile_run(r'''
#include <assert.h>
#include <string.h>
#include "redfin_gpu_physical.h"
int main(void){
 struct rf_gr_arena arena={0};uint64_t address=rf_gr_allocate(&arena,0x4000);uint32_t words=16;
 uint32_t legacy[RF_GR_PACKET_WORDS]={0},native[RF_GR_PACKET_WORDS]={0};
 for(uint32_t fence=1;fence<4096;++fence){
  unsigned n=rf_gr_submit_words(&arena,&address,&words,1,fence,legacy,RF_GR_PACKET_WORDS);
  assert(n==22&&rf_gi_submit_words(&arena,&address,&words,1,fence,native,RF_GR_PACKET_WORDS)==n);
  for(unsigned i=0;i<n;++i)assert(native[i]==(i==2?0x01200000+rf_gi_time_offset(fence):i==n-7?0x01200008+rf_gi_time_offset(fence):legacy[i]));
  assert(native[n-4]==4&&native[n-3]==0x01200200&&native[n-1]==fence);
  assert(rf_gi_time_offset(fence)+16<=RF_GI_SCRATCH_BYTES);
  for(unsigned pending=1;pending<RF_GI_DEPTH;++pending)assert(rf_gi_time_offset(fence)!=rf_gi_time_offset(fence+pending));
 }
 for(unsigned capacity=2;capacity<=64;++capacity)for(unsigned read=0;read<capacity;++read)
  for(unsigned write=0;write<capacity;++write)for(unsigned need=1;need<capacity;++need){
   unsigned available=read>write?read-write-1:capacity-write+read-1;
   assert(rf_gi_ring_room(read,write,capacity,need)==(available>=need));
  }
 assert(!rf_gi_ring_room(0,0,8192,8192)&&!rf_gi_ring_room(8192,0,8192,1));
 bool done=false;assert(!rf_gi_counter(3,1,2,2,&done)&&done);
 assert(rf_gi_counter(3,1,4,2,&done)==EPROTO&&rf_gi_counter(3,2,1,2,&done)==EPROTO);
 assert(rf_gi_can_publish(5,4)&&!rf_gi_can_publish(5,3)&&!rf_gi_can_publish(UINT32_MAX,UINT32_MAX));
 return 0;
}
''')

    def test_physical_observations_fit_the_actual_native_logger(self):
        formats=[]
        for name in ('gpu-physical-runtime.inc','gpu-physical-worker.inc'):
            formats+=re.findall(r'(?:printf|IOLog)\("(REDFIN GPU (?:PHYSICAL (?:DONE|PUB)|PIPE):[^"\n]+)"',
                                (HERE/name).read_text())
        self.assertEqual(len(formats),3)
        for value in formats:
            for spec,maximum in {'%llu':str(2**64-1),'%u':str(2**32-1),'%x':'ffffffff'}.items():
                value=value.replace(spec,maximum)
            self.assertNotIn('%',value)
            self.assertLessEqual(len(value.replace(r'\n','\n').encode()),255)

    def test_actual_native_runtime_keeps_publication_distinct_from_real_completion(self):
        result=self.compile_run((HERE/'gpu-physical-runtime-host.c').read_text())
        self.assertIn('quiescence/failure PASS',result)

    def test_actual_fifo_worker_late_publication_native_output_cache_failure_and_stop(self):
        native=HERE.parents[1]/'research/redfin-gpu/physical-ring-native-v1/iokit/Kernel/arm/RedfinGPUQueue.inc'
        source=native.read_text();first=source.index('IOReturn RedwoodGPUUserClient::executeQueued(')
        last=source.index('\nvoid RedwoodGPUUserClient::retireQueued(',first)
        receiver=(HERE/'gpu-physical-worker-host.cpp').read_text().replace('#include "actual-physical-methods.inc"',source[first:last])
        result=self.compile_run(receiver,cpp=True)
        self.assertIn('cache/error/stop/retirement PASS',result)

    def test_overlay_contains_exact_owned_helpers_and_applies_to_verified_native_preimages(self):
        patch=(HERE/'native-physical-submission.patch').read_text()
        for owned,native in (
            ('include/redfin_gpu_physical.h','bsd/dev/redfin_gpu_physical.h'),
            ('gpu-physical-runtime.inc','bsd/dev/redfin_gpu_physical.inc'),
            ('gpu-physical-worker.inc','iokit/Kernel/arm/RedfinGPUPhysicalWorker.inc')):
            self.assertEqual((HERE/owned).read_text(),added_file(patch,native))
        base=HERE.parents[1]/'research/redfin-gpu/physical-ring-base-v1'
        if not base.is_dir():self.skipTest('verified current kernel preimages unavailable')
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory);shutil.copytree(base,directory,dirs_exist_ok=True)
            result=subprocess.run(['git','apply','--check',str(HERE/'native-physical-submission.patch')],cwd=directory,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            subprocess.run(['git','apply',str(HERE/'native-physical-submission.patch')],cwd=directory,check=True,capture_output=True)
            for name in ('bsd/dev/redfin_gpu_runtime.inc','iokit/Kernel/arm/RedfinGPUQueue.inc','iokit/Kernel/arm/RedfinGPU.cpp'):
                authored=base.parent/'physical-ring-native-v1'/name
                self.assertEqual((directory/name).read_bytes(),authored.read_bytes())


if __name__=='__main__':unittest.main()
