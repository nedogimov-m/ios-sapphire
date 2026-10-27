"""The actual CI builder must stage every native preparation extension."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('redfin_kernel_builder_inventory',HERE/'build-xnu.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


class KernelOverlayInventoryTests(unittest.TestCase):
    def test_real_CI_staging_receives_cold_output_and_station_identity_in_order(self):
        names=builder.extension_patch_names()
        self.assertEqual(names[-4:],('native-output-direct.patch','native-controls.patch',
                                    'native-cold-output-waits.patch','native-wifi-station-identity.patch'))
        self.assertEqual(len(names),len(set(names)))
        # Exercise the production staging loop in isolation. No downloads,
        # remote builds, KDK setup or device access are needed for this check.
        source=(HERE/'build-xnu.py').read_text()
        start=source.index('            for rank, name in enumerate(')
        stop=source.index('            result["patch_sha256"]',start)
        staged=[];overlays=[]
        class Copier:
            @staticmethod
            def copy2(source,target):staged.append((source.name,target.name))
        actual='\n'.join(line[12:] if line.startswith('            ') else line
                         for line in source[start:stop].splitlines())
        exec(actual,{'extension_patch_names':builder.extension_patch_names,
                    'ROOT':HERE.parents[1],'patches':Path('/tmp/redfin-inventory-only'),
                    'shutil':Copier,'overlays':overlays})
        self.assertEqual([x[0] for x in staged],list(names))
        self.assertEqual([p.name for p in overlays],list(names))
        self.assertEqual(staged[-1][1],'z'*(20+len(names))+'-redfin-native-wifi-station-identity.patch')

    def test_missing_canonical_source_refuses_before_any_kernel_build(self):
        real=Path.is_file
        def missing(path):
            return False if path.name=='native-cold-output-waits.patch' else real(path)
        with patch.object(Path,'is_file',missing):
            with self.assertRaisesRegex(ValueError,'incomplete or unsafe'):
                builder.extension_patch_names()


if __name__=='__main__':unittest.main()
