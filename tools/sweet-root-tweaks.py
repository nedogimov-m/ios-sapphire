#!/usr/bin/env python3
"""Apply the SWEET bring-up changes to an iOS root made by tools/mkiosroot.sh.

  sudo sweet-root-tweaks.py MOUNTED_ROOT

MOUNTED_ROOT is the HFS+ image mounted read-write (Linux: run
`fsck.hfsplus -fy` on the image, then `mount -t hfsplus -o loop,force`).
Run as root (it writes root/mobile owned files). Idempotent. This is what
turned the plain mkiosroot.sh output into the images that reach the home
screen (image versions v8-v14 in NOTES.md):

  launchd.plist   _PanicOnCrash -> _PanicOnCrasX (a crashing daemon must not
                  panic the system); CommCenter jobs removed (no baseband: it
                  crash-loops and Setup blocks on its CoreTelephony XPC)
  keybag         plain systembag.kb for the built-in unlocked AppleKeyStore
                  (requires /defaults/no-effaceable-storage in the ADT)
  containers      /private/var/containers/{Bundle,Data/System,Shared/SystemGroup,Temp}
                  (on iOS they live on the data volume)
  migration       LastSystemVersion so DataMigration does not run for an hour
                  on every boot
  audio           VirtualAudio HAL plug-in disabled (mediaserverd crash)
  MediaToolbox    StartRecorderServer=false (camera filter prewarm calls a
                  NULL OpenGL function without a GPU -> mediaserverd crash loop)
  SpringBoard     BKNoWatchdogs (one slow CPU path, no scene-create watchdog
                  kills), no cloud-configuration UI
  Setup           skipped: SetupDone, SetupFinishedAllSteps, SetupVersion 11,
                  mini-buddy flags off
  activation      mobileactivationd data ark seeded; the actual Activated state
                  comes from its Hactivation branch, selected by the /chosen
                  security-status properties in tools/mkadt.py

The redfin image builder calls apply(root, metadata) to defer uid/gid/mode
changes to its offline HFS catalog pass instead of requiring host root.
"""
import glob, os, plistlib, shutil, stat, sys
from pathlib import Path

BUILD, VERSION = '20H392', '16.7.16'
MOBILE = 501
# Exact three-line plist from tools/mkiosroot.sh, including its final newline.
SYSTEM_KEYBAG_PLIST = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
    b'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>\n'
)


class RootEditor:
    """Native root edits, optionally deferring ownership to an offline catalog pass."""
    def __init__(self, root, metadata=None):
        self.root = Path(root).resolve()
        self.metadata = metadata

    def key(self, path):
        path = Path(path).absolute()
        # iOS has absolute symlinks. Never follow one into the host filesystem
        # while editing an image mounted below an ordinary host directory.
        path.resolve().relative_to(self.root)
        return str(path.relative_to(self.root))

    def attributes(self, path):
        key = self.key(path)
        if self.metadata is not None:
            record = self.metadata[key]
            return record['uid'], record['gid'], record['mode']
        item = os.stat(path)
        return item.st_uid, item.st_gid, stat.S_IMODE(item.st_mode)

    def own(self, path, uid, gid, mode):
        key = self.key(path)
        if self.metadata is None:
            os.chown(path, uid, gid)
            os.chmod(path, mode)
        else:
            # Keep the staging mount writable; final modes are applied offline.
            self.metadata[key] = {'uid': uid, 'gid': gid, 'mode': mode,
                                             'kind': stat.S_IFMT(os.lstat(path).st_mode)}

    def mkdir(self, path, uid=0, gid=0, mode=0o755):
        path = Path(path)
        self.key(path)
        missing = []
        current = path
        while not current.exists():
            self.key(current)
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir()
            self.own(directory, uid if directory == path else 0,
                     gid if directory == path else 0, mode if directory == path else 0o755)

    def move(self, source, destination):
        source_key, destination_key = self.key(source), self.key(destination)
        if Path(destination).exists():
            raise ValueError('root tweak destination already exists: ' + destination_key)
        shutil.move(source, destination)
        if self.metadata is not None:
            for key in list(self.metadata):
                if key == source_key or key.startswith(source_key + '/'):
                    self.metadata[destination_key + key[len(source_key):]] = self.metadata.pop(key)


def load(path):
    with open(path, 'rb') as f:
        return plistlib.load(f)


def save(path, data, uid, gid, mode, fmt=plistlib.FMT_BINARY, editor=None):
    if editor is not None:
        editor.key(path)
    with open(path, 'wb') as f:
        plistlib.dump(data, f, fmt=fmt)
    if editor is None:
        os.chown(path, uid, gid)
        os.chmod(path, mode)
    else:
        editor.own(path, uid, gid, mode)


def merge_pref(root, name, values, editor):
    """Merge keys into /var/mobile/Library/Preferences/NAME.plist (mobile, 0600)."""
    path = os.path.join(root, 'private/var/mobile/Library/Preferences', name + '.plist')
    editor.key(path)
    data = load(path) if os.path.exists(path) else {}
    data.update(values)
    editor.mkdir(os.path.dirname(path), MOBILE, MOBILE)
    save(path, data, MOBILE, MOBILE, 0o600, editor=editor)
    print('pref', name, sorted(values))


