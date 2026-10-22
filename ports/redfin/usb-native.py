#!/usr/bin/env python3
"""Bounded native macOS ECM packet diagnostic; never changes host networking."""
import argparse
import ctypes as C
from dataclasses import dataclass
import importlib.util
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
from xml.parsers.expat import ExpatError

# Share the strict wire protocol with the direct USB diagnostic.
_SPEC = importlib.util.spec_from_file_location('redfin_usb_native_wire', Path(__file__).with_name('usb-host.py'))
WIRE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = WIRE
_SPEC.loader.exec_module(WIRE)

MAC = '02:00:5e:77:ee:01'
# XNU dlil_ifaddr_bytes can redact net.link.addr as 02:00:00:00:00:00.
# This observed ifconfig value never supplies the wire MAC or BPF filter.
MASKED_MAC = bytes.fromhex('020000000000')
BSD_NAME = re.compile(r'en[0-9]{1,4}\Z')
REGISTRY_COMMAND = ['/usr/sbin/ioreg', '-a', '-l', '-p', 'IOService', '-w', '0', '-r', '-k', 'idVendor']
MAX_REGISTRY_BYTES = 32 * 1024 * 1024
FILTER = ('ether src 02:00:5e:77:ee:02 and '
          '((arp and (ether dst 02:00:5e:77:ee:01 or ether broadcast)) or '
          '(ip and ether dst 02:00:5e:77:ee:01 and src host 192.168.7.2 '
          'and dst host 192.168.7.1 and (icmp or udp dst port 5140)))')


class NativeError(RuntimeError):
    pass


class RegistryTransient(NativeError):
    """An incomplete registry query is never evidence of device removal."""


@dataclass(frozen=True)
class Binding:
    name: str
    descriptor_mac: bytes
    skywalk: bool


@dataclass(frozen=True)
class Service:
    location: int
    vendor: int
    product: int
    interfaces: tuple = ()
    bindings: tuple = ()


def registry_services(roots):
    """Retain only topology, IDs and BSD names; never USB strings or serials."""
    if isinstance(roots, dict):
        roots = [roots]
    if not isinstance(roots, list):
        raise NativeError('IOService plist is not an array or dictionary')
    services, stack, count = [], [(n, 0) for n in roots], 0
    while stack:
        node, depth = stack.pop()
        if not isinstance(node, dict):
            continue
        count += 1
        if count > 65536 or depth > 128:
            raise NativeError('IOService tree bound exceeded')
        children = node.get('IORegistryEntryChildren', [])
        if not isinstance(children, list):
            raise NativeError('IOService children are malformed')
        stack.extend((n, depth + 1) for n in children)
        vendor, product = node.get('idVendor'), node.get('idProduct')
        if (node.get('IOObjectClass') not in ('IOUSBHostDevice', 'IOUSBDevice') or
                type(vendor) is not int or type(product) is not int or
                vendor not in (0x18d1, 0x1209)):
            continue
        location = node.get('locationID')
        if type(location) is not int or not 0 < location <= 0xffffffff:
            raise NativeError('USB device has no valid locationID')
        names, bindings, child_count = set(), set(), 0
        descendants = [(n, 0, b'', False, False) for n in children]
        while descendants:
            child, child_depth, descriptor, ecm, skywalk = descendants.pop()
            if not isinstance(child, dict):
                continue
            child_count += 1
            if child_count > 1024 or child_depth > 32:
                raise NativeError('USB subtree bound exceeded')
            # Never borrow a network interface belonging to a downstream USB device.
            if child.get('IOObjectClass') in ('IOUSBHostDevice', 'IOUSBDevice'):
                continue
            cls = child.get('IOObjectClass')
            if (cls == 'AppleUserECM' or
                    (cls == 'IOUserNetworkEthernet' and child.get('IOUserClass') == 'AppleUserECM')):
                ecm = True
                raw_mac = child.get('IOMACAddress')
                descriptor = raw_mac if isinstance(raw_mac, bytes) and len(raw_mac) == 6 else b''
            if cls == 'IOSkywalkLegacyEthernet':
                skywalk = True
                if 'IOMACAddress' in child and child['IOMACAddress'] != descriptor:
                    descriptor = b''
            if (child.get('IOInterfaceType') == 6 and
                    cls in ('IOSkywalkLegacyEthernetInterface', 'IOEthernetInterface')):
                local_names = set()
                for key in ('BSD Name', 'IOBSDName'):
                    value = child.get(key)
                    if isinstance(value, str) and BSD_NAME.fullmatch(value):
                        local_names.add(value)
                unit = child.get('IOInterfaceUnit')
                if child.get('IOInterfaceNamePrefix') == 'en' and type(unit) is int and 0 <= unit <= 9999:
                    local_names.add('en' + str(unit))
                if len(local_names) > 1:
                    raise NativeError('inconsistent BSD interface identity')
                names.update(local_names)
                bindings.update(Binding(name, descriptor if ecm else b'', skywalk) for name in local_names)
            descendants.extend((n, child_depth + 1, descriptor, ecm, skywalk) for n in child.get('IORegistryEntryChildren', [])
                               if isinstance(n, dict))
        services.append(Service(location, vendor, product, tuple(sorted(names)),
                                tuple(sorted(bindings, key=lambda b: (b.name, b.descriptor_mac, b.skywalk)))))
    return services


