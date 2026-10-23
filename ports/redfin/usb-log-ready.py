"""Unhooked fixed-peer host ACK codec for a future dedicated USB diagnostic.

No USB/network device is opened here. Existing usb-native.py/usb-host.py are
unchanged. A new coordinator must supply verified capture/injection and record
each request before transmitting its ACK; this module never invokes GPU work.
"""
from dataclasses import dataclass, replace
import importlib.util
from pathlib import Path
import struct
import sys

SPEC = importlib.util.spec_from_file_location('redfin_log_ready_wire', Path(__file__).with_name('usb-host.py'))
WIRE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = WIRE
SPEC.loader.exec_module(WIRE)

MAGIC, PORT = b'RFLGv001', 5141
HELLO, HELLO_ACK, MARKER, MARKER_ACK = range(1, 5)
READ32, WRITE32 = 1, 2
PACKET = struct.Struct('!8sIIQQQII')
MAX_MARKERS, MAX_ACKS = 16, 3
# Add to a new coordinator's filter only. The baseline native filter is intact.
CONTROL_FILTER = ('ether src 02:00:5e:77:ee:02 and ether dst 02:00:5e:77:ee:01 '
                  'and ip and src host 192.168.7.2 and dst host 192.168.7.1 '
                  'and udp dst port 5141')


@dataclass(frozen=True)
class Message:
    kind: int
    sequence: int
    boot_nonce: int
    cookie: int
    address: int = 0
    operation: int = 0
    value: int = 0

    def encode(self):
        values = (self.kind, self.sequence, self.boot_nonce, self.cookie,
                  self.address, self.operation, self.value)
        if any(type(value) is not int for value in values):
            raise ValueError('control fields must be integers')
        if not (1 <= self.kind <= 4 and 0 < self.boot_nonce < 1 << 64 and
                0 < self.cookie < 1 << 64 and 0 <= self.value < 1 << 32):
            raise ValueError('invalid control identity or field range')
        if self.kind <= HELLO_ACK:
            if self.sequence != 1 or self.address or self.operation or self.value:
                raise ValueError('noncanonical hello')
        elif not (2 <= self.sequence <= MAX_MARKERS + 1 and 0 < self.address < 1 << 36 and
                  self.address % 4 == 0 and (self.operation == WRITE32 or
                  self.operation == READ32 and self.value == 0)):
            raise ValueError('noncanonical marker')
        return PACKET.pack(MAGIC, *values)


def decode(payload):
    if not isinstance(payload, bytes) or len(payload) != PACKET.size:
        raise ValueError('control payload must be exactly 48 bytes')
    magic, *fields = PACKET.unpack(payload)
    if magic != MAGIC:
        raise ValueError('control magic/version mismatch')
    message = Message(*fields)
    message.encode()  # Same canonical contract as the C decoder.
    return message


def acknowledge(message):
    if message.kind not in (HELLO, MARKER):
        raise ValueError('only device requests receive an ACK')
    message.encode()
    return replace(message, kind=message.kind + 1)


def frame(message, reply=False):
    if message.kind not in ((HELLO_ACK, MARKER_ACK) if reply else (HELLO, MARKER)):
        raise ValueError('control direction/kind mismatch')
    source, target = (WIRE.HOST_IP, WIRE.PHONE_IP) if reply else (WIRE.PHONE_IP, WIRE.HOST_IP)
    source_mac, target_mac = ((WIRE.HOST_MAC, WIRE.PHONE_MAC) if reply else
                              (WIRE.PHONE_MAC, WIRE.HOST_MAC))
    payload = message.encode()
    udp = struct.pack('!HHHH', PORT, PORT, 8 + len(payload), 0) + payload
    checksum = WIRE.checksum(source + target + struct.pack('!BBH', 0, 17, len(udp)) + udp) or 0xffff
    udp = udp[:6] + struct.pack('!H', checksum) + udp[8:]
    return WIRE.ethernet(target_mac, source_mac, 0x800, WIRE.ipv4(source, target, 17, udp))


