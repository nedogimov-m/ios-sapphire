"""Real NIR/read-only/cache contracts for bounded Metal constant snapshots."""
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent


class MetalUBOExtentsTests(unittest.TestCase):
    def test_actual_nir_ranges_and_unsupported_reads_without_serialization_changes(self):
        host=ROOT/'research/redfin-air-preparation-v2';build=host/'build'
        if not (build/'compile_commands.json').is_file():
            self.skipTest('reusable native Mesa25.0.7 host build is unavailable')
        recipes=json.loads((build/'compile_commands.json').read_text())
        main=next(r for r in recipes if r['file'].endswith('/ir3_cmdline.c'))
        compile=shlex.split(main['command']);original=compile[compile.index('-o')+1]
        target=original.split('.p/',1)[0]
        lines=subprocess.check_output(['ninja','-C',str(build),'-t','commands',target],text=True).splitlines()
        link=shlex.split(lines[-1]);self.assertIn(original,link)
        with tempfile.TemporaryDirectory(prefix='redfin-ubo-nir-') as directory:
            directory=Path(directory);obj=directory/'contract.o';binary=directory/'contract'
            compile[compile.index('-o')+1]=str(obj)
            compile[compile.index('-c')+1]=str(HERE/'metal-ubo-extents-host.c')
            # Keep dependency side effects out of the reused native build.
            for flag in ('-MF','-MQ'):
                if flag in compile:
                    at=compile.index(flag);del compile[at:at+2]
            if '-MD' in compile:compile.remove('-MD')
            compile+=['-I'+str(HERE)]
            compiled=subprocess.run(compile,cwd=build,capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            link[link.index('-o')+1]=str(binary);link[link.index(original)]=str(obj)
            subprocess.run(link,cwd=build,check=True,capture_output=True,text=True)
            result=subprocess.run([str(binary)],check=True,capture_output=True,text=True)
            self.assertIn('cases=16',result.stdout)
            self.assertIn('serialized-NIR-unchanged=1',result.stdout)


if __name__=='__main__':unittest.main()
