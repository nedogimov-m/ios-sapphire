"""Execute the actual native retained-power/AOP probe against bounded MMIO."""
import ctypes as C
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import wifi_platform as P
from test_rpmh_probe import added_file
from test_wifi_native_probe import HARNESS as OBSERVER_HARNESS

HERE = Path(__file__).resolve().parent
ARGS = ('debug=0xc serial=3 cpus=1 keepsyms=1 -noprogress rd=md0 '
        'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 '
        'modem=0 wifi=0 gpu=0 redfinwifi=2 redfinwifinative=1 redfinwifipower=1 '
        'redfinspmi=1 redfinreturn=1 redfinbootid=0x0000000000000001')


def database():
    data = bytearray(0x20000)
    struct.pack_into('<II', data, 0, 1, 0x0c0330db)
    struct.pack_into('<5H', data, 8, 3, 0, 0x100, 3, 0x1000)
    resources = [('cx.lvl', 0x30000, (0, 16, 64, 128, 192, 256, 384, 416)),
                 ('mss.lvl', 0x30060, (0, 64, 128, 192, 256, 320, 384)),
                 ('xo.lvl', 0x300a0, (0, 32, 80, 128))]
    for index, (name, address, levels) in enumerate(resources):
        at = 144 + index * 24
        data[at:at + 8] = name.encode().ljust(8, b'\0')
        struct.pack_into('<IIIHH', data, at + 8, 1, 2, address, 32, 32 * index)
        struct.pack_into('<16H', data, 144 + 0x100 + 32 * index, *(levels + (0,) * (16 - len(levels))))
    return data


MODEL = r'''
alignas(16) static uint8_t ipcc[0x1000],rsc[0x10000],gcc[0x1f0000],gic[0x4000];
static uint64_t power_ranges[12];static uint32_t power_witness[16],power_marker;
static int power_enabled,bad_power_node,bad_power_length,register_issue;
static unsigned thread_owner,model_issue,write_count,fail_store,cancel_store,delay_total,message_count;
static unsigned mutation_store,mutation_kind;
static uint32_t trace[256][3],held_values[3];static uint8_t message[64];
static char command_line[608];
static uint32_t model_word(const uint8_t *base,unsigned at){uint32_t value;memcpy(&value,base+at,4);return value;}
static void model_put(uint8_t *base,unsigned at,uint32_t value){memcpy(base+at,&value,4);}
static void wf_harness_write(uintptr_t base,unsigned unit,uint32_t offset,uint32_t value) {
    ++write_count;
    if(write_count<=256){trace[write_count-1][0]=unit;trace[write_count-1][1]=offset;trace[write_count-1][2]=value;}
    else ++unsafe;
    uint32_t actual=write_count==fail_store ? value^1u : value;
    memcpy((void *)(base+offset),&actual,4);
    if(unit==2 && offset==0xd14 && value==0x1010000 && write_count!=fail_store) {
        unsigned index=model_word(rsc,0xd34)==0x30000 ? 0 : model_word(rsc,0xd34)==0x30060 ? 1 : 2;
        held_values[index]=model_word(rsc,0xd38);
        if(model_issue!=1) {
            model_put(rsc,0xd04,1);model_put(rsc,0xd18,model_issue==2 ? 0 : 1);
            model_put(rsc,0xd3c,model_issue==3 ? 0x100 : 0x10101);
            model_put(gic,0x204,1u<<5);
        }
    }
    if(unit==2 && offset==0xd08 && value==1 && model_issue!=4 && write_count!=fail_store)model_put(rsc,0xd04,0);
    if(unit==1 && offset==12 && value==0 && write_count!=fail_store && model_issue!=5) {
        if(model_word(aop,0x24)==0xffff)model_put(aop,0x28,0xffff);
        if(model_word(aop,0x2c)==0xffff)model_put(aop,0x14,0xffff);
        if(model_word(aop,0x18)==0xffff)model_put(aop,0x30,0xffff);
        unsigned box=model_word(aop,0x38);
        if(box>=64 && box<=0x1000-68 && model_word(aop,box)==64) {
            ++message_count;memcpy(message,aop+box+4,64);
            if(model_issue!=6)model_put(aop,box,0);
        }
    }
    if(write_count==mutation_store) {
        if(mutation_kind==1)model_put(rsc,0xd00+0x2a0*2+0x38,model_word(rsc,0xd00+0x2a0*2+0x38)^1);
        if(mutation_kind==2)model_put(db,144+16,0x30004);
        if(mutation_kind==3)model_put(gic,0x104,1u<<5);
        if(mutation_kind==4)thread_owner=2;
        if(mutation_kind==5)command_line[0]='x';
        if(mutation_kind==6)register_issue=1;
        if(mutation_kind==7)model_put(rsc,0xd30,0x10109);
    }
    if(write_count==cancel_store)ready=0;
}
static void IODelay(uint32_t us){delay_total+=us;}
'''