def is_control(frame_bytes):
    if not isinstance(frame_bytes, bytes) or len(frame_bytes) < 42 or frame_bytes[12:14] != b'\x08\0':
        return False
    ip = frame_bytes[14:]
    ihl = (ip[0] & 15) * 4
    return (ip[0] >> 4 == 4 and 20 <= ihl <= 60 and len(ip) >= ihl + 8 and
            ip[9] == 17 and struct.unpack_from('!H', ip, ihl + 2)[0] == PORT)


def decode_request_frame(packet):
    if not isinstance(packet, bytes) or len(packet) != 90 or packet[:14] != (
            WIRE.HOST_MAC + WIRE.PHONE_MAC + b'\x08\0'):
        raise ValueError('control Ethernet identity/length mismatch')
    ip = packet[14:34]
    total, fragment = struct.unpack_from('!HH', ip, 2)[0], struct.unpack_from('!H', ip, 6)[0]
    if (ip[0] != 0x45 or total != 76 or fragment & ~0x4000 or ip[9] != 17 or
            WIRE.checksum(ip) or ip[12:16] != WIRE.PHONE_IP or ip[16:20] != WIRE.HOST_IP):
        raise ValueError('control IPv4 checksum, shape or identity mismatch')
    udp = packet[34:]
    source, target, length, checksum = struct.unpack_from('!4H', udp)
    if (source != PORT or target != PORT or length != 56 or not checksum or
            WIRE.checksum(WIRE.PHONE_IP + WIRE.HOST_IP + struct.pack('!BBH', 0, 17, length) + udp)):
        raise ValueError('control UDP checksum, length or port mismatch')
    message = decode(udp[8:])
    if message.kind not in (HELLO, MARKER):
        raise ValueError('device control packet must be a request')
    return message


class HostReadyProtocol:
    """Pure packet protocol; record() must finish before an ACK is returned.

    Caller injects returned frames only on the already verified ECM binding.
    Call echo_transmitted() only after the returned nonce echo was actually
    injected in full. Returning a queued request alone cannot prove a ping.
    """
    def __init__(self, boot_id, record):
        if not WIRE.valid_boot_id(boot_id) or not callable(record):
            raise ValueError('canonical fresh boot ID and recorder required')
        self.wire = WIRE.Protocol(boot_id)
        self.boot_nonce, self.record = int(boot_id, 16), record
        self.echo_sent = self.echo_offered = self.failed = False
        self.pending = self.last = None
        self.cookie = None
        self.acks = self.rejected = 0

    def arp_request(self):
        return self.wire.arp_request()

    def echo_transmitted(self, packet):
        if not self.echo_offered or packet != self.wire.echo_request():
            raise ValueError('echo injection does not match the offered nonce request')
        self.echo_sent = True

    def _reply(self, retry=False):
        freshness = self.wire.log_freshness
        if self.wire.log_overflow or freshness in ('duplicate', 'mismatch'):
            self.failed = True
        if (self.failed or self.pending is None or not self.echo_sent or not self.wire.echo_seen or
                not self.wire.arp_seen or freshness != 'matched'):
            return []
        message = self.pending
        if self.last == message and not retry:
            return []
        if self.last != message:
            try:
                self.record(message)
            except BaseException:
                self.failed = True
                raise
            self.last, self.acks = message, 0
        if self.acks >= MAX_ACKS:
            return []
        self.acks += 1
        return [frame(acknowledge(message), reply=True)]

    def feed(self, packet):
        if not is_control(packet):
            replies = self.wire.feed(packet)
            if not self.echo_sent:
                self.wire.echo_seen = False
            if self.wire.arp_seen and not self.echo_sent and not self.echo_offered:
                replies.append(self.wire.echo_request())
                self.echo_offered = True
            return replies + self._reply()
        if self.failed:
            return []
        try:
            message = decode_request_frame(packet)
        except ValueError:
            self.rejected += 1
            return []
        if message.boot_nonce != self.boot_nonce or (self.cookie is not None and message.cookie != self.cookie):
            self.rejected += 1
            return []
        if self.cookie is None:
            if message.kind != HELLO:
                self.rejected += 1
                return []
            self.cookie, self.pending = message.cookie, message
        elif self.pending == message:
            pass
        elif (self.last is not None and message.kind == MARKER and
              message.sequence == self.last.sequence + 1):
            self.pending = message
        else:
            self.rejected += 1
            return []
        return self._reply(retry=True)