def launchd(root, editor):
    path = os.path.join(root, 'System/Library/xpc/launchd.plist')
    uid, gid, mode = editor.attributes(path)
    plist = load(path)
    jobs = plist['LaunchDaemons']
    renamed = 0
    for job in jobs.values():
        if '_PanicOnCrash' in job:
            job['_PanicOnCrasX'] = job.pop('_PanicOnCrash')
            renamed += 1
    removed = [k for k, j in jobs.items() if j.get('Label') == 'com.apple.CommCenter']
    for k in removed:
        del jobs[k]
    save(path, plist, uid, gid, mode, editor=editor)
    print(f'launchd.plist: {renamed} _PanicOnCrash renamed, {len(removed)} CommCenter jobs removed')


def containers(root, editor):
    base = os.path.join(root, 'private/var/containers')
    for sub, uid in (('Bundle', 33), ('Data/System', 0), ('Shared/SystemGroup', 0), ('Temp', 0)):
        d = os.path.join(base, sub)
        if not os.path.isdir(d):
            editor.mkdir(d, uid, uid)
            print('mkdir', d)


def keybag(root, editor):
    directory = Path(root).resolve() / 'private/var/keybags'
    editor.mkdir(directory, 0, 0, 0o700)
    editor.own(directory, 0, 0, 0o700)
    path = directory / 'systembag.kb'
    editor.key(path)
    # Keep any existing bag; this seed belongs only to fresh bring-up roots.
    if not path.exists():
        path.write_bytes(SYSTEM_KEYBAG_PLIST)
        print('created system keybag')
    editor.own(path, 0, 0, 0o600)


def find_container(root, kind, identifier):
    for meta in glob.glob(os.path.join(root, 'private/var/containers', kind, '*',
                                       '.com.apple.mobile_container_manager.metadata.plist')):
        if load(meta).get('MCMMetadataIdentifier') == identifier:
            return os.path.dirname(meta)
    return None


def activation(root, editor):
    c = find_container(root, 'Data/System', 'com.apple.mobileactivationd')
    if c is None:
        print('warning: no mobileactivationd system container in the image; skipped data ark')
        return
    d = os.path.join(c, 'Library/internal')
    editor.mkdir(d, MOBILE, MOBILE)
    editor.own(d, MOBILE, MOBILE, 0o755)
    save(os.path.join(d, 'data_ark.plist'), {
        '-ActivationState': 'Activated', '-BrickState': False,
        '-BuildVersion': BUILD, '-ProductVersion': VERSION,
        '-DataMigrationCompleted': True, '-PreSydroDataMigrationCompleted': True,
    }, MOBILE, MOBILE, 0o600, editor=editor)
    print('data ark', d)


def audio(root, editor):
    src = os.path.join(root, 'Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin')
    dst_dir = os.path.join(root, 'Library/Audio/Plug-Ins/HAL.disabled')
    if os.path.exists(src):
        editor.mkdir(dst_dir)
        editor.move(src, os.path.join(dst_dir, os.path.basename(src)))
        print('VirtualAudio.plugin disabled')
    for conf in glob.glob(os.path.join(root, 'System/Library/Frameworks/MediaToolbox.framework/*/SubServerConfiguration.plist')):
        uid, gid, mode = editor.attributes(conf)
        data = load(conf)
        data['StartRecorderServer'] = False
        save(conf, data, uid, gid, mode, plistlib.FMT_XML, editor=editor)
        print('StartRecorderServer off', os.path.relpath(conf, root))


def apply(root, metadata=None):
    """Apply root tweaks; metadata maps relative paths to true uid/gid/mode/kind.

    With metadata supplied, callers must apply that map to the unmounted image
    before treating it as bootable. No chown is attempted on the host.
    """
    root = str(Path(root).resolve())
    editor = RootEditor(root, metadata)
    launchd(root, editor)
    containers(root, editor)
    keybag(root, editor)
    activation(root, editor)
    audio(root, editor)
    merge_pref(root, 'com.apple.migration', {
        'LastSystemVersion': BUILD,
        'DMUserDataDisposition': {'SyntheticDidUpgrade': False, 'buildVersion': BUILD}}, editor)
    merge_pref(root, 'com.apple.springboard', {
        'BKNoWatchdogs': True,
        'FBLaunchWatchdogExceptions': {'com.apple.purplebuddy': 100.0},
        'MCForceShowCloudConfigurationUI': False}, editor)
    merge_pref(root, 'com.apple.purplebuddy', {
        'SetupDone': True, 'SetupFinishedAllSteps': True, 'SetupVersion': 11,
        'daemonizeNeedsToRun': False}, editor)
    merge_pref(root, 'com.apple.purplebuddy.notbackedup', {
        k: False for k in ('ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy',
                           'ShouldRunKeychainSyncMiniBuddy', 'ShouldRunMesaMiniBuddy',
                           'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy',
                           'SilentICDPUpgrade')}, editor)
    merge_pref(root, 'com.apple.managedconfiguration.notbackedup', {
        'LockdownActivationIndicatesCloudConfigurationAvailable': False}, editor)


def main():
    if len(sys.argv) != 2 or not os.path.isdir(os.path.join(sys.argv[1], 'System/Library/xpc')):
        sys.exit(__doc__)
    apply(sys.argv[1])


if __name__ == '__main__':
    main()