API = r'''
extern "C" void power_reset(void) {
    reset();memset(&wf_power,0,sizeof(wf_power));
    memset(ipcc,0,sizeof(ipcc));memset(rsc,0,sizeof(rsc));memset(gcc,0,sizeof(gcc));memset(gic,0,sizeof(gic));
    memset(trace,0,sizeof(trace));memset(held_values,0,sizeof(held_values));memset(message,0,sizeof(message));
    memcpy(power_ranges,wf_power_ranges,sizeof(power_ranges));memcpy(power_witness,wf_power_witness,sizeof(power_witness));
    power_enabled=power_marker=thread_owner=1;bad_power_node=bad_power_length=register_issue=0;
    model_issue=write_count=fail_store=cancel_store=delay_total=message_count=mutation_store=mutation_kind=0;
    memset(command_line,0,sizeof(command_line));
    model_put(rsc,0,0x10000);model_put(rsc,0xc,(16u<<27)|(8u<<12));model_put(rsc,0xd00,3);
    for(unsigned t=0;t<8;t++)model_put(rsc,0xd00+t*0x2a0+0x18,1);
    model_put(gcc,0x71004,1);
}
extern "C" void power_args(const char *args) {memset(command_line,0,sizeof(command_line));strncpy(command_line,args,sizeof(command_line)-1);}
extern "C" int power_args_valid(const char *args,unsigned bytes){return wf_power_args(args,bytes);}
extern "C" uint8_t *power_region(unsigned unit){uint8_t *regions[]={aop,ipcc,rsc,gcc,gic,db};return unit<6 ? regions[unit] : NULL;}
extern "C" void power_option(unsigned which,unsigned value) {
    switch(which) {
    case 0:power_enabled=(int)value;break;case 1:bad_power_node=(int)value;break;case 2:bad_power_length=(int)value;break;
    case 3:power_marker=value;break;case 4:register_issue=(int)value;break;case 5:thread_owner=value;break;
    case 6:model_issue=value;break;case 7:fail_store=value;break;case 8:cancel_store=value;break;
    case 9:mutation_store=value;break;case 10:mutation_kind=value;break;
    }
}
extern "C" void power_range(unsigned index,uint64_t value){if(index<12)power_ranges[index]=value;}
extern "C" void power_witness_word(unsigned index,uint32_t value){if(index<16)power_witness[index]=value;}
extern "C" unsigned power_metric(unsigned which) {
    unsigned values[]={write_count,wf_power.held,wf_power.poisoned,wf_power.aop.load_state,wf_power.aop.open,
        delay_total,unsafe,wf_power.phase,message_count,wf_power.step,wf_power.stores,wf_power.notifications,
        held_values[0],held_values[1],held_values[2]};
    return which<sizeof(values)/sizeof(values[0]) ? values[which] : 0;
}
extern "C" unsigned power_trace(unsigned index,unsigned field){return index<write_count && index<256 && field<3 ? trace[index][field] : UINT32_MAX;}
extern "C" const uint8_t *power_message(void){return message;}
'''


