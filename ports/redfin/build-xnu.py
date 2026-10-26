#!/usr/bin/env python3
"""Attempt a local SWEET/redfin XNU build; no device or system KDK installation.

Uses the selected Xcode (DEVELOPER_DIR can select a different installation).
XNU 8796 was originally built with Xcode 15; a newer iig may be incompatible.
All downloaded sources, extracted KDK files and logs stay in --work-dir.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
DXB_SHA = "663906528d1cd5ea8fde7de6f16de73db9511549"
XNU_SHA = "1b191cb58250d0705d8a51287127505aa4bc0789"
KDK_NAME = "Kernel_Debug_Kit_13.5_build_22G74.dmg"
KDK_URL = "https://github.com/dortania/KdkSupportPkg/releases/download/22G74/" + KDK_NAME
KDK_BYTES = 658949979
KDK_SHA256 = "29866842eef039812888daea4176ce493be153b0d6d1b88f90753d69ea51b7d4"
VERIFY_OVERLAYS = '''import pathlib, re, shutil, subprocess, sys, tempfile
tree = pathlib.Path(sys.argv[1])
patches = [pathlib.Path(path) for path in sys.argv[2:]]
with tempfile.TemporaryDirectory(prefix="redfin-overlay-check-") as name:
    temporary = pathlib.Path(name)
    files = set()
    for patch in patches:
        files.update(re.findall(r"^\\+\\+\\+ b/(.+)$", patch.read_text(), re.M))
    for name in files:
        relative = pathlib.Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe patch path")
        target = temporary / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tree / relative, target)
    for patch in reversed(patches):
        subprocess.run(["git", "apply", "--reverse", "--check", str(patch)], cwd=temporary, check=True)
        subprocess.run(["git", "apply", "--reverse", str(patch)], cwd=temporary, check=True)
'''


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("unexpected pinned build script: %r" % old)
    return source.replace(old, new)


def find_kdk(expanded):
    if not expanded.exists():
        return None
    # Flat packages expand the contents of the installed .kdk into Payload,
    # retaining the intended installation directory only in PackageInfo.
    for metadata in expanded.rglob("PackageInfo"):
        package = ET.parse(metadata).getroot()
        if (package.get("identifier") == "com.apple.pkg.KDK.22G74" and
                package.get("install-location") == "/Library/Developer/KDKs/KDK_13.5_22G74.kdk"):
            payload = metadata.parent / "Payload"
            if (payload / "System/Library/Kernels").is_dir():
                return payload
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=ROOT / "research/redfin-build")
    parser.add_argument("--no-install-deps", action="store_true",
                        help="require existing brew jq/gum/cmake/ninja/bash")
    args = parser.parse_args(argv)
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    log_path = work / (time.strftime("build-%Y%m%d-%H%M%S") + ".log")
    environment = dict(os.environ)
    environment["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + environment.get("PATH", "")
    result = {"builder_commit": DXB_SHA, "xnu_commit": XNU_SHA,
              "log": str(log_path), "success": False}
    build_began = time.monotonic()
    with log_path.open("w") as log:
        def run(command, cwd=work, capture=False):
            command = [str(part) for part in command]
            log.write("\n$ " + shlex.join(command) + "\n")
            log.flush()
            began = time.monotonic()
            try:
                completed = subprocess.run(command, cwd=cwd, env=environment,
                                           stdout=subprocess.PIPE if capture else log,
                                           stderr=log, text=capture, check=True)
            finally:
                result.setdefault("command_timings", []).append({
                    "step": " ".join(command[:2]),
                    "seconds": round(time.monotonic() - began, 3),
                })
            if capture:
                log.write(completed.stdout)
                log.flush()
                return completed.stdout.strip()

        def checkout(path, url, commit):
            if not (path / ".git").is_dir():
                if path.exists() and any(path.iterdir()):
                    raise ValueError("refusing non-git source directory: %s" % path)
                run(["git", "init", "-q", path])
                run(["git", "fetch", "--depth", "1", url, commit], cwd=path)
                run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=path)
            if run(["git", "rev-parse", "HEAD"], cwd=path, capture=True) != commit:
                raise ValueError("unexpected source commit: %s" % path)

        try:
            if not args.no_install_deps:
                run(["brew", "install", "jq", "gum", "cmake", "ninja", "bash"])
            for executable in ("jq", "gum", "cmake", "ninja", "brew", "xcrun"):
                if not shutil.which(executable, path=environment["PATH"]):
                    raise ValueError("missing dependency: " + executable)
            bash = Path(run(["brew", "--prefix", "bash"], capture=True)) / "bin/bash"
            if not bash.is_file():
                raise ValueError("Homebrew bash is missing")
            result["xcode"] = run(["xcodebuild", "-version"], capture=True)
            dxb = work / "dxb"
            checkout(dxb, "https://github.com/blacktop/darwin-xnu-build", DXB_SHA)
            checkout(dxb / "xnu", "https://github.com/apple-oss-distributions/xnu", XNU_SHA)

            dmg = work / KDK_NAME
            if not dmg.is_file() or dmg.stat().st_size != KDK_BYTES:
                partial = work / (KDK_NAME + ".partial")
                run(["curl", "--fail", "--location", "--retry", "3", "--connect-timeout", "30",
                     "--output", partial, KDK_URL])
                if partial.stat().st_size != KDK_BYTES:
                    raise ValueError("unexpected KDK download size")
                partial.replace(dmg)
            result["kdk_sha256"] = digest(dmg)
            if result["kdk_sha256"] != KDK_SHA256:
                raise ValueError("KDK SHA256 mismatch")
            expanded = work / "kdk-expanded"
            kdk = find_kdk(expanded)
            result["reused_expanded_kdk"] = kdk is not None
            if kdk is None:
                if expanded.exists():
                    raise ValueError("incomplete KDK extraction; choose another --work-dir")
                mount = work / "kdk-mount"
                mount.mkdir(exist_ok=True)
                run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, dmg])
                try:
                    package = mount / "KernelDebugKit.pkg"
                    if not package.is_file():
                        raise ValueError("KernelDebugKit.pkg was not present in mounted KDK")
                    run(["pkgutil", "--expand-full", package, expanded])
                finally:
                    run(["hdiutil", "detach", mount])
                kdk = find_kdk(expanded)
            if kdk is None or not kdk.is_dir():
                raise ValueError("extracted KDK root was not found")
            result["kdk_root"] = str(kdk)

            patches = dxb / "patches"
            local_patches = sorted((ROOT / "xnu/patches").glob("*.patch"))
            local_scripts = sorted((ROOT / "xnu/patches").glob("*.sh"))
            for patch in local_patches + local_scripts:
                shutil.copy2(patch, patches / patch.name)
            overlay = ROOT / "ports/redfin/redfin.patch"
            shutil.copy2(overlay, patches / "zz-redfin.patch")
            logging_patch = ROOT / "ports/redfin/logging.patch"
            shutil.copy2(logging_patch, patches / "zzz-redfin-logging.patch")
            trace_patch = ROOT / "ports/redfin/trace.patch"
            shutil.copy2(trace_patch, patches / "zzzz-redfin-trace.patch")
            cpu_trace_patch = ROOT / "ports/redfin/cpu-trace.patch"
            shutil.copy2(cpu_trace_patch, patches / "zzzzz-redfin-cpu-trace.patch")
            battery_patch = ROOT / "ports/redfin/battery-disable.patch"
            shutil.copy2(battery_patch, patches / "zzzzzz-redfin-battery-disable.patch")
            watchdog_patch = ROOT / "ports/redfin/watchdog-progress.patch"
            shutil.copy2(watchdog_patch, patches / "zzzzzzz-redfin-watchdog-progress.patch")
            pid1_patch = ROOT / "ports/redfin/pid1-trace.patch"
            shutil.copy2(pid1_patch, patches / "zzzzzzzz-redfin-pid1-trace.patch")
            panic_patch = ROOT / "ports/redfin/panic-log.patch"
            shutil.copy2(panic_patch, patches / "zzzzzzzzz-redfin-panic-log.patch")
            open_patch = ROOT / "ports/redfin/console-open-trace.patch"
            shutil.copy2(open_patch, patches / "zzzzzzzzzz-redfin-console-open-trace.patch")
            namei_patch = ROOT / "ports/redfin/namei-trace.patch"
            shutil.copy2(namei_patch, patches / "zzzzzzzzzzz-redfin-namei-trace.patch")
            pan_patch = ROOT / "ports/redfin/pan.patch"
            shutil.copy2(pan_patch, patches / "zzzzzzzzzzzz-redfin-pan.patch")
            ufs_probe_patch = ROOT / "ports/redfin/ufs-probe.patch"
            shutil.copy2(ufs_probe_patch, patches / "zzzzzzzzzzzzz-redfin-ufs-probe.patch")
            ufs_read_patch = ROOT / "ports/redfin/ufs-read-probe.patch"
            shutil.copy2(ufs_read_patch, patches / "zzzzzzzzzzzzzz-redfin-ufs-read-probe.patch")
            ufs_sense_patch = ROOT / "ports/redfin/ufs-sense.patch"
            shutil.copy2(ufs_sense_patch, patches / "zzzzzzzzzzzzzzz-redfin-ufs-sense.patch")
            ufs_root_patch = ROOT / "ports/redfin/ufs-root.patch"
            shutil.copy2(ufs_root_patch, patches / "zzzzzzzzzzzzzzzz-redfin-ufs-root.patch")
            ufs_raw_patch = ROOT / "ports/redfin/ufs-raw-read.patch"
            shutil.copy2(ufs_raw_patch, patches / "zzzzzzzzzzzzzzzzz-redfin-ufs-raw-read.patch")
            spmi_patch = ROOT / "ports/redfin/spmi-probe.patch"
            shutil.copy2(spmi_patch, patches / "zzzzzzzzzzzzzzzzzz-redfin-spmi-probe.patch")
            return_patch = ROOT / "ports/redfin/spmi-return.patch"
            shutil.copy2(return_patch, patches / "zzzzzzzzzzzzzzzzzzz-redfin-spmi-return.patch")
            ufs_rw_patch = ROOT / "ports/redfin/ufs-root-rw.patch"
            shutil.copy2(ufs_rw_patch, patches / "zzzzzzzzzzzzzzzzzzzz-redfin-ufs-root-rw.patch")
            overlays = [overlay, logging_patch, trace_patch, cpu_trace_patch, battery_patch,
                        watchdog_patch, pid1_patch, panic_patch, open_patch, namei_patch, pan_patch,
                        ufs_probe_patch, ufs_read_patch, ufs_sense_patch, ufs_root_patch, ufs_raw_patch,
                        spmi_patch, return_patch, ufs_rw_patch]
            for rank, name in enumerate(('trace-gate.patch', 'shutdown.patch', 'display.patch',
                                         'muted-log.patch', 'screen-capture.patch',
                                         'final-frame.patch', 'quiet-display.patch',
                                         'userspace-stacks.patch', 'touch.patch',
                                         'usb-probe.patch', 'gpu-probe.patch', 'wifi-probe.patch',
                                         'rpmh-probe.patch', 'usb-route.patch', 'touch-spi.patch',
                                         'touch-setup.patch', 'touch-rail-observe.patch',
                                         'touch-events.patch', 'touch-rail-ready.patch',
                                         'rpmh-touch.patch', 'touch-start.patch',
                                         'touch-spi-diag.patch', 'touch-platform-diag.patch',
                                         'touch-dfs-diag.patch', 'touch-dfs-disable.patch',
                                         'touch-rx-irq.patch', 'touch-sensing.patch',
                                         'usb-owned-route.patch', 'usb-owned-diag.patch',
                                         'usb-owned-build.patch',
                                         'usb-gadget.patch', 'usb-start.patch',
                                         'usb-context-probe.patch', 'usb-bypass-context.patch',
                                         'usb-enumeration-start.patch', 'usb-bypass-diagnostic.patch',
                                         'usb-fault-diagnostic.patch',
                                         'usb-aarch64-context.patch',
                                         'usb-context-format-status.patch',
                                         'usb-network-worker.patch', 'usb-log-worker-check.patch',
                                         'usb-tx-completion.patch', 'usb-network-start.patch',
                                         'peripheral-start.patch', 'touch-event-start.patch',
                                         'cpu-probe.patch', 'cpu-probe-start.patch', 'cpu-target.patch',
                                         'early-return.patch', 'early-return-start.patch',
                                         'smp-log.patch', 'smp-return.patch', 'smp.patch',
                                         'early-bootid.patch', 'smp-eight.patch', 'smp-gui.patch',
                                         'touch-overflow.patch', 'gpu-power.patch', 'display-fit.patch',
                                         'wifi-aop.patch', 'wifi-native-probe.patch', 'wifi-native-start.patch',
                                         'gmu-probe.patch', 'gmu-start.patch', 'scm-query.patch',
                                         'wifi-firmware.patch', 'wifi-fw-source.patch', 'wifi-smp2p.patch',
                                         'wifi-fw-build.patch', 'wifi-radio.patch', 'wifi-network.patch',
                                         'wifi-network-build.patch', 'wifi-gui.patch', 'touch-response.patch', 'preinit-progress.patch',
                                         'userspace-waits.patch', 'gpu-service.patch', 'graphics-eagl.patch', 'graphics-physical.patch', 'graphics-journal.patch', 'graphics-exec.patch', 'graphics-memory.patch', 'graphics-lifecycle.patch', 'touch-reconnect.patch', 'platform-entitlements.patch', 'display-presenter.patch', 'device-identity.patch', 'photos-exec.patch', 'gpu-display.patch', 'userland-platform.patch', 'gui-integration.patch', 'keychain-descriptors.patch', 'platform-power.patch', 'metal-platform.patch', 'platform-readiness.patch', 'native-validated-platform.patch', 'native-observability.patch', 'native-tcc-observation.patch', 'native-session-performance.patch', 'sensor-platform.patch', 'native-sensor-cold.patch', 'native-sandbox.patch', 'native-gpu-dvfs.patch', 'native-sensor-discovery.patch', 'native-failure-capture.patch', 'native-surface-lifecycle.patch', 'native-runtime-queues.patch', 'native-queued-submission.patch', 'native-presentation-observer.patch','native-throughput.patch','native-resource-access.patch','native-cadence.patch','native-display-output.patch','native-surface-padding.patch','native-retained-memory.patch','native-physical-submission.patch','native-surface-cache.patch'), 21):
                extension = ROOT / 'ports/redfin' / name
                shutil.copy2(extension, patches / ('z' * rank + '-redfin-' + name))
                overlays.append(extension)
            result["patch_sha256"] = {path.name: digest(path)
                                      for path in local_patches + local_scripts + overlays}
            fingerprint_path = dxb / "xnu/.redfin-patches.json"
            fingerprint = {"builder_commit": DXB_SHA, "xnu_commit": XNU_SHA,
                           "patch_sha256": result["patch_sha256"]}
            resume = fingerprint_path.exists()
            rebuild_objects = False
            verifier = dxb / "verify-redfin-overlays.py"
            verifier.write_text(VERIFY_OVERLAYS)
            verification_command = [sys.executable, verifier, dxb / "xnu", *overlays]
            if resume:
                previous = json.loads(fingerprint_path.read_text())
                # Existing base patches remain pinned; final board overlays can
                # be adopted once their exact new contents are present in XNU.
                overlay_names = {path.name for path in overlays}
                expected_base = {name: value for name, value in fingerprint["patch_sha256"].items()
                                 if name not in overlay_names}
                previous_base = {name: value for name, value in previous["patch_sha256"].items()
                                 if name not in overlay_names}
                if (previous.get("builder_commit") != DXB_SHA or
                        previous.get("xnu_commit") != XNU_SHA or previous_base != expected_base):
                    raise ValueError("base source fingerprint changed; use a new --work-dir")
                run(verification_command)
                rebuild_objects = (previous["patch_sha256"].get(pan_patch.name) != digest(pan_patch))
            if not resume:
                # Adopt a known prepared tree only after both final overlays
                # and the staged provider are verified; no partial patch replay.
                try:
                    run(verification_command)
                    resume = (dxb / "xnu/bsd/pthread/sweet_libpthread").is_dir()
                except subprocess.CalledProcessError:
                    pass
            result["resumed_sources"] = resume
            if rebuild_objects:
                # Changing -mcpu or PAN support invalidates every kernel object.
                # Retain all source trees, KDK files and dependency libraries.
                object_directory = dxb / "build/xnu.obj"
                if object_directory.is_dir() and not object_directory.is_symlink():
                    log.write("Removing kernel objects after PAN/CPU configuration change\n")
                    log.flush()
                    shutil.rmtree(object_directory)
                result["cleaned_kernel_objects"] = True
            # Recreate the wrapper from the exact pin on every invocation.
            source = run(["git", "show", DXB_SHA + ":build.sh"], cwd=dxb, capture=True)
            source = replace_once(source, '    install_deps\n',
                                  '    # Dependencies are handled by ports/redfin/build-xnu.py.\n')
            first = source.index('    if [ ! -d "$KDKROOT" ]; then\n')
            last = source.index('\n}\n', first)
            source = source[:first] + ('    if [ ! -d "$KDKROOT" ]; then\n'
                     '        error "Private KDKROOT is missing; refusing system installation"\n'
                     '        exit 1\n    fi') + source[last:]
            source = replace_once(source,
                'ARCHS="x86_64 arm64e" VALID_ARCHS="x86_64 arm64e"',
                'ARCHS="arm64" VALID_ARCHS="arm64" '
                'OTHER_CFLAGS="-mkernel -nostdinc -Wno-packed -mcpu=cortex-a53"')
            # Preserve exact compiler/flags while reusing unchanged native
            # objects in CI. ccache validates source/header/compiler contents.
            ccache = shutil.which("ccache", path=environment["PATH"])
            result["ccache_enabled"] = bool(ccache)
            if ccache:
                wrappers = work / "ccache-bin"
                wrappers.mkdir(exist_ok=True)
                for tool, variable in (("clang", "CC"), ("clang++", "CXX")):
                    compiler = run(["xcrun", "--find", tool], capture=True)
                    wrapper = wrappers / tool
                    wrapper.write_text("#!/bin/sh\nexec " + shlex.join([ccache, compiler]) + ' "$@"\n')
                    wrapper.chmod(0o755)
                    source = replace_once(source, 'export ' + variable + '="$(xcrun -find ' + tool + ')"',
                                          'export ' + variable + '=' + shlex.quote(str(wrapper)))
            # Always ask make to evaluate dependencies; the pinned builder's
            # existence check otherwise silently returns an old final kernel.
            source = replace_once(source,
                '    if [ ! -f "${BUILD_DIR}/xnu.obj/kernel.${KERNEL_TYPE}" ]; then\n',
                '    if true; then\n')
            patch_step = ('    info "Reusing verified prepared XNU source tree"\n' if resume else '    patches\n')
            source = replace_once(source, '    patches\n',
                patch_step + '    ' + shlex.join([str(part) for part in verification_command]) + '\n'
                '    cp "${WORK_DIR}/redfin-patches.expected.json" '
                '"${WORK_DIR}/xnu/.redfin-patches.json"\n')
            (dxb / "redfin-patches.expected.json").write_text(json.dumps(fingerprint, indent=2) + "\n")
            (dxb / "build.sh").write_text(source + "\n")
            environment.update(KDKROOT=str(kdk), MACOS_VERSION="13.5",
                               KERNEL_CONFIG="DEVELOPMENT", MACHINE_CONFIG="SWEET", ARCH_CONFIG="ARM64")
            run([bash, "build.sh"], cwd=dxb)
            kernels = list((dxb / "fakeroot").rglob("kernel.development.sweet"))
            result["kernels"] = {str(path): digest(path) for path in kernels if path.is_file()}
            result["success"] = bool(result["kernels"])
            if not result["success"]:
                raise ValueError("build returned success but no kernel.development.sweet was found")
        except (subprocess.CalledProcessError, OSError, ValueError) as error:
            result["error"] = str(error)
            result["exit_code"] = getattr(error, "returncode", 1)
            log.write("\nBUILD FAILED: " + str(error) + "\n")
    result["elapsed_seconds"] = round(time.monotonic() - build_began, 3)
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(("built" if result["success"] else "build failed") + ": " + str(log_path))
    return 0 if result["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
