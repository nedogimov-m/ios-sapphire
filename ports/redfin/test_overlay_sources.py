"""Replay the final ordered native overlay when comparing compiled board sources."""
from pathlib import Path
import subprocess
import tempfile


def sensor_overlay(original, target):
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/target;path.parent.mkdir(parents=True);path.write_text(original)
        for name in ('sensor-platform.patch','native-sensor-cold.patch'):
            patch=Path(__file__).with_name(name)
            if patch.exists():
                subprocess.run(['git','apply','--include='+target,str(patch)],cwd=directory,check=True,capture_output=True)
        return path.read_text()
