#!/usr/bin/env python3
"""Bounded libusb CDC diagnostic for the temporary Redfin RAM gadget."""
import argparse
import contextlib
import ctypes as C
import ctypes.util
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import struct
import sys
import time

HOST_MAC = bytes.fromhex('02005e77ee01')
PHONE_MAC = bytes.fromhex('02005e77ee02')
HOST_IP = ipaddress.IPv4Address('192.168.7.1').packed
PHONE_IP = ipaddress.IPv4Address('192.168.7.2').packed
LOG_LIMIT = 8 * 1024 * 1024


class USBError(RuntimeError):
    def __init__(self, code, message='USB operation failed'):
        self.code = code
        names = {-1: 'IO', -2: 'INVALID_PARAM', -3: 'ACCESS', -4: 'NO_DEVICE',
                 -5: 'NOT_FOUND', -6: 'BUSY', -7: 'TIMEOUT', -8: 'OVERFLOW',
                 -9: 'PIPE', -10: 'INTERRUPTED', -11: 'NO_MEM', -12: 'NOT_SUPPORTED'}
        super().__init__(f'{message}: LIBUSB_ERROR_{names.get(code, str(code))} ({code})')


@dataclass(frozen=True)
class DeviceInfo:
    bus: int
    ports: tuple
    vendor: int
    product: int
    token: object = None