def baseline_location(services):
    candidates = [s for s in services if s.vendor == 0x18d1]
    if len(candidates) != 1:
        raise NativeError('require exactly one Google USB device before boot')
    return candidates[0].location


def target_service(services, location):
    candidates = [s for s in services if (s.vendor, s.product) == (0x1209, 1)]
    if len(candidates) > 1:
        raise NativeError('ambiguous 1209:0001 gadgets')
    if not candidates:
        return None
    if candidates[0].location != location:
        raise NativeError('gadget location differs from Google baseline')
    return candidates[0]


class Registry:
    def __init__(self, command=subprocess.run):
        self.command = command

    def snapshot(self, timeout=2):
        try:
            result = self.command(REGISTRY_COMMAND, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise RegistryTransient('IOService query timed out') from None
        if result.returncode:
            raise RegistryTransient('IOService query failed')
        if not result.stdout.strip():
            raise RegistryTransient('IOService query returned empty output')
        if len(result.stdout) > MAX_REGISTRY_BYTES:
            raise NativeError('IOService plist exceeds size bound')
        try:
            return registry_services(plistlib.loads(result.stdout))
        except (ValueError, plistlib.InvalidFileException, ExpatError):
            raise RegistryTransient('IOService plist is malformed') from None

    def verify_mac(self, name, timeout=2):
        if not BSD_NAME.fullmatch(name):
            raise NativeError('invalid BSD interface name')
        try:
            result = self.command(['/sbin/ifconfig', name], capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise NativeError('interface identity query timed out') from None
        if result.returncode or len(result.stdout) > 65536:
            raise NativeError('interface identity query failed')
        text = result.stdout.decode('ascii', 'replace')
        if not re.match(re.escape(name) + r': flags=', text):
            raise NativeError('ifconfig interface identity mismatch')
        matches = re.findall(r'(?m)^\s+ether\s+([0-9a-fA-F:]{17})\s*$', text)
        if len(matches) != 1:
            raise NativeError('ECM interface MAC is missing or ambiguous')
        actual = bytes.fromhex(matches[0].replace(':', ''))
        if actual not in (WIRE.HOST_MAC, MASKED_MAC):
            raise NativeError('ECM interface MAC differs from descriptor or known masked value')
        return actual


class Timeval(C.Structure):
    _fields_ = [('tv_sec', C.c_long), ('tv_usec', C.c_int)]


class PacketHeader(C.Structure):
    _fields_ = [('ts', Timeval), ('caplen', C.c_uint32), ('length', C.c_uint32),
                ('comment', C.c_char * 256)]  # Apple libpcap ABI; never retained.


class BPFProgram(C.Structure):
    _fields_ = [('length', C.c_uint), ('instructions', C.c_void_p)]


class PCap:
    """Typed libpcap ABI. A capture opens only after registry and MAC proof."""
    def __init__(self, library='/usr/lib/libpcap.A.dylib', loader=C.CDLL):
        self.lib = loader(library)
        ptr, bytep = C.c_void_p, C.POINTER(C.c_ubyte)
        signatures = {
            'create': ([C.c_char_p, C.c_char_p], ptr),
            'geterr': ([ptr], C.c_char_p),
            'set_snaplen': ([ptr, C.c_int], C.c_int),
            'set_promisc': ([ptr, C.c_int], C.c_int),
            'set_timeout': ([ptr, C.c_int], C.c_int),
            'set_immediate_mode': ([ptr, C.c_int], C.c_int),
            'activate': ([ptr], C.c_int),
            'setnonblock': ([ptr, C.c_int, C.c_char_p], C.c_int),
            'datalink': ([ptr], C.c_int),
            'compile': ([ptr, C.POINTER(BPFProgram), C.c_char_p, C.c_int, C.c_uint32], C.c_int),
            'setfilter': ([ptr, C.POINTER(BPFProgram)], C.c_int),
            'freecode': ([C.POINTER(BPFProgram)], None),
            'next_ex': ([ptr, C.POINTER(C.POINTER(PacketHeader)), C.POINTER(bytep)], C.c_int),
            'inject': ([ptr, ptr, C.c_size_t], C.c_int),
            'close': ([ptr], None),
        }
        for suffix, (args, result) in signatures.items():
            fn = getattr(self.lib, 'pcap_' + suffix)
            fn.argtypes, fn.restype = args, result

    def error(self, value):
        raw = self.lib.pcap_geterr(value) or b'no native detail'
        return self.safe_error(raw)

    @staticmethod
    def safe_error(raw):
        return ''.join(c if 32 <= ord(c) < 127 else '?' for c in raw[:256].decode('ascii', 'replace'))

    def open(self, name):
        if not BSD_NAME.fullmatch(name):
            raise NativeError('invalid BSD interface name')
        error = C.create_string_buffer(256)
        value = self.lib.pcap_create(name.encode('ascii'), error)
        if not value:
            raise NativeError('pcap_create failed: ' + self.safe_error(error.value))
        handle = Capture(self, value)
        try:
            for suffix, value in (('set_snaplen', 2048), ('set_promisc', 0),
                                  ('set_timeout', 20), ('set_immediate_mode', 1)):
                if getattr(self.lib, 'pcap_' + suffix)(handle.value, value) != 0:
                    raise NativeError('pcap_' + suffix + ' failed: ' + self.error(handle.value))
            if self.lib.pcap_activate(handle.value) < 0:
                raise NativeError('pcap_activate failed: ' + self.error(handle.value))
            if self.lib.pcap_datalink(handle.value) != 1:
                raise NativeError('capture link type must be Ethernet DLT_EN10MB')
            if self.lib.pcap_setnonblock(handle.value, 1, error) != 0:
                raise NativeError('pcap_setnonblock failed: ' + self.safe_error(error.value))
            program = BPFProgram()
            if self.lib.pcap_compile(handle.value, C.byref(program), FILTER.encode('ascii'), 1, 0xffffffff) != 0:
                raise NativeError('pcap_compile failed: ' + self.error(handle.value))
            try:
                if self.lib.pcap_setfilter(handle.value, C.byref(program)) != 0:
                    raise NativeError('pcap_setfilter failed: ' + self.error(handle.value))
            finally:
                self.lib.pcap_freecode(C.byref(program))
            return handle
        except BaseException:
            handle.close()
            raise


class Capture:
    def __init__(self, backend, value):
        self.backend, self.value = backend, value
        self.truncated = 0

    def read(self):
        header = C.POINTER(PacketHeader)()
        packet = C.POINTER(C.c_ubyte)()
        code = self.backend.lib.pcap_next_ex(self.value, C.byref(header), C.byref(packet))
        if code == 0:
            return b''
        if code != 1:
            raise NativeError('pcap_next_ex failed: ' + self.backend.error(self.value))
        if not header or not packet:
            raise NativeError('pcap returned a null packet/header')
        size, original = header.contents.caplen, header.contents.length
        if size > 2048 or size > original:
            raise NativeError('pcap returned an invalid packet length')
        if size != original:
            self.truncated += 1
            return b''
        return C.string_at(packet, size)

    def send(self, packet):
        if not 14 <= len(packet) <= 2048:
            raise NativeError('injection frame exceeds bounds')
        data = (C.c_ubyte * len(packet)).from_buffer_copy(packet)
        if self.backend.lib.pcap_inject(self.value, C.cast(data, C.c_void_p), len(packet)) != len(packet):
            raise NativeError('pcap_inject failed or short; frame was not retransmitted: ' + self.backend.error(self.value))

    def close(self):
        if self.value is not None:
            self.backend.lib.pcap_close(self.value)
            self.value = None


def run_probe(registry, pcap, boot_id, seconds, out, clock=time.monotonic, sleep=time.sleep):
    if not WIRE.valid_boot_id(boot_id) or not 1 <= seconds <= 120:
        raise ValueError('seconds must be 1..120 and boot ID canonical nonzero hex')
    out = Path(out)
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    deadline = clock() + seconds
    protocol = WIRE.Protocol(boot_id)
    handle = None
    reported_mac = None
    result = {'evidence': 'native-ecm', 'capture_authenticated': False,
              'expected_boot_id': boot_id, 'network_modified': False,
              'promiscuous': False, 'serials_retained': False,
              'registry_transient_errors': [], 'registry_errors_dropped': 0}

    def remaining():
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError('native ECM diagnostic deadline expired')
        return min(2, left)

    def snapshot():
        while clock() < deadline:
            try:
                return registry.snapshot(timeout=remaining())
            except RegistryTransient as error:
                if len(result['registry_transient_errors']) < 64:
                    result['registry_transient_errors'].append(str(error))
                else:
                    result['registry_errors_dropped'] += 1
                sleep(min(0.05, max(0, deadline - clock())))
        raise TimeoutError('no complete IOService snapshot before deadline')

    def descriptor_binding(target, name):
        matches = [b for b in target.bindings if b.name == name]
        if len(matches) != 1 or matches[0].descriptor_mac != WIRE.HOST_MAC:
            raise NativeError('ECM ancestor descriptor MAC is missing, ambiguous or unexpected')
        return matches[0]

    def verify_binding(name):
        target = target_service(snapshot(), location)
        if target is None:
            return False
        if target.interfaces != (name,):
            raise NativeError('bound ECM interface identity changed')
        binding = descriptor_binding(target, name)
        current = registry.verify_mac(name, timeout=remaining())
        if current != reported_mac or (current == MASKED_MAC and not binding.skywalk):
            raise NativeError('bound ECM reported MAC/profile changed')
        return True

    try:
        location = baseline_location(snapshot())
        result['baseline_location'] = location
        while clock() < deadline:
            target = target_service(snapshot(), location)
            if target and target.interfaces:
                if len(target.interfaces) != 1:
                    raise NativeError('gadget has ambiguous BSD interfaces')
                name = target.interfaces[0]
                binding = descriptor_binding(target, name)
                reported_mac = registry.verify_mac(name, timeout=remaining())
                if reported_mac == MASKED_MAC and not binding.skywalk:
                    raise NativeError('masked interface report requires the proved Apple Skywalk ancestry')
                result.update(interface=name, descriptor_mac=MAC, reported_mac=reported_mac.hex(':'),
                              wire_mac=MAC,
                              mac_profile='descriptor' if reported_mac == WIRE.HOST_MAC else 'ifconfig-masked')
                handle = pcap.open(name)
                break
            sleep(min(0.1, max(0, deadline - clock())))
        if handle is None:
            raise TimeoutError('no bound ECM interface on baseline USB location before deadline')
        if not verify_binding(name):
            raise NativeError('ECM device disconnected before first injection')
        remaining()
        handle.send(protocol.arp_request())
        echo_sent, next_identity = False, clock()
        while clock() < deadline and not protocol.log_overflow:
            try:
                if clock() >= next_identity:
                    if not verify_binding(name):
                        result['end_reason'] = 'device-disconnected'
                        break
                    next_identity = clock() + 0.5
                try:
                    frame = handle.read()
                except NativeError:
                    if target_service(snapshot(), location) is None:
                        result['end_reason'] = 'device-disconnected'
                        break
                    raise
                if frame:
                    for reply in protocol.feed(frame):
                        remaining()
                        handle.send(reply)
                    if not echo_sent:
                        protocol.echo_seen = False  # A nonce alone is not a solicited round trip.
                    if protocol.arp_seen and not echo_sent:
                        remaining()
                        handle.send(protocol.echo_request())
                        echo_sent = True
                else:
                    sleep(min(0.01, max(0, deadline - clock())))
            except TimeoutError:
                result['end_reason'] = 'deadline'
                break
        result['status'] = 'link-ready' if protocol.arp_seen and protocol.echo_seen else 'probe-incomplete'
        result.setdefault('end_reason', 'log-limit' if protocol.log_overflow else 'deadline')
        return result
    except BaseException as error:
        result.update(status='error', error=str(error))
        raise
    finally:
        if handle is not None:
            handle.close()
        result.update(arp_seen=protocol.arp_seen, echo_seen=protocol.echo_seen,
                      log_bytes=len(protocol.log), log_overflow=protocol.log_overflow,
                      rejected_frames=protocol.rejected, udp_log_freshness=protocol.log_freshness,
                      truncated_frames=handle.truncated if handle else 0)
        WIRE.private_write(out / 'kernel.log', bytes(protocol.log))
        WIRE.private_write(out / 'manifest.json', (json.dumps(result, indent=2) + '\n').encode())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-manifest', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        boot_id = WIRE.read_boot_id(args.image_manifest)
        if not 1 <= args.seconds <= 120:
            raise ValueError('seconds must be 1..120')
        if args.out.exists() or not args.out.parent.is_dir():
            raise ValueError('output directory must be new and its parent must exist')
        result = run_probe(Registry(), PCap(), boot_id, args.seconds, args.out)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] == 'link-ready' else 1
    except (OSError, ValueError, NativeError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
