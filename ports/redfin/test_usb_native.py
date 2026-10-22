"""Native ECM identity, bounded lifecycle and libpcap ABI checks; no USB actions."""
import ctypes as C
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('redfin_usb_native_tested', HERE / 'usb-native.py')
N = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = N
SPEC.loader.exec_module(N)
BOOT = '0123456789abcdef'
LOCATION = 0x03100000


def usb_node(vendor=0x1209, product=1, location=LOCATION, children=()):
    return {'IOObjectClass': 'IOUSBHostDevice', 'idVendor': vendor,
            'idProduct': product, 'locationID': location,
            'USB Serial Number': 'PRIVATE MUST NOT RETAIN',
            'IORegistryEntryChildren': list(children)}


def interface(name='en9', unit=9):
    return {'IOObjectClass': 'IOSkywalkLegacyEthernetInterface', 'IOInterfaceType': 6,
            'BSD Name': name, 'IOInterfaceNamePrefix': 'en', 'IOInterfaceUnit': unit}


def ecm_tree(child, descriptor=N.WIRE.HOST_MAC, skywalk=True):
    children = [child]
    if skywalk:
        children = [{'IOObjectClass': 'IOSkywalkLegacyEthernet', 'IOMACAddress': descriptor,
                     'IORegistryEntryChildren': children}]
    return {'IOObjectClass': 'IOUserNetworkEthernet', 'IOUserClass': 'AppleUserECM',
            'IOMACAddress': descriptor, 'IORegistryEntryChildren': children}


def gadget(name='en9', location=LOCATION, descriptor=N.WIRE.HOST_MAC, skywalk=True):
    return N.Service(location, 0x1209, 1, (name,), (N.Binding(name, descriptor, skywalk),))


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Registry:
    def __init__(self, snapshots=None, mac_error=False, reported_mac=N.WIRE.HOST_MAC):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        target = gadget()
        self.snapshots = list(snapshots if snapshots is not None else ([google], [target]))
        self.calls, self.mac_error = [], mac_error
        self.reported_mac = reported_mac

    def snapshot(self, timeout=2):
        self.calls.append('snapshot')
        item = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        if isinstance(item, Exception):
            raise item
        return item

    def verify_mac(self, name, timeout=2):
        self.calls.append(('verify_mac', name))
        if self.mac_error:
            raise N.NativeError('MAC mismatch')
        return self.reported_mac


class Capture:
    def __init__(self, frames=(), read_error=None, send_error=None):
        self.frames = list(frames)
        self.sent, self.closed, self.truncated = [], 0, 0
        self.read_error, self.send_error = read_error, send_error

    def send(self, packet):
        self.sent.append(packet)
        if self.send_error:
            raise self.send_error

    def read(self):
        if self.read_error:
            raise self.read_error
        return self.frames.pop(0) if self.frames else b''

    def close(self):
        self.closed += 1


class Pcap:
    def __init__(self, capture=None, error=None):
        self.capture, self.error, self.opens = capture or Capture(), error, []

    def open(self, name):
        self.opens.append(name)
        if self.error:
            raise self.error
        return self.capture


