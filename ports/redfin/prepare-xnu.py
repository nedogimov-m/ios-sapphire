#!/usr/bin/env python3
"""Stage pinned XNU sources and the redfin RAM-only overlay; do not build or boot.

Requires git, curl, bash and a macOS SDK (xcrun). Existing output trees are never
overwritten. The resulting kernel sources still need the normal SWEET toolchain,
KDK and build dependencies; source preparation does not establish boot support.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
RELEASE_URL = 'https://raw.githubusercontent.com/apple-oss-distributions/distribution-macOS/macos-135/release.json'
XNU_TAG = 'xnu-8796.141.3'
XNU_SHA = '1b191cb58250d0705d8a51287127505aa4bc0789'
BUILDER_SHA = '663906528d1cd5ea8fde7de6f16de73db9511549'
BUILDER_APPLIED = {'kas_info.patch', 'machine_routines.patch', 'skywalk_ventura.patch', 'syntax_checker_ventura.patch'}
BUILDER_SKIPPED = {'TrustCache.patch', 'iobuffermemd_monterey.patch', 'skywalk_sonoma.patch', 'syntax_checker_sonoma.patch'}


def run(args, cwd=None, capture=False, env=None):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, check=True,
                          text=True, capture_output=capture, env=env)


def checkout(directory, repository, commit, cached=False):
    if directory.exists() and any(directory.iterdir()):
        if not cached or run(['git', 'rev-parse', 'HEAD'], directory, True).stdout.strip() != commit:
            raise ValueError(f'refusing to overwrite existing directory: {directory}')
        run(['git', 'diff', '--quiet', 'HEAD'], directory)
        return
    directory.mkdir(parents=True, exist_ok=True)
    run(['git', 'init', '-q', directory])
    run(['git', 'fetch', '-q', '--depth', '1', repository, commit], directory)
    run(['git', 'checkout', '-q', '--detach', 'FETCH_HEAD'], directory)
    if run(['git', 'rev-parse', 'HEAD'], directory, True).stdout.strip() != commit:
        raise ValueError(f'commit verification failed: {directory}')


def replace(path, old, new):
    source = path.read_text()
    if source.count(old) != 1:
        raise ValueError(f'expected exactly one build-script match in {path}: {old!r}')
    path.write_text(source.replace(old, new))


def replace_regex(path, pattern, replacement):
    result, count = re.subn(pattern, replacement, path.read_text(), flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f'expected exactly one build-script match in {path}: {pattern!r}')
    path.write_text(result)


def builder_edits(tree):
    """The six pre-patch edits from the pinned builder, with checked matches."""
    replace(tree / 'bsd/sys/make_symbol_aliasing.sh',
            'AVAILABILITY_PL="${SDKROOT}/${DRIVERKITROOT}', 'AVAILABILITY_PL="${FAKEROOT_DIR}')
    replace(tree / 'libsyscall/Libsyscall.xcconfig',
            '#include "<DEVELOPER_DIR>/Makefiles/CoreOS/Xcode/BSD.xcconfig"', '')
    definitions = tree / 'makedefs/MakeInc.def'
    replace_regex(definitions, r'^LDFLAGS_KERNEL_SDK\t= -L\$\(SDKROOT\).*',
                  'LDFLAGS_KERNEL_SDK\t= -L$(FAKEROOT_DIR)/usr/local/lib/kernel -lfirehose_kernel')
    replace_regex(definitions, r'^(INCFLAGS_SDK\s*=) -I\$\(SDKROOT\)/usr/local/include/(?:kernel)?',
                  r'\1 -I$(FAKEROOT_DIR)/usr/local/include/kernel')
    for tool in ('MIG', 'MIGCOM'):
        replace(tree / 'makedefs/MakeInc.cmd',
                f'export {tool} := $(shell $(XCRUN) -sdk $(SDKROOT) -find {tool.lower()})',
                f'export {tool} := $(shell find $(FAKEROOT_DIR) -name "{tool.lower()}")')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'research/redfin-xnu')
    parser.add_argument('--builder-dir', type=Path, default=ROOT / 'research/redfin-dxb')
    args = parser.parse_args(argv)
    tree, builder = args.output.resolve(), args.builder_dir.resolve()
    try:
        if tree.exists() and any(tree.iterdir()):
            raise ValueError(f'refusing to overwrite existing directory: {tree}')
        if tree == builder or tree in builder.parents or builder in tree.parents:
            raise ValueError('source and builder directories must be separate')
        sdk = Path(run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], capture=True).stdout.strip())
        if not (sdk / 'usr/include/TargetConditionals.h').is_file():
            raise ValueError(f'SDK TargetConditionals.h is missing: {sdk}')
        release = json.loads(run(['curl', '-fLsS', '--connect-timeout', '15', '--max-time', '90', RELEASE_URL],
                                 capture=True).stdout)
        tag = next(project['tag'] for project in release['projects'] if project['project'] == 'xnu')
        if tag != XNU_TAG:
            raise ValueError(f'macos-135 changed XNU tag: {tag!r}')
        checkout(builder, 'https://github.com/blacktop/darwin-xnu-build.git', BUILDER_SHA, cached=True)
        checkout(tree, 'https://github.com/apple-oss-distributions/xnu.git', XNU_SHA)
        builder_edits(tree)
        env = dict(os.environ, MACHINE_CONFIG='SWEET', MACOS_VERSION='13.5')
        scripts = sorted((ROOT / 'xnu/patches').glob('*.sh'))
        stage_targets = {
            '0019-stage-libpthread.sh': 'bsd/pthread/sweet_libpthread',
            '0020-stage-bearssl.sh': 'libkern/crypto/sweet_bearssl',
            '0026-stage-hfs.sh': 'bsd/sweet_hfs',
        }
        if {script.name for script in scripts} != set(stage_targets):
            raise ValueError('upstream staging script inventory changed')
        for script in scripts:
            print(f'Staging {script.name}', flush=True)
            for attempt in range(3):
                try:
                    run(['bash', script], tree, env=env)
                    break
                except subprocess.CalledProcessError:
                    # Fetch failures leave no staged target; partially copied
                    # sources require inspection rather than another overwrite.
                    if attempt == 2 or (tree / stage_targets[script.name]).exists():
                        raise
                    print(f'Retrying unstaged dependency: {script.name}', flush=True)
                    time.sleep(1)
        local_patches = sorted((ROOT / 'xnu/patches').glob('*.patch'))
        builder_patches = sorted((builder / 'patches').glob('*.patch'))
        if {patch.name for patch in builder_patches} != BUILDER_APPLIED | BUILDER_SKIPPED:
            raise ValueError('pinned builder patch inventory changed')
        applied, skipped = [], []
        for patch in sorted(local_patches + builder_patches, key=lambda path: path.name):
            check = subprocess.run(['git', 'apply', '--check', str(patch)], cwd=tree,
                                   capture_output=True, text=True)
            if check.returncode:
                if patch in local_patches or patch.name not in BUILDER_SKIPPED:
                    raise ValueError(f'cannot apply {patch.name}:\n{check.stderr}')
                skipped.append(patch.name)
            else:
                if patch in builder_patches and patch.name not in BUILDER_APPLIED:
                    raise ValueError(f'unexpected applicable builder patch: {patch.name}')
                run(['git', 'apply', '--whitespace=nowarn', patch], tree)
                applied.append(patch.name)
        overlay = ROOT / 'ports/redfin/redfin.patch'
        run(['git', 'apply', '--check', overlay], tree)
        run(['git', 'apply', overlay], tree)
        run(['git', 'apply', '--check', '--reverse', overlay], tree)
        logging_overlay = ROOT / 'ports/redfin/logging.patch'
        run(['git', 'apply', '--check', logging_overlay], tree)
        run(['git', 'apply', logging_overlay], tree)
        run(['git', 'apply', '--check', '--reverse', logging_overlay], tree)
        trace_overlay = ROOT / 'ports/redfin/trace.patch'
        run(['git', 'apply', '--check', trace_overlay], tree)
        run(['git', 'apply', trace_overlay], tree)
        run(['git', 'apply', '--check', '--reverse', trace_overlay], tree)
        cpu_trace_overlay = ROOT / 'ports/redfin/cpu-trace.patch'
        run(['git', 'apply', '--check', cpu_trace_overlay], tree)
        run(['git', 'apply', cpu_trace_overlay], tree)
        battery_overlay = ROOT / 'ports/redfin/battery-disable.patch'
        run(['git', 'apply', '--check', battery_overlay], tree)
        run(['git', 'apply', battery_overlay], tree)
        extra_overlays = [ROOT / 'ports/redfin' / name for name in
            ('pid1-trace.patch', 'watchdog-progress.patch', 'panic-log.patch',
             'console-open-trace.patch', 'namei-trace.patch', 'pan.patch',
             'ufs-probe.patch', 'ufs-read-probe.patch', 'ufs-sense.patch', 'ufs-root.patch',
             'ufs-raw-read.patch', 'spmi-probe.patch', 'spmi-return.patch', 'ufs-root-rw.patch',
             'trace-gate.patch', 'shutdown.patch', 'display.patch',
             'muted-log.patch', 'screen-capture.patch', 'final-frame.patch',
             'quiet-display.patch', 'userspace-stacks.patch')]
        for extra in extra_overlays:
            run(['git', 'apply', '--check', extra], tree)
            run(['git', 'apply', extra], tree)
        manifest = {
            'xnu_tag': XNU_TAG, 'xnu_commit': XNU_SHA, 'builder_commit': BUILDER_SHA,
            'release_url': RELEASE_URL, 'sdk': str(sdk), 'machine_config': 'SWEET',
            'applied': applied, 'skipped_builder': skipped,
            'local_inputs_sha256': {path.name: digest(path) for path in scripts + local_patches},
            'redfin_overlay_sha256': digest(overlay), 'kernel_built': False, 'device_booted': False,
            'logging_overlay_sha256': digest(logging_overlay),
            'trace_overlay_sha256': digest(trace_overlay),
            'cpu_trace_overlay_sha256': digest(cpu_trace_overlay),
            'battery_overlay_sha256': digest(battery_overlay),
            'extra_overlays_sha256': {path.name: digest(path) for path in extra_overlays},
        }
        (tree / '.redfin-source.json').write_text(json.dumps(manifest, indent=2) + '\n')
    except (ValueError, OSError, subprocess.CalledProcessError, StopIteration) as error:
        parser.exit(1, f'prepare-xnu: {error}\n')
    print(f'{tree}: {len(applied)} upstream patches + redfin overlay; sources only, no build or boot')


if __name__ == '__main__':
    main()