def checksum(data):
    if len(data) & 1:
        data += b'\0'
    value = sum(struct.unpack('!' + 'H' * (len(data) // 2), data))
    while value >> 16:
        value = (value & 0xffff) + (value >> 16)
    return (~value) & 0xffff


def ethernet(dst, src, kind, payload):
    return dst + src + struct.pack('!H', kind) + payload


def ipv4(src, dst, protocol, payload):
    header = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(payload), 0,
                         0x4000, 64, protocol, 0, src, dst)
    return header[:10] + struct.pack('!H', checksum(header)) + header[12:] + payload


def icmp_echo(boot_id, reply=False):
    payload = b'REDFIN USB ' + boot_id.encode('ascii')
    packet = struct.pack('!BBHHH', 0 if reply else 8, 0, 0, 0x5246, 1) + payload
    return packet[:2] + struct.pack('!H', checksum(packet)) + packet[4:]


def valid_boot_id(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{16}', value) and int(value, 16) != 0


def read_boot_id(path):
    manifest = json.loads(Path(path).read_text())
    if not isinstance(manifest, dict) or not isinstance(manifest.get('boot_args'), str):
        raise ValueError('image manifest must contain string boot_args')
    tokens = manifest.get('boot_args', '').split()
    found = [word for word in tokens if word.startswith('redfinbootid')]
    if len(found) != 1 or not re.fullmatch('redfinbootid=0x[0-9a-f]{16}', found[0]):
        raise ValueError('image manifest must contain exactly one redfinbootid=0x<16 lowercase hex>')
    result = found[0].split('0x')[1]
    if not valid_boot_id(result):
        raise ValueError('image boot ID must be nonzero')
    return result


class Protocol:
    def __init__(self, boot_id, log_limit=LOG_LIMIT):
        if not valid_boot_id(boot_id) or not 1 <= log_limit <= LOG_LIMIT:
            raise ValueError('invalid boot ID or log bound')
        self.boot_id, self.log_limit = boot_id, log_limit
        self.arp_seen = self.echo_seen = self.log_overflow = False
        self.log = bytearray()
        self.rejected = 0

    def arp_request(self):
        arp = struct.pack('!HHBBH', 1, 0x800, 6, 4, 1) + HOST_MAC + HOST_IP + bytes(6) + PHONE_IP
        return ethernet(b'\xff' * 6, HOST_MAC, 0x806, arp)

    def echo_request(self):
        return ethernet(PHONE_MAC, HOST_MAC, 0x800,
                        ipv4(HOST_IP, PHONE_IP, 1, icmp_echo(self.boot_id)))

    @property
    def log_freshness(self):
        markers = re.findall(rb'^REDFIN BOOT ID:[^\r\n]*\r?$', bytes(self.log), re.M)
        if not markers:
            return 'missing'
        if len(markers) != 1:
            return 'duplicate'
        return 'matched' if markers[0].rstrip(b'\r') == b'REDFIN BOOT ID: ' + self.boot_id.encode() else 'mismatch'

    def feed(self, frame):
        try:
            return self._feed(frame)
        except (ValueError, struct.error, IndexError):
            self.rejected += 1
            return []

    def _feed(self, frame):
        if not 14 <= len(frame) <= 1515 or frame[6:12] != PHONE_MAC:
            raise ValueError('Ethernet source or size')
        kind = struct.unpack_from('!H', frame, 12)[0]
        body = frame[14:]
        if kind == 0x806:
            if frame[:6] not in (HOST_MAC, b'\xff' * 6) or len(body) < 28:
                raise ValueError('ARP envelope')
            if body[:6] != struct.pack('!HHBB', 1, 0x800, 6, 4):
                raise ValueError('ARP format')
            op = struct.unpack_from('!H', body, 6)[0]
            if body[8:14] != PHONE_MAC or body[14:18] != PHONE_IP or body[24:28] != HOST_IP:
                raise ValueError('ARP identities')
            if any(body[28:]) or len(body) > 46:
                raise ValueError('ARP padding')
            if op == 1 and body[18:24] in (bytes(6), HOST_MAC):
                self.arp_seen = True
                arp = struct.pack('!HHBBH', 1, 0x800, 6, 4, 2) + HOST_MAC + HOST_IP + PHONE_MAC + PHONE_IP
                return [ethernet(PHONE_MAC, HOST_MAC, 0x806, arp)]
            if op == 2 and body[18:24] == HOST_MAC and frame[:6] == HOST_MAC:
                self.arp_seen = True
                return []
            raise ValueError('ARP operation')
        if kind != 0x800 or frame[:6] != HOST_MAC or len(body) < 20:
            raise ValueError('IPv4 envelope')
        ihl = (body[0] & 15) * 4
        total, fragment = struct.unpack_from('!HH', body, 2)[0], struct.unpack_from('!H', body, 6)[0]
        if body[0] >> 4 != 4 or ihl < 20 or ihl > 60 or total < ihl or total > len(body):
            raise ValueError('IPv4 length')
        if fragment & ~0x4000 or checksum(body[:ihl]) or body[12:16] != PHONE_IP or body[16:20] != HOST_IP:
            raise ValueError('IPv4 checksum, fragmentation or identity')
        padding = body[total:]
        allowed = max(0, 60 - 14 - total)
        if padding and (any(padding) or (len(padding) > allowed and not (len(padding) == 1 and (14 + total) % 512 == 0))):
            raise ValueError('Ethernet padding')
        payload = body[ihl:total]
        if body[9] == 1:
            if payload != icmp_echo(self.boot_id, reply=True):
                raise ValueError('ICMP echo identity/checksum')
            self.echo_seen = True
            return []
        if body[9] != 17 or len(payload) < 8:
            raise ValueError('IPv4 protocol')
        source, target, length, check = struct.unpack_from('!4H', payload)
        if not source or target != 5140 or length != len(payload):
            raise ValueError('UDP ports/length')
        if check and checksum(PHONE_IP + HOST_IP + struct.pack('!BBH', 0, 17, length) + payload):
            raise ValueError('UDP checksum')
        data = payload[8:]
        room = self.log_limit - len(self.log)
        self.log.extend(data[:room])
        self.log_overflow |= len(data) > room
        return []


def select_baseline(devices):
    phones = [d for d in devices if d.vendor == 0x18d1]
    if len(phones) != 1 or not phones[0].ports:
        raise ValueError('require exactly one Google 18d1 device with a known physical port before boot')
    return phones[0].bus, tuple(phones[0].ports)


class Discovery:
    """Bounded topology changes; no serial strings or native device pointers."""
    def __init__(self, limit=64, device_limit=32):
        if not 1 <= limit <= 64 or not 1 <= device_limit <= 32:
            raise ValueError('invalid discovery bounds')
        self.limit, self.device_limit = limit, device_limit
        self.entries, self.last = [], None
        self.transitions_dropped = 0
        self.devices_truncated = False

    def observe(self, devices):
        state = tuple(sorted((d.vendor, d.product, d.bus, tuple(d.ports)) for d in devices))
        if state == self.last:
            return
        self.last = state
        self.devices_truncated |= len(state) > self.device_limit
        if len(self.entries) >= self.limit:
            self.transitions_dropped += 1
            return
        self.entries.append([{'vendor': vendor, 'product': product, 'bus': bus,
                              'ports': list(ports)}
                             for vendor, product, bus, ports in state[:self.device_limit]])


def open_gadget(backend, baseline, deadline, clock=time.monotonic, sleep=time.sleep, observe=None):
    while clock() < deadline:
        with backend.snapshot() as devices:
            if observe is not None:
                observe(devices)
            gadgets = [d for d in devices if (d.vendor, d.product) == (0x1209, 1)]
            if len(gadgets) > 1:
                raise ValueError('ambiguous 1209:0001 gadgets')
            if gadgets:
                d = gadgets[0]
                if not d.ports or (d.bus, tuple(d.ports)) != baseline:
                    raise ValueError('gadget physical port differs from Google baseline')
                return backend.open(d)  # Open retains device before list is freed.
        sleep(min(0.1, max(0, deadline - clock())))
    raise TimeoutError('1209:0001 did not appear on the baseline port before deadline')


def private_write(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(data)


def run_probe(backend, boot_id, seconds, out, clock=time.monotonic, sleep=time.sleep):
    if not valid_boot_id(boot_id) or not 1 <= seconds <= 120:
        raise ValueError('seconds must be 1..120 and boot ID nonzero canonical hex')
    out = Path(out)
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    deadline = clock() + seconds
    protocol = Protocol(boot_id)
    handle = None
    claimed = False
    disconnected = False
    discovery = Discovery()
    result = {'evidence': 'direct-usb', 'capture_authenticated': False,
              'expected_boot_id': boot_id}

    def timeout():
        left = deadline - clock()
        if left <= 0:
            raise TimeoutError('USB diagnostic deadline expired')
        return min(250, max(1, int(left * 1000)))

    def send(frame):
        if handle.bulk_write(0x01, frame, timeout()) != len(frame):
            raise USBError(-1, 'short bulk OUT; frame was not retransmitted')

    try:
        with backend.snapshot() as devices:
            discovery.observe(devices)
            baseline = select_baseline(devices)
        result['baseline'] = {'bus': baseline[0], 'ports': list(baseline[1])}
        handle = open_gadget(backend, baseline, deadline, clock, sleep, discovery.observe)
        configuration = handle.get_configuration()
        result['initial_configuration'] = configuration
        if configuration == 0:
            handle.set_configuration(1)
        elif configuration != 1:
            raise ValueError('gadget configuration must be 0 or 1')
        handle.claim_interface(1)
        claimed = True
        handle.set_alt_setting(1, 1)
        try:
            response = handle.control_transfer(0x21, 0x43, 0xf, 0, b'', timeout())
            if response != b'':
                raise USBError(-1, 'unexpected CDC packet-filter response')
            result['packet_filter'] = 'accepted'
        except USBError as error:
            if error.code != -9:
                raise
            result['packet_filter'] = 'stalled-optional'
        send(protocol.arp_request())
        echo_sent = False
        while clock() < deadline and not protocol.log_overflow:
            try:
                frame = handle.bulk_read(0x81, 2048, timeout())
            except USBError as error:
                if error.code != -4:
                    raise
                disconnected = True
                break
            if frame:
                for reply in protocol.feed(frame):
                    send(reply)
                if not echo_sent:
                    protocol.echo_seen = False  # Unsolicited echo is not a round trip.
                if protocol.arp_seen and not echo_sent:
                    send(protocol.echo_request())
                    echo_sent = True
        result.update(status='link-ready' if protocol.arp_seen and protocol.echo_seen else 'probe-incomplete')
        result['end_reason'] = ('device-disconnected' if disconnected else
                                'log-limit' if protocol.log_overflow else 'deadline')
        return result
    except Exception as error:
        result.update(status='error', error=str(error))
        raise
    finally:
        pending = sys.exc_info()[0] is not None
        try:
            if handle is not None and claimed:
                handle.release_interface(1)
        except USBError as error:
            if error.code == -4 and disconnected:
                result['release_no_device_after_disconnect'] = True
            else:
                result['release_error'] = str(error)
            if not pending and not (error.code == -4 and disconnected):
                result.update(status='error', error=str(error))
                raise
        finally:
            if handle is not None:
                handle.close()
            result.update(arp_seen=protocol.arp_seen, echo_seen=protocol.echo_seen,
                          log_bytes=len(protocol.log), log_overflow=protocol.log_overflow,
                          rejected_frames=protocol.rejected, udp_log_freshness=protocol.log_freshness)
            result.update(discovery=discovery.entries,
                          discovery_transitions_dropped=discovery.transitions_dropped,
                          discovery_devices_truncated=discovery.devices_truncated)
            private_write(out / 'kernel.log', bytes(protocol.log))
            private_write(out / 'manifest.json', (json.dumps(result, indent=2) + '\n').encode())


class DeviceDescriptor(C.Structure):
    _fields_ = [('length', C.c_uint8), ('type', C.c_uint8), ('usb', C.c_uint16),
                ('device_class', C.c_uint8), ('subclass', C.c_uint8), ('protocol', C.c_uint8),
                ('packet', C.c_uint8), ('vendor', C.c_uint16), ('product', C.c_uint16),
                ('release', C.c_uint16), ('manufacturer', C.c_uint8), ('name', C.c_uint8),
                ('serial', C.c_uint8), ('configurations', C.c_uint8)]


class LibUSB:
    def __init__(self, library=None):
        name = library or C.util.find_library('usb-1.0') or '/opt/homebrew/lib/libusb-1.0.dylib'
        self.lib = C.CDLL(name)
        pointer = C.c_void_p
        bytep = C.POINTER(C.c_uint8)
        signatures = {
            'init': ([C.POINTER(pointer)], C.c_int), 'exit': ([pointer], None),
            'get_device_list': ([pointer, C.POINTER(C.POINTER(pointer))], C.c_ssize_t),
            'free_device_list': ([C.POINTER(pointer), C.c_int], None),
            'get_device_descriptor': ([pointer, C.POINTER(DeviceDescriptor)], C.c_int),
            'get_bus_number': ([pointer], C.c_uint8),
            'get_port_numbers': ([pointer, bytep, C.c_int], C.c_int),
            'open': ([pointer, C.POINTER(pointer)], C.c_int), 'close': ([pointer], None),
            'get_configuration': ([pointer, C.POINTER(C.c_int)], C.c_int),
            'set_configuration': ([pointer, C.c_int], C.c_int),
            'claim_interface': ([pointer, C.c_int], C.c_int),
            'release_interface': ([pointer, C.c_int], C.c_int),
            'set_interface_alt_setting': ([pointer, C.c_int, C.c_int], C.c_int),
            'control_transfer': ([pointer, C.c_uint8, C.c_uint8, C.c_uint16, C.c_uint16,
                                  bytep, C.c_uint16, C.c_uint], C.c_int),
            'bulk_transfer': ([pointer, C.c_ubyte, bytep, C.c_int, C.POINTER(C.c_int), C.c_uint], C.c_int),
        }
        for suffix, (args, returns) in signatures.items():
            fn = getattr(self.lib, 'libusb_' + suffix)
            fn.argtypes, fn.restype = args, returns
        self.ctx = pointer()
        self.check(self.lib.libusb_init(C.byref(self.ctx)), 'initialize libusb')

    @staticmethod
    def check(code, message):
        if code < 0:
            raise USBError(code, message)
        return code

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.ctx is not None:
            self.lib.libusb_exit(self.ctx)
            self.ctx = None

    @contextlib.contextmanager
    def snapshot(self):
        items = C.POINTER(C.c_void_p)()
        count = self.check(self.lib.libusb_get_device_list(self.ctx, C.byref(items)), 'enumerate USB')
        try:
            devices = []
            for index in range(count):
                token = items[index]
                descriptor = DeviceDescriptor()
                self.check(self.lib.libusb_get_device_descriptor(token, C.byref(descriptor)), 'read cached USB descriptor')
                if descriptor.vendor not in (0x18d1, 0x1209):
                    continue
                ports = (C.c_uint8 * 8)()
                depth = self.check(self.lib.libusb_get_port_numbers(token, ports, 8), 'read USB port path')
                devices.append(DeviceInfo(self.lib.libusb_get_bus_number(token), tuple(ports[:depth]),
                                          descriptor.vendor, descriptor.product, token))
            yield devices
        finally:
            self.lib.libusb_free_device_list(items, 1)

    def open(self, device):
        value = C.c_void_p()
        self.check(self.lib.libusb_open(device.token, C.byref(value)), 'open gadget; ACCESS/BUSY requires OS/user action, no detach or retry')
        return Handle(self, value)


class Handle:
    def __init__(self, backend, value):
        self.backend, self.value = backend, value

    def call(self, suffix, *args):
        return self.backend.check(getattr(self.backend.lib, 'libusb_' + suffix)(self.value, *args), suffix)

    def get_configuration(self):
        value = C.c_int()
        self.call('get_configuration', C.byref(value))
        return value.value

    def set_configuration(self, value): self.call('set_configuration', value)
    def claim_interface(self, value): self.call('claim_interface', value)
    def release_interface(self, value): self.call('release_interface', value)
    def set_alt_setting(self, interface, alt): self.call('set_interface_alt_setting', interface, alt)

    def control_transfer(self, kind, request, value, index, data, timeout_ms):
        if not 1 <= timeout_ms <= 120000 or len(data) > 65535:
            raise ValueError('bounded control transfer required')
        buffer = (C.c_uint8 * len(data)).from_buffer_copy(data) if data else None
        count = self.call('control_transfer', kind, request, value, index, buffer, len(data), timeout_ms)
        if count != len(data):
            raise USBError(-1, 'short control transfer')
        return b''

    def bulk_write(self, endpoint, data, timeout_ms):
        if not 1 <= timeout_ms <= 120000 or not 1 <= len(data) <= 2048:
            raise ValueError('bounded bulk OUT required')
        buffer = (C.c_uint8 * len(data)).from_buffer_copy(data)
        count = C.c_int()
        self.call('bulk_transfer', endpoint, buffer, len(data), C.byref(count), timeout_ms)
        if count.value != len(data):
            raise USBError(-1, 'short bulk OUT; no retransmission')
        return count.value

    def bulk_read(self, endpoint, size, timeout_ms):
        if not 1 <= timeout_ms <= 120000 or not 1 <= size <= 2048:
            raise ValueError('bounded bulk IN required')
        buffer = (C.c_uint8 * size)()
        count = C.c_int()
        result = self.backend.lib.libusb_bulk_transfer(self.value, endpoint, buffer, size, C.byref(count), timeout_ms)
        if result == -7:
            return b''  # Discard uncertain partial data, never parse a truncated transfer.
        self.backend.check(result, 'bulk IN')
        if not 0 <= count.value <= size:
            raise USBError(-1, 'invalid bulk IN length')
        return bytes(buffer[:count.value])

    def close(self):
        if self.value is not None:
            self.backend.lib.libusb_close(self.value)
            self.value = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-manifest', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--library')
    args = parser.parse_args(argv)
    try:
        boot_id = read_boot_id(args.image_manifest)
        if not 1 <= args.seconds <= 120:
            raise ValueError('seconds must be 1..120')
        if args.out.exists():
            raise ValueError('output directory must be new')
        if not args.out.parent.is_dir():
            raise ValueError('output parent directory must exist')
        with LibUSB(args.library) as backend:
            result = run_probe(backend, boot_id, args.seconds, args.out)
        print(json.dumps(result, sort_keys=True))
        return 0 if result['status'] == 'link-ready' else 1
    except (OSError, ValueError, USBError, TimeoutError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