class NativeIdentityTests(unittest.TestCase):
    def test_only_ethernet_bsd_descendant_of_exact_usb_device_is_retained(self):
        child = ecm_tree(interface())
        raw = [usb_node(children=[child]), {'BSD Name': 'en0', 'IOInterfaceType': 6}]
        self.assertEqual(N.registry_services(raw), [gadget()])
        self.assertNotIn('PRIVATE', repr(N.registry_services(raw)))
        self.assertEqual(N.registry_services({'IORegistryEntryChildren': raw}),
                         [gadget()])

    def test_prefix_unit_is_accepted_without_bsd_name_and_conflicts_are_rejected(self):
        node = interface()
        del node['BSD Name']
        self.assertEqual(N.registry_services([usb_node(children=[node])])[0].interfaces, ('en9',))
        with self.assertRaisesRegex(N.NativeError, 'inconsistent'):
            N.registry_services([usb_node(children=[interface('en8', 9)])])

    def test_unrelated_names_and_downstream_usb_interfaces_are_not_borrowed(self):
        bad = interface()
        bad['IOInterfaceType'] = 24
        nested = usb_node(vendor=0x1234, children=[interface('en1', 1)])
        items = N.registry_services([usb_node(children=[bad, nested])])
        self.assertEqual(items[0].interfaces, ())
        items = N.registry_services([usb_node(children=[interface('../en9', -1)])])
        self.assertEqual(items[0].interfaces, ())

    def test_baseline_and_target_fail_closed_on_missing_ambiguous_or_wrong_port(self):
        g = N.Service(LOCATION, 0x18d1, 0x4ee0)
        for items in ([], [g, g]):
            with self.assertRaises(N.NativeError):
                N.baseline_location(items)
        self.assertEqual(N.baseline_location([g]), LOCATION)
        target = N.Service(LOCATION + 1, 0x1209, 1)
        with self.assertRaisesRegex(N.NativeError, 'location differs'):
            N.target_service([target], LOCATION)
        with self.assertRaisesRegex(N.NativeError, 'ambiguous'):
            N.target_service([target, target], LOCATION)
        self.assertIsNone(N.target_service([], LOCATION))

    def test_registry_empty_disconnect_and_invalid_plist_are_distinct(self):
        for payload in (b'', b'  \n'):
            command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=payload))
            with self.assertRaises(N.RegistryTransient):
                N.Registry(command).snapshot()
        command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=b'bad plist'))
        with self.assertRaisesRegex(N.NativeError, 'malformed'):
            N.Registry(command).snapshot()
        command.side_effect = subprocess.TimeoutExpired('ioreg', 2)
        with self.assertRaisesRegex(N.NativeError, 'timed out'):
            N.Registry(command).snapshot()

    def test_registry_output_bound_and_missing_location(self):
        command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=b'x' * (N.MAX_REGISTRY_BYTES + 1)))
        with self.assertRaisesRegex(N.NativeError, 'size bound'):
            N.Registry(command).snapshot()
        raw = usb_node(location=0)
        with self.assertRaisesRegex(N.NativeError, 'locationID'):
            N.registry_services([raw])

    def test_ifconfig_corrobates_exact_mac_and_never_runs_a_write_command(self):
        command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=(
            'en9: flags=8863<UP> mtu 1500\n\tether 02:00:5e:77:ee:01\n').encode()))
        self.assertEqual(N.Registry(command).verify_mac('en9'), N.WIRE.HOST_MAC)
        self.assertEqual(command.call_args.args[0], ['/sbin/ifconfig', 'en9'])
        command.return_value.stdout = b'en9: flags=8863<UP> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n'
        with self.assertRaisesRegex(N.NativeError, 'MAC differs'):
            N.Registry(command).verify_mac('en9')
        with self.assertRaisesRegex(N.NativeError, 'invalid BSD'):
            N.Registry(command).verify_mac('en9;touch x')
        self.assertEqual(command.call_count, 2)

    def test_ifconfig_accepts_only_descriptor_or_known_redacted_report(self):
        for mac in (N.MAC, '02:00:00:00:00:00'):
            command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=(
                'en9: flags=8863<UP> mtu 1500\n\tether ' + mac + '\n').encode()))
            self.assertEqual(N.Registry(command).verify_mac('en9'), bytes.fromhex(mac.replace(':', '')))
        for mac in ('00:00:00:00:00:00', '02:00:5e:77:ee:02', '02:11:22:33:44:55'):
            command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=(
                'en9: flags=8863<UP> mtu 1500\n\tether ' + mac + '\n').encode()))
            with self.assertRaisesRegex(N.NativeError, 'MAC differs'):
                N.Registry(command).verify_mac('en9')

    def test_descriptor_mac_proof_follows_same_ecm_ancestor_and_rejects_conflicting_skywalk(self):
        expected = N.registry_services([usb_node(children=[ecm_tree(interface())])])[0]
        self.assertEqual(expected.bindings, (N.Binding('en9', N.WIRE.HOST_MAC, True),))
        # An expected MAC on a sibling is not ancestry proof.
        raw = usb_node(children=[interface(), ecm_tree({'IOObjectClass': 'Unrelated'})])
        self.assertEqual(N.registry_services([raw])[0].bindings, (N.Binding('en9', b'', False),))
        raw = ecm_tree(interface())
        raw['IORegistryEntryChildren'][0]['IOMACAddress'] = N.MASKED_MAC
        self.assertEqual(N.registry_services([usb_node(children=[raw])])[0].bindings,
                         (N.Binding('en9', b'', True),))


