"""Real command redirection, strict reuse boundary and canonical native pairing."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from ports.redfin.graphics_build_inputs import metal_pairing,metal_plugin_command
from ports.redfin.graphics_native_runtime import AIR_DIR,AIR_TARGET,RUNTIME_INPUTS,runtime_commands,runtime_delta

ROOT=Path(__file__).resolve().parents[2]


class GraphicsNativeRuntimeTests(unittest.TestCase):
    def test_only_complete_wait_delta_can_reuse_native_objects(self):
        prior=[{'path':'upstream/compiler.c','sha256':'1'*64},
               {'path':'ports/redfin/metal-queued.inc','sha256':'2'*64},
               {'path':'ports/redfin/mesa-disk-cache.inc','sha256':'3'*64}]
        current=copy.deepcopy(prior);current[1]['sha256']='4'*64
        current.extend({'path':p,'sha256':'5'*64} for p in sorted(RUNTIME_INPUTS) if p!=prior[1]['path'])
        self.assertEqual(runtime_delta(prior,current),sorted(RUNTIME_INPUTS))
        for bad in (current[:-1],current+[{'path':'unknown','sha256':'6'*64}],
                    [current[2],current[1],current[0],*current[3:]],current+[current[0]]):
            with self.assertRaises(ValueError):runtime_delta(prior,bad)
        bad=copy.deepcopy(current);bad[0]['sha256']='7'*64
        with self.assertRaises(ValueError):runtime_delta(prior,bad)
        with self.assertRaises(ValueError):runtime_delta(prior,current[1:])

    def test_native_commands_write_only_new_objects_and_keep_archive_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);old=root/'baseline/mesa-25.0.7';build=root/'baseline/build-freedreno'
            source=root/'fresh/mesa-25.0.7';objects=root/'fresh/objects';air=root/'fresh/bundle/lib/libredfinair.dylib'
            build.mkdir(parents=True);(build/'libcompiler.a').write_bytes(b'immutable archive')
            commands=[];link=[]
            for name in ('air_metal.c','redfin_pairing.c'):
                obj='air.p/'+name+'.o';link.append(obj)
                commands.append(['clang','-target','arm64-apple-ios16.0','-I../mesa-25.0.7/src',
                    '-Isrc','-MD','-MQ',obj,'-MF',obj+'.d','-o',obj,'-c','../mesa-25.0.7/'+AIR_DIR+'/'+name])
            commands.append(['clang++','-o',AIR_TARGET,*link,'libcompiler.a','-framework','IOKit'])
            before=copy.deepcopy(commands)
            rewritten,reused=runtime_commands(commands,build,old,source,objects,air)
            self.assertEqual(commands,before)
            self.assertEqual(reused,[(build/'libcompiler.a').resolve()])
            for command,name in zip(rewritten,('air_metal.c','redfin_pairing.c')):
                self.assertEqual(command[command.index('-c')+1],str(source/AIR_DIR/name))
                for flag in ('-o','-MF','-MQ'):
                    self.assertIn(str(objects),command[command.index(flag)+1])
                self.assertIn('-I'+str(source/'src'),command);self.assertIn('-Isrc',command)
            self.assertEqual(rewritten[-1][rewritten[-1].index('-o')+1],str(air))
            self.assertIn('libcompiler.a',rewritten[-1])
            self.assertIn(str(objects/'air_metal.c.o'),rewritten[-1])
            with self.assertRaises(ValueError):runtime_commands(commands[:-1],build,old,source,objects,air)
            with self.assertRaises(ValueError):runtime_commands(commands+[commands[0]],build,old,source,objects,air)

    def test_shared_pairing_reproduces_accepted_checker_shader_source_identity(self):
        baseline=ROOT/'research/redfin-metal-ubo-extent-v1/result.json'
        if not baseline.is_file():self.skipTest('private reviewed source baseline absent')
        result=json.loads(baseline.read_text())
        self.assertEqual(metal_pairing(ROOT,ROOT/'research/hackios-upstream/userland',result['input_sha256']),
                         result['metal_pairing_sha256'])
        command=metal_plugin_command(ROOT,'clang','sdk',ROOT/'metal',ROOT/'plugin')
        self.assertIn('-bundle',command);self.assertNotIn('-dynamiclib',command)
        self.assertIn('-Werror=incompatible-function-pointer-types',command)


if __name__=='__main__':unittest.main()