def harness():
    source = OBSERVER_HARNESS

    def replace(before, after):
        nonlocal source
        assert source.count(before) == 1, before
        source = source.replace(before, after)

    replace('static thread_t current_thread(void){return (thread_t)1;}',
            'static unsigned thread_owner;static thread_t current_thread(void){return (thread_t)(uintptr_t)thread_owner;}')
    replace('static const char *PE_boot_args(void){return "";}',
            'static char command_line[608];static const char *PE_boot_args(void){return command_line;}')
    replace('static uint64_t wf_test_register(const char *key){return !strcmp(key,"CurrentEL") ? 4 : 0;}',
            'static int register_issue;static uint64_t wf_test_register(const char *key){return !strcmp(key,"CurrentEL") ? (register_issue==1 ? 0 : 4) : (register_issue==2 ? 1 : 0);}')
    replace('static void IODelay(uint32_t){}', 'static void IODelay(uint32_t);')
    replace('static int enabled,cpus,spmi,returned,ready,modem,wifi,gpu,usb,gui,smp,wifi_mode;',
            'static int enabled,cpus,spmi,returned,ready,modem,wifi,gpu,usb,gui,smp,wifi_mode;\n'
            'static int power_enabled,bad_power_node,bad_power_length;\n'
            'static uint64_t power_ranges[12];static uint32_t power_witness[16],power_marker;')
    replace('if(!strcmp(key,"redfinwifinative"))value=enabled;',
            'if(!strcmp(key,"redfinwifipower"))value=power_enabled;\n    else if(!strcmp(key,"redfinwifinative"))value=enabled;')
    replace('if(!strcmp(path,"/redfin-wifi-native") && !bad_node){*out=3;return 0;}',
            'if(!strcmp(path,"/redfin-wifi-native") && !bad_node){*out=3;return 0;}\n'
            '    if(!strcmp(path,"/redfin-wifi-power") && !bad_power_node){*out=4;return 0;}')
    replace('    if(entry==3) {', '''    if(entry==4) {
        if(!strcmp(key,"reg")){*out=power_ranges;*bytes=sizeof(power_ranges)-(bad_power_length==1 ? 1 : 0);return 0;}
        if(!strcmp(key,"source-contract")){*out=power_witness;*bytes=sizeof(power_witness)-(bad_power_length==2 ? 1 : 0);return 0;}
        if(!strcmp(key,"live-fdt-verified")){*out=&power_marker;*bytes=4-(bad_power_length==3 ? 1 : 0);return 0;}
    }
    if(entry==3) {''')
    # MMIO arrays must precede the fake mapping classes. Model functions follow
    # their shared counters and the original observer region definitions.
    model = MODEL.replace('static uint64_t power_ranges[12];static uint32_t power_witness[16],power_marker;\n', '')
    model = model.replace('static int power_enabled,bad_power_node,bad_power_length,register_issue;\n', '')
    model = model.replace('static unsigned thread_owner,model_issue', 'static unsigned model_issue')
    model = model.replace('static char command_line[608];\n', '')
    replace('class IOMemoryMap {', model + '\nclass IOMemoryMap {')
    replace('if(!address || direction!=kIODirectionIn){++unsafe;return NULL;}', '''
        if(physical==0x408000 && size==0x1000)address=(uintptr_t)ipcc;
        if(physical==0x18220000 && size==0x10000)address=(uintptr_t)rsc;
        if(physical==0x100000 && size==0x1f0000)address=(uintptr_t)gcc;
        if(physical==0x17a00000 && size==0x4000)address=(uintptr_t)gic;
        bool writable=power_enabled && (address==(uintptr_t)aop || address==(uintptr_t)ipcc || address==(uintptr_t)rsc);
        if(!address || direction!=(writable ? kIODirectionInOut : kIODirectionIn)){++unsafe;return NULL;}''')
    replace('IOOptionBits expected=kIOMapReadOnly|(address==(uintptr_t)aop ? kIOMapInhibitCache : kIOMapWriteCombineCache);', '''
        bool writable=power_enabled && (address==(uintptr_t)aop || address==(uintptr_t)ipcc || address==(uintptr_t)rsc);
        IOOptionBits expected=(writable ? 0 : kIOMapReadOnly)|
            (power_enabled ? (address==(uintptr_t)db ? kIOMapWriteCombineCache : kIOMapInhibitCache) :
            (address==(uintptr_t)aop ? kIOMapInhibitCache : kIOMapWriteCombineCache));''')
    return source + API


class NativeWifiPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('host C++ compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / 'redfin_rpmh.h').write_text(added_file('redfin_rpmh.h'))
        actual = '\n'.join(line for line in (HERE / 'wifi_native_probe.cpp').read_text().splitlines()
                           if not line.startswith('#include'))
        store = '*(volatile uint32_t *)(context->base[unit] + offset) = value;'
        assert actual.count(store) == 1
        actual = actual.replace(store, 'wf_harness_write(context->base[unit], unit, offset, value);')
        source = directory / 'power.cpp'
        source.write_text(harness().replace('ACTUAL', actual))
        library = directory / 'power.so'
        command = [compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
                   '-I', str(HERE), '-I', str(directory), '-x', 'c++', str(source),
                   str(HERE / 'wifi_aop.c'), '-o', str(library)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.library = C.CDLL(str(library))
        for name in ('power_args',):
            getattr(cls.library, name).argtypes = [C.c_char_p]
        cls.library.power_args_valid.argtypes = [C.c_char_p, C.c_uint]
        cls.library.power_option.argtypes = [C.c_uint, C.c_uint]
        cls.library.set_option.argtypes = [C.c_uint, C.c_uint64]
        cls.library.power_range.argtypes = [C.c_uint, C.c_uint64]
        cls.library.power_witness_word.argtypes = [C.c_uint, C.c_uint]
        cls.library.power_region.restype = C.c_void_p
        cls.library.power_message.restype = C.c_void_p
        cls.library.get_output.restype = C.c_char_p

    def setUp(self):
        self.library.power_reset()
        self.library.power_args(ARGS.encode())
        aop = bytearray(0x1000)
        struct.pack_into('<16I', aop, 0, 0x4d41494c, 1, 0, 0xffff, 0xffff0000,
                         0xffff0000, 0xffff0000, 104, 0xc0, 0xffff0000, 0xffff0000,
                         0xffff0000, 0xffff0000, 728, 0x128, 0)
        C.memmove(self.library.power_region(0), bytes(aop), len(aop))
        C.memmove(self.library.power_region(5), bytes(database()), 0x20000)

    def put(self, unit, offset, value):
        C.memmove(self.library.power_region(unit) + offset, struct.pack('<I', value), 4)

    def word(self, unit, offset):
        return struct.unpack('<I', C.string_at(self.library.power_region(unit) + offset, 4))[0]

    def run_probe(self):
        self.library.redfin_wifi_native_observe()
        self.assertEqual(self.library.metric(6), 0, 'only exact mappings and write paths admitted')
        self.assertEqual(self.library.metric(2), self.library.metric(4), 'every descriptor released')
        self.assertEqual(self.library.metric(3), self.library.metric(5), 'every map released')
        return self.library.get_output().decode()

    def trace(self):
        return [tuple(self.library.power_trace(i, field) for field in range(3))
                for i in range(self.library.power_metric(0))]

    def test_exact_retained_votes_precede_native_aop_handshake_and_single_modem_on(self):
        self.assertIn('result=0', self.run_probe())
        self.assertEqual([self.library.power_metric(i) for i in (1, 2, 3, 4, 8, 12, 13, 14)],
                         [7, 0, 1, 1, 1, 7, 6, 3])
        trace = self.trace()
        self.assertEqual(len(trace), 64)
        self.assertTrue(all(unit == 2 for unit, _offset, _value in trace[:39]))
        self.assertTrue(all(unit in (0, 1) for unit, _offset, _value in trace[39:]))
        self.assertEqual([(trace[i + 1][2], trace[i + 2][2]) for i in (0, 13, 26)],
                         [(0x30000, 7), (0x30060, 6), (0x300a0, 3)])
        self.assertEqual(C.string_at(self.library.power_message(), 64),
                         b'{class: image, res: load_state, name: modem, val: on}'.ljust(64, b'\0'))
        self.assertEqual(self.word(0, 0x128), 0)

    def test_complete_exact_boot_args_reject_duplicates_unknowns_nonce_and_other_writers(self):
        valid = [ARGS, ' '.join(reversed(ARGS.split())), ARGS + ' -enable_kprintf_spam']
        invalid = [ARGS + ' cpus=1', ARGS + ' redfinrpmh=1', ARGS + ' redfingpupower=1',
                   ARGS + ' redfinrail=1', ARGS.replace('cpus=1', 'cpus=8'),
                   ARGS.replace('rd=md0', 'rd=ufsroot0'), ARGS.replace('modem=0', 'modem=1'),
                   ARGS.replace('redfinwifipower=1 ', ''), ARGS + ' unknown=0',
                   ARGS.replace('0000000000000001', '0000000000000000'),
                   ARGS + ' redfinbootid=0x0000000000000001', ARGS + '\t']
        for args in valid:
            self.assertEqual(self.library.power_args_valid(args.encode(), len(args) + 1), 1, args)
        for args in invalid:
            self.assertEqual(self.library.power_args_valid(args.encode(), len(args) + 1), 0, args)
        self.library.power_args((ARGS + ' redfinrpmh=1').encode())
        self.assertIn('refused exact args', self.run_probe())
        self.assertEqual(self.library.metric(0), 0)

    def test_every_power_adt_word_length_marker_and_mapping_failure_refuses_before_writes(self):
        for index, value in enumerate(value for pair in P.POWER_RANGES for value in pair):
            self.setUp(); self.library.power_range(index, value ^ 4)
            self.run_probe(); self.assertEqual(self.library.metric(0), 0)
        for index, value in enumerate(P.POWER_WITNESS):
            self.setUp(); self.library.power_witness_word(index, value ^ 1)
            self.run_probe(); self.assertEqual(self.library.metric(0), 0)
        for option, value in [(1, 1), (2, 1), (2, 2), (2, 3), (3, 0)]:
            self.setUp(); self.library.power_option(option, value)
            self.run_probe(); self.assertEqual(self.library.metric(0), 0)
        for option in (14, 15, 16, 17):
            for index in range(1, 7):
                self.setUp(); self.library.set_option(option, index)
                self.run_probe(); self.assertEqual(self.library.power_metric(0), 0)

    def test_all_exact_arc_aux_words_addresses_versions_and_padding_are_mandatory(self):
        for index in range(3):
            for offset in (144 + index * 24 + 16, 144 + index * 24 + 20, 16):
                self.setUp(); self.put(5, offset, self.word(5, offset) ^ 1)
                self.run_probe(); self.assertEqual(self.library.power_metric(0), 0)
            for level in range(16):
                self.setUp()
                at = 144 + 0x100 + index * 32 + level * 2
                C.memmove(self.library.power_region(5) + at,
                          bytes([C.string_at(self.library.power_region(5) + at, 1)[0] ^ 1]), 1)
                self.run_probe(); self.assertEqual(self.library.power_metric(0), 0)

    def test_inherited_sleep_wake_votes_are_preserved_and_illegal_floors_refuse(self):
        for index, (address, selector) in enumerate(((0x30000, 7), (0x30060, 6), (0x300a0, 3))):
            at = 0xd00 + 0x2a0 * (index + 2)
            self.put(2, at + 0x1c, 1); self.put(2, at + 0x10, 1)
            self.put(2, at + 0x30, 0x10108); self.put(2, at + 0x34, address); self.put(2, at + 0x38, selector)
        before = C.string_at(self.library.power_region(2) + 0xd00 + 0x2a0, 7 * 0x2a0)
        self.assertIn('result=0', self.run_probe())
        self.assertEqual(C.string_at(self.library.power_region(2) + 0xd00 + 0x2a0, 7 * 0x2a0), before)
        for address, selector in ((0x30000, 8), (0x30060, 7), (0x300a0, 4), (0x30001, 1)):
            self.setUp(); at = 0xd00 + 0x2a0 * 2
            self.put(2, at + 0x1c, 1); self.put(2, at + 0x30, 0x10108)
            self.put(2, at + 0x34, address); self.put(2, at + 0x38, selector)
            self.run_probe(); self.assertEqual(self.library.power_metric(0), 0)

    def test_busy_tcs_irq_clock_metadata_and_aop_handoff_refuse_before_any_write(self):
        changes = [(2, 0xd1c, 1), (2, 0xd04, 1), (2, 0xd00, 2), (2, 0xd18, 0),
                   (2, 0xd00 + 0x2a0 + 0x14, 0x10000), (2, 0xc, 0xffffffff),
                   (2, 0, 0x30000), (3, 0x71004, 0), (4, 0x104, 1 << 5),
                   (4, 0x304, 1 << 5), (4, 0x204, 1 << 5), (4, 0x120, 1 << 5),
                   (4, 0x320, 1 << 5), (0, 0, 0), (0, 0x128, 64), (0, 0xc0, 1), (0, 0x2c, 0xffff)]
        for unit, offset, value in changes:
            self.setUp(); self.put(unit, offset, value)
            self.run_probe(); self.assertEqual(self.library.power_metric(0), 0, (unit, offset))

    def test_each_rsc_write_failure_stops_and_never_enters_aop(self):
        for store in range(1, 40):
            self.setUp(); self.library.power_option(7, store)
            output = self.run_probe()
            self.assertNotIn('result=0 ', output, store)
            self.assertEqual(self.library.power_metric(0), store)
            self.assertEqual(self.library.power_metric(8), 0)
            self.assertTrue(all(unit == 2 for unit, _offset, _value in self.trace()))

    def test_each_aop_write_or_notification_failure_retains_votes_and_quarantines(self):
        for store in range(40, 65):
            self.setUp(); self.library.power_option(7, store)
            self.assertNotIn('result=0 ', self.run_probe(), store)
            self.assertEqual(self.library.power_metric(0), store)
            self.assertEqual(self.library.power_metric(1), 7)
            self.assertEqual(self.library.power_metric(2), 1)

    def test_native_el_cpu_thread_and_cached_return_proof_are_required(self):
        for option, value in ((4, 1), (4, 2), (5, 0)):
            self.setUp(); self.library.power_option(option, value)
            self.run_probe(); self.assertEqual(self.library.power_metric(0), 0)
        self.setUp(); self.library.set_option(4, 0)
        self.run_probe(); self.assertEqual(self.library.metric(0), 0)

    def test_lost_return_thread_args_cpu_table_or_inherited_template_prevents_next_write(self):
        for kind in range(1, 8):
            self.setUp()
            # Ensure the changed template is an inherited enabled command.
            at = 0xd00 + 0x2a0 * 2
            self.put(2, at + 0x1c, 1); self.put(2, at + 0x30, 0x10108)
            self.put(2, at + 0x34, 0x30060); self.put(2, at + 0x38, 6)
            self.library.power_option(9, 2); self.library.power_option(10, kind)
            self.run_probe(); self.assertEqual(self.library.power_metric(0), 2, kind)
        for store in (1, 8, 13, 26, 39, 40, 47, 63):
            self.setUp(); self.library.power_option(8, store)
            self.run_probe(); self.assertEqual(self.library.power_metric(0), store)
            self.assertEqual(self.library.power_metric(2), 1)

    def test_rsc_timeout_incomplete_status_and_failed_clear_are_bounded_and_skip_aop(self):
        for issue in (1, 2, 3, 4):
            self.setUp(); self.library.power_option(6, issue)
            self.assertNotIn('result=0 ', self.run_probe())
            self.assertEqual(self.library.power_metric(8), 0)
            self.assertLessEqual(self.library.power_metric(5), 100000)
            self.assertLessEqual(self.library.power_metric(0), 13)

    def test_aop_timeout_retains_all_votes_and_pending_delivery_without_off_or_retry(self):
        for issue, expected in ((5, 0), (6, 64)):
            self.setUp(); self.library.power_option(6, issue)
            self.assertNotIn('result=0 ', self.run_probe())
            self.assertEqual(self.library.power_metric(1), 7)
            self.assertEqual(self.word(0, 0x128), expected)
            count = self.library.power_metric(0)
            self.library.redfin_wifi_native_observe()
            self.assertEqual(self.library.power_metric(0), count)
            self.assertLessEqual(self.library.power_metric(5), 5000000)

    def test_fully_open_idle_aop_is_adopted_without_control_stores(self):
        for offset in (0xc, 0x10, 0x14, 0x18, 0x24, 0x28, 0x2c, 0x30):
            self.put(0, offset, 0xffff)
        self.assertIn('result=0', self.run_probe())
        self.assertEqual(self.library.power_metric(8), 1)
        self.assertEqual(len(self.trace()), 57)
        self.assertTrue(all(unit != 0 or offset >= 0x128 for unit, offset, _value in self.trace()[39:]))


if __name__ == '__main__':
    unittest.main()