class NativeLifecycleTests(unittest.TestCase):
    def run_case(self, registry=None, pcap=None, seconds=1, expect_error=None):
        clock, registry, pcap = Clock(), registry or Registry(), pcap or Pcap()
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / 'out'
            if expect_error:
                with self.assertRaises(expect_error):
                    N.run_probe(registry, pcap, BOOT, seconds, out, clock, clock.sleep)
            else:
                N.run_probe(registry, pcap, BOOT, seconds, out, clock, clock.sleep)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((out / 'kernel.log').stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE((out / 'manifest.json').stat().st_mode), 0o600)
            self.assertFalse(manifest['capture_authenticated'])
            self.assertFalse(manifest['network_modified'])
            self.assertFalse(manifest['promiscuous'])
            return manifest, pcap, registry, clock

    def test_deadline_closes_once_and_records_incomplete_without_mocking_success(self):
        result, pcap, registry, clock = self.run_case()
        self.assertEqual(result['status'], 'probe-incomplete')
        self.assertEqual(result['end_reason'], 'deadline')
        self.assertFalse(result['arp_seen'])
        self.assertFalse(result['echo_seen'])
        self.assertEqual(pcap.capture.closed, 1)
        self.assertEqual(pcap.capture.sent, [N.WIRE.Protocol(BOOT).arp_request()])
        self.assertIn(('verify_mac', 'en9'), registry.calls)
        self.assertLessEqual(clock.now, 1.001)

    def test_wrong_port_and_mac_stop_before_pcap_open_or_injection(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        bad = gadget(location=LOCATION + 1)
        result, pcap, _, _ = self.run_case(Registry([[google], [bad]]), expect_error=N.NativeError)
        self.assertEqual(pcap.opens, [])
        self.assertEqual(result['status'], 'error')
        result, pcap, _, _ = self.run_case(Registry(mac_error=True), expect_error=N.NativeError)
        self.assertEqual(pcap.opens, [])

    def test_masked_ifconfig_report_uses_descriptor_wire_mac_without_host_network_edits(self):
        result, pcap, _, _ = self.run_case(Registry(reported_mac=N.MASKED_MAC))
        self.assertEqual(result['reported_mac'], '02:00:00:00:00:00')
        self.assertEqual(result['descriptor_mac'], N.MAC)
        self.assertEqual(result['wire_mac'], N.MAC)
        self.assertEqual(result['mac_profile'], 'ifconfig-masked')
        self.assertEqual(pcap.capture.sent[0][6:12], N.WIRE.HOST_MAC)
        self.assertEqual(pcap.capture.sent[0][22:28], N.WIRE.HOST_MAC)
        self.assertNotIn('02:00:00:00:00:00', N.FILTER)
        self.assertFalse(result['network_modified'])

    def test_missing_wrong_or_ambiguous_descriptor_proof_never_opens_capture(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        missing = N.Service(LOCATION, 0x1209, 1, ('en9',))
        ambiguous = N.Service(LOCATION, 0x1209, 1, ('en9',),
                              (N.Binding('en9', N.WIRE.HOST_MAC, True),
                               N.Binding('en9', N.MASKED_MAC, True)))
        for target in (missing, gadget(descriptor=N.MASKED_MAC), ambiguous):
            with self.subTest(target=target):
                result, pcap, _, _ = self.run_case(Registry([[google], [target]]), expect_error=N.NativeError)
                self.assertEqual(pcap.opens, [])
                self.assertIn('descriptor MAC', result['error'])

    def test_masked_report_requires_skywalk_ancestry_and_post_open_report_is_stable(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        no_skywalk = gadget(skywalk=False)
        result, pcap, _, _ = self.run_case(Registry([[google], [no_skywalk]], reported_mac=N.MASKED_MAC),
                                           expect_error=N.NativeError)
        self.assertEqual(pcap.opens, [])
        registry = Registry()
        values = iter((N.WIRE.HOST_MAC, N.MASKED_MAC))
        registry.verify_mac = lambda *a, **k: next(values)
        result, pcap, _, _ = self.run_case(registry, expect_error=N.NativeError)
        self.assertEqual(pcap.opens, ['en9'])
        self.assertEqual(pcap.capture.sent, [])
        self.assertEqual(pcap.capture.closed, 1)
        self.assertEqual(result['status'], 'error')

    def test_no_interface_timeout_never_opens_capture(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        target = N.Service(LOCATION, 0x1209, 1)
        result, pcap, _, clock = self.run_case(Registry([[google], [target]]), expect_error=TimeoutError)
        self.assertEqual(pcap.opens, [])
        self.assertEqual(result['status'], 'error')
        self.assertLessEqual(clock.now, 1.001)

    def test_capture_open_and_injection_failures_do_not_retry(self):
        result, pcap, _, _ = self.run_case(pcap=Pcap(error=N.NativeError('access denied')), expect_error=N.NativeError)
        self.assertEqual(pcap.opens, ['en9'])
        capture = Capture(send_error=N.NativeError('short write'))
        result, _, _, _ = self.run_case(pcap=Pcap(capture), expect_error=N.NativeError)
        self.assertEqual(len(capture.sent), 1)
        self.assertEqual(capture.closed, 1)

    def test_normal_disconnect_is_incomplete_and_read_error_only_suppressed_after_absence(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        target = gadget()
        result, pcap, _, _ = self.run_case(Registry([[google], [target], [target], []]))
        self.assertEqual(result['end_reason'], 'device-disconnected')
        self.assertEqual(result['status'], 'probe-incomplete')
        capture = Capture(read_error=N.NativeError('device read failed'))
        result, _, _, _ = self.run_case(Registry([[google], [target], [target], [target], []]), Pcap(capture))
        self.assertEqual(result['end_reason'], 'device-disconnected')
        capture = Capture(read_error=N.NativeError('still connected read failed'))
        result, _, _, _ = self.run_case(pcap=Pcap(capture), expect_error=N.NativeError)
        self.assertIn('still connected', result['error'])
        self.assertEqual(capture.closed, 1)

    def test_interface_rebinding_fails_and_closes_without_reopen(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        target = gadget()
        changed = gadget('en10')
        result, pcap, _, _ = self.run_case(Registry([[google], [target], [changed]]), expect_error=N.NativeError)
        self.assertEqual(pcap.opens, ['en9'])
        self.assertEqual(pcap.capture.closed, 1)
        self.assertEqual(pcap.capture.sent, [])  # Changed after open, before any injection.

    def test_transient_empty_or_timeout_never_counts_as_disconnect(self):
        google = N.Service(LOCATION, 0x18d1, 0x4ee0)
        target = gadget()
        registry = Registry([[google], [target], [target],
                             N.RegistryTransient('empty'), N.RegistryTransient('timeout'), [target]])
        result, pcap, _, _ = self.run_case(registry)
        self.assertEqual(result['end_reason'], 'deadline')
        self.assertEqual(result['registry_transient_errors'], ['empty', 'timeout'])
        self.assertEqual(pcap.capture.closed, 1)

    def test_unsolicited_current_nonce_echo_does_not_become_roundtrip_evidence(self):
        reply = N.WIRE.ethernet(N.WIRE.HOST_MAC, N.WIRE.PHONE_MAC, 0x800, N.WIRE.ipv4(
            N.WIRE.PHONE_IP, N.WIRE.HOST_IP, 1, N.WIRE.icmp_echo(BOOT, reply=True)))
        result, _, _, _ = self.run_case(pcap=Pcap(Capture([reply])))
        self.assertFalse(result['echo_seen'])
        self.assertEqual(result['status'], 'probe-incomplete')

    def test_logs_remain_separate_from_link_verdict_and_preserve_nonce_freshness(self):
        payload = b'REDFIN BOOT ID: fedcba9876543210\n'
        udp = struct.pack('!HHHH', 31337, 5140, 8 + len(payload), 0) + payload
        frame = N.WIRE.ethernet(N.WIRE.HOST_MAC, N.WIRE.PHONE_MAC, 0x800,
                                N.WIRE.ipv4(N.WIRE.PHONE_IP, N.WIRE.HOST_IP, 17, udp))
        result, _, _, _ = self.run_case(pcap=Pcap(Capture([frame])))
        self.assertEqual(result['udp_log_freshness'], 'mismatch')
        self.assertEqual(result['log_bytes'], len(payload))
        self.assertEqual(result['status'], 'probe-incomplete')

    def test_unit_packet_order_requires_arp_then_solicited_echo_and_separate_current_log(self):
        def incoming(body, kind=0x800):
            return N.WIRE.ethernet(N.WIRE.HOST_MAC, N.WIRE.PHONE_MAC, kind, body)

        echo = incoming(N.WIRE.ipv4(N.WIRE.PHONE_IP, N.WIRE.HOST_IP, 1,
                                    N.WIRE.icmp_echo(BOOT, reply=True)))
        arp = incoming(struct.pack('!HHBBH6s4s6s4s', 1, 0x800, 6, 4, 2,
                                   N.WIRE.PHONE_MAC, N.WIRE.PHONE_IP,
                                   N.WIRE.HOST_MAC, N.WIRE.HOST_IP), 0x806)
        payload = ('REDFIN BOOT ID: ' + BOOT + '\n').encode()
        udp = incoming(N.WIRE.ipv4(N.WIRE.PHONE_IP, N.WIRE.HOST_IP, 17,
                                    struct.pack('!HHHH', 31337, 5140, 8 + len(payload), 0) + payload))
        # All frames are synthetic unit fixtures, never hardware evidence.
        result, pcap, _, _ = self.run_case(pcap=Pcap(Capture([echo, arp, echo, udp])))
        self.assertEqual(result['status'], 'link-ready')
        self.assertTrue(result['arp_seen'])
        self.assertTrue(result['echo_seen'])
        self.assertEqual(result['udp_log_freshness'], 'matched')
        self.assertEqual(result['log_bytes'], len(payload))
        wire = N.WIRE.Protocol(BOOT)
        self.assertEqual(pcap.capture.sent, [wire.arp_request(), wire.echo_request()])


class Function:
    def __init__(self, value=0):
        self.value, self.calls = value, []

    def __call__(self, *args):
        self.calls.append(args)
        return self.value


def fake_library():
    methods = ('create geterr set_snaplen set_promisc set_timeout set_immediate_mode activate setnonblock '
               'datalink compile setfilter freecode next_ex inject close').split()
    lib = SimpleNamespace(**{'pcap_' + name: Function() for name in methods})
    lib.pcap_create.value, lib.pcap_datalink.value = 0x123456789abcdef, 1
    lib.pcap_geterr.value = b'fake native error'
    return lib


class NativeFFITests(unittest.TestCase):
    def test_all_pointer_bearing_native_signatures_are_typed_before_use(self):
        lib = fake_library()
        pcap = N.PCap(loader=lambda _: lib)
        self.assertEqual(lib.pcap_create.restype, C.c_void_p)
        self.assertEqual(lib.pcap_inject.argtypes, [C.c_void_p, C.c_void_p, C.c_size_t])
        self.assertEqual(lib.pcap_next_ex.argtypes[0], C.c_void_p)
        self.assertEqual(C.sizeof(N.PacketHeader), 280)
        self.assertEqual(N.PacketHeader.caplen.offset, 16)
        self.assertEqual(C.sizeof(N.BPFProgram), 16)
        handle = pcap.open('en9')
        self.assertEqual(lib.pcap_set_promisc.calls, [(handle.value, 0)])
        self.assertEqual(lib.pcap_set_snaplen.calls, [(handle.value, 2048)])
        self.assertEqual(lib.pcap_setnonblock.calls[0][1], 1)
        self.assertEqual(lib.pcap_compile.calls[0][2], N.FILTER.encode())
        self.assertEqual(len(lib.pcap_freecode.calls), 1)
        handle.close()
        handle.close()
        self.assertEqual(len(lib.pcap_close.calls), 1)

    def test_open_failure_closes_native_pointer_and_frees_filter(self):
        for step in ('set_promisc', 'setnonblock', 'setfilter'):
            with self.subTest(step=step):
                lib = fake_library()
                getattr(lib, 'pcap_' + step).value = -1
                with self.assertRaises(N.NativeError):
                    N.PCap(loader=lambda _: lib).open('en9')
                self.assertEqual(len(lib.pcap_close.calls), 1)
                self.assertEqual(len(lib.pcap_freecode.calls), int(step == 'setfilter'))
        lib = fake_library()
        lib.pcap_datalink.value = 12
        with self.assertRaisesRegex(N.NativeError, 'DLT_EN10MB'):
            N.PCap(loader=lambda _: lib).open('en9')
        self.assertEqual(len(lib.pcap_close.calls), 1)

    def test_native_library_smoke_loads_symbols_without_opening_device(self):
        if sys.platform != 'darwin':
            self.skipTest('Darwin libpcap ABI smoke only')
        lib = N.PCap()
        self.assertEqual(lib.lib.pcap_create.restype, C.c_void_p)
        self.assertEqual(lib.lib.pcap_inject.restype, C.c_int)
        self.assertEqual(lib.lib.pcap_close.argtypes, [C.c_void_p])

    def test_ffi_read_lengths_null_and_short_injection_fail_without_retransmission(self):
        lib = fake_library()
        backend = N.PCap(loader=lambda _: lib)
        capture = N.Capture(backend, 123)
        packet = (C.c_ubyte * 2049)(*([1] * 2049))
        header = N.PacketHeader()

        def next_ex(value, header_pointer, data_pointer):
            C.cast(header_pointer, C.POINTER(C.POINTER(N.PacketHeader)))[0] = C.pointer(header)
            C.cast(data_pointer, C.POINTER(C.POINTER(C.c_ubyte)))[0] = C.cast(packet, C.POINTER(C.c_ubyte))
            return 1

        lib.pcap_next_ex = next_ex
        header.caplen, header.length = 60, 60
        self.assertEqual(capture.read(), b'\1' * 60)
        header.caplen, header.length = 42, 60
        self.assertEqual(capture.read(), b'')
        self.assertEqual(capture.truncated, 1)
        for size, original in ((2049, 2049), (60, 42)):
            header.caplen, header.length = size, original
            with self.assertRaisesRegex(N.NativeError, 'invalid packet length'):
                capture.read()
        lib.pcap_next_ex = lambda *_: 1
        with self.assertRaisesRegex(N.NativeError, 'null packet/header'):
            capture.read()
        lib.pcap_inject.value = 1
        with self.assertRaisesRegex(N.NativeError, 'not retransmitted: fake native error'):
            capture.send(bytes(42))
        self.assertEqual(len(lib.pcap_inject.calls), 1)

    def test_darwin_sdk_struct_layout_matches_ctypes(self):
        compiler = shutil.which('cc')
        if sys.platform != 'darwin' or not compiler:
            self.skipTest('Darwin SDK ABI smoke only')
        source = '''#include <pcap/pcap.h>
#include <stddef.h>
#include <stdio.h>
int main(void) { printf("%zu %zu %zu %zu %zu\\n", sizeof(struct timeval),
    sizeof(((struct timeval*)0)->tv_usec), sizeof(struct pcap_pkthdr),
    offsetof(struct pcap_pkthdr, caplen), sizeof(struct bpf_program)); }
'''
        with tempfile.TemporaryDirectory() as temporary:
            src, binary = Path(temporary) / 'abi.c', Path(temporary) / 'abi'
            src.write_text(source)
            subprocess.run([compiler, str(src), '-o', str(binary)], capture_output=True,
                           check=True, timeout=20)
            result = subprocess.run([str(binary)], capture_output=True, check=True, timeout=2)
        self.assertEqual([int(n) for n in result.stdout.split()],
                         [C.sizeof(N.Timeval), C.sizeof(C.c_int), C.sizeof(N.PacketHeader),
                          N.PacketHeader.caplen.offset, C.sizeof(N.BPFProgram)])


if __name__ == '__main__':
    unittest.main()
