"""Shader-cache compatibility and exact-artifact startup policy contracts."""
import copy
import json
from pathlib import Path
import plistlib
import tempfile
import unittest

from ports.redfin import gpu_userland,metal_userland
from ports.redfin.graphics_build_cache import compiler_cache,components,digest,semantic_identity,startup_policy,verify_build


class GraphicsBuildReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.work=self.root/'prior';self.bundle=self.work/'bundle'
        self.bundle.mkdir(parents=True)
        self.identity={'target':'arm64-apple-ios16.0','clang':'reviewed-clang','sdk':'27.1',
                       'archive':'a'*64,'flags':{'CFLAGS':''}}
        self.input_hash='1'*64;self.cache_id='redfin-ios16-arm64-'+self.input_hash
        self.inputs=[]
        for name,data in (
                ('research/upstream/air/air_to_nir.c',b'translation v1'),
                ('ports/redfin/metal-persistent-cache.inc',b'serialization v1'),
                ('ports/redfin/mesa-submit-merge.h',b'native submit bounds v1')):
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);self.inputs.append(path)
        files={
            'lib/native.dylib':b'previously ABI-validated native fixture bytes',
            gpu_userland.JOB_PATH.lstrip('/'):plistlib.dumps(gpu_userland.job(True)),
            metal_userland.JOB_PATH.lstrip('/'):plistlib.dumps(metal_userland.job(True)),
        }
        for name,data in files.items():
            path=self.bundle/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        metal={'success':True,'actual_abi_compatible':True,'max_buffer_bytes':128<<20,
               'startup_checks_enabled':True,'files':{
                   metal_userland.JOB_PATH:{'source':metal_userland.JOB_PATH.lstrip('/'),
                       'uid':0,'mode':0o644,'sha256':digest(files[metal_userland.JOB_PATH.lstrip('/')])}}}
        (self.bundle/'metal-build.json').write_text(json.dumps(metal))
        self.result={'success':True,'actual_abi_compatible':True,'input_sha256':self.input_hash,
                     'metal_pairing_sha256':'2'*64,'startup_checks_enabled':True,
                     'artifacts':{str(p.relative_to(self.bundle)):digest(p.read_bytes())
                                  for p in self.bundle.rglob('*') if p.is_file()}}
        (self.work/'result.json').write_text(json.dumps(self.result))
        (self.work/'abi-check.json').write_text(json.dumps({'compatible':True}))
        src=self.work/'mesa-25.0.7';(src/'src/util').mkdir(parents=True)
        (src/'.redfin-graphics').write_text(self.input_hash+'\n')
        (src/'src/util/redfin_mesa_cache_build.h').write_text(
            '#define REDFIN_MESA_CACHE_BUILD_ID '+json.dumps(self.cache_id)+'\n')
        self.prior={'version':1,'input_sha256':self.input_hash,'compiler_identity':self.identity,
                    'components':components(self.root,self.inputs),'cache_id':self.cache_id}
        (self.work/'compiler-inputs.json').write_text(json.dumps(self.prior))

    def reuse(self,inputs=None,identity=None):
        return compiler_cache(self.root,inputs or self.inputs,identity or self.identity,'3'*64,self.work)

    def test_transport_only_changes_preserve_existing_disk_cache_and_full_pairing(self):
        self.inputs[-1].write_bytes(b'new bounded native submit policy')
        added=self.root/'ports/redfin/mesa-resource-access.patch'
        added.write_text('--- a/src/gallium/drivers/freedreno/freedreno_batch.c\n'
                         '+++ b/src/gallium/drivers/freedreno/freedreno_batch.c\n')
        proof=self.reuse(self.inputs+[added])
        self.assertTrue(proof['reused']);self.assertTrue(proof['full_binary_pairing_preserved'])
        self.assertEqual(proof['cache_id'],self.cache_id)
        self.assertEqual(json.loads((self.work/'result.json').read_text())['metal_pairing_sha256'],'2'*64)

    def test_shader_or_serialization_changes_refuse_reuse(self):
        for index in (0,1):
            original=self.inputs[index].read_bytes();self.inputs[index].write_bytes(original+b' semantic change')
            with self.assertRaisesRegex(ValueError,'shader/compiler/serialization'):self.reuse()
            self.inputs[index].write_bytes(original)

    def test_compiler_options_and_semantic_patch_order_are_strict(self):
        changed=copy.deepcopy(self.identity);changed['flags']['CFLAGS']='-ffast-math'
        with self.assertRaisesRegex(ValueError,'toolchain/options'):self.reuse(identity=changed)
        with self.assertRaisesRegex(ValueError,'shader/compiler/serialization'):
            self.reuse([self.inputs[1],self.inputs[0],self.inputs[2]])

    def test_new_unknown_inputs_and_transport_patch_scope_are_strict(self):
        added=self.root/'ports/redfin/new-shader-transform.h';added.write_bytes(b'new semantics')
        with self.assertRaisesRegex(ValueError,'shader/compiler/serialization'):self.reuse(self.inputs+[added])
        bad=self.root/'ports/redfin/mesa-resource-access.patch'
        bad.write_text('+++ b/src/compiler/nir/nir_serialize.c\n')
        with self.assertRaisesRegex(ValueError,'unreviewed compiler input'):self.reuse(self.inputs+[bad])

    def test_tampered_native_bytes_or_prior_cache_marker_cannot_authorize_reuse(self):
        path=self.bundle/'lib/native.dylib';old=path.read_bytes();path.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'native artifact changed'):self.reuse()
        path.write_bytes(old)
        (self.work/'mesa-25.0.7/src/util/redfin_mesa_cache_build.h').write_text('different marker')
        with self.assertRaisesRegex(ValueError,'cache marker differs'):self.reuse()

    def test_policy_flip_preserves_all_native_bytes_and_records_original_evidence(self):
        before=(self.bundle/'lib/native.dylib').read_bytes()
        result=startup_policy(self.work,False)
        self.assertFalse(result['startup_checks_enabled'])
        self.assertFalse(result['policy_only_update']['native_recompiled'])
        self.assertEqual(result['input_sha256'],self.input_hash)
        self.assertEqual(result['metal_pairing_sha256'],'2'*64)
        self.assertEqual((self.bundle/'lib/native.dylib').read_bytes(),before)
        evidence=Path(result['policy_only_update']['source_evidence'])
        self.assertTrue(json.loads((evidence/'result.json').read_text())['startup_checks_enabled'])
        for path in (gpu_userland.JOB_PATH,metal_userland.JOB_PATH):
            job=plistlib.loads((self.bundle/path.lstrip('/')).read_bytes())
            self.assertTrue(job['Disabled']);self.assertFalse(job['RunAtLoad'])
        verify_build(self.work);metal_userland.inventory(self.bundle)
        current=(self.work/'result.json').read_bytes();startup_policy(self.work,False)
        self.assertEqual((self.work/'result.json').read_bytes(),current)
        startup_policy(self.work,True);verify_build(self.work)
        self.assertEqual((self.bundle/'lib/native.dylib').read_bytes(),before)

    def test_policy_refuses_tampering_before_changing_any_job(self):
        path=self.bundle/gpu_userland.JOB_PATH.lstrip('/');before=path.read_bytes()
        (self.bundle/'lib/native.dylib').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'native artifact changed'):startup_policy(self.work,False)
        self.assertEqual(path.read_bytes(),before)

    def test_policy_does_not_apply_new_program_arguments_to_verified_old_binaries(self):
        path=self.bundle/gpu_userland.JOB_PATH.lstrip('/')
        job=plistlib.loads(path.read_bytes());job['ProgramArguments'].append('--older-native-contract')
        path.write_bytes(plistlib.dumps(job));before=path.read_bytes()
        result=json.loads((self.work/'result.json').read_text())
        result['artifacts'][str(path.relative_to(self.bundle))]=digest(before)
        (self.work/'result.json').write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError,'diagnostic recipe changed'):startup_policy(self.work,False)
        self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
