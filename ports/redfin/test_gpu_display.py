"""Decode real emitted PM4 and prove every packed panel row's source/bounds."""
import ctypes as C
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
W, H, PITCH, STAGE_PITCH = 1080, 2340, 4320, 4352
PANEL_SIZE = (PITCH*H + 16383) & ~16383
CONTROL = (STAGE_PITCH*H + 16383) & ~16383
STAGE_SIZE = CONTROL + 16384
WORDS = 2048


class Surface(C.Structure):
    _fields_ = [('address', C.c_uint64), ('length', C.c_uint64),
                ('offset', C.c_uint32), ('width', C.c_uint32), ('height', C.c_uint32), ('pitch', C.c_uint32)]


class Rect(C.Structure):
    _fields_ = [(key, C.c_uint32) for key in ('x', 'y', 'w', 'h')]


class Layer(C.Structure):
    _fields_ = [('surface', Surface), ('source', Rect), ('destination', Rect)]


def decode(words):
    registers, blits, events = {}, [], []
    cursor = 0
    while cursor < len(words):
        header = words[cursor]
        cursor += 1
        kind = header >> 28
        if kind == 4:
            count, reg = header & 127, (header >> 8) & 0x7ffff
            assert count and ((header >> 7) & 1) == 1-(count.bit_count() & 1)
            assert ((header >> 27) & 1) == 1-(reg.bit_count() & 1)
            assert cursor + count <= len(words)
            for i, value in enumerate(words[cursor:cursor+count]):
                registers[reg+i] = value
        elif kind == 7:
            count, op = header & 0x3fff, (header >> 16) & 127
            assert ((header >> 15) & 1) == 1-(count.bit_count() & 1)
            assert ((header >> 23) & 1) == 1-(op.bit_count() & 1)
            assert cursor + count <= len(words)
            values = words[cursor:cursor+count]
            assert op in (0x26, 0x46, 0x2c, 0x65)
            if op == 0x2c:
                assert values == [3]
                blits.append(dict(registers))
            if op == 0x46:
                events.append(values)
        else:
            raise AssertionError(f'unexpected PM4 kind: {kind}')
        cursor += count
    return registers, blits, events


class GPUDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        (root/'display.c').write_text('#include "redfin_gpu_runtime.h"\n#include "redfin_gpu_display.h"\n'
            'unsigned program(uint32_t *o,unsigned n,const struct rf_gd_surface *s,uint64_t p,uint64_t z,'
            'const struct rf_gd_layer *l,unsigned c){return rf_gd_program(o,n,s,p,z,l,c);}\n'
            'unsigned program_direct(uint32_t *o,unsigned n,const struct rf_gd_surface *s,uint64_t p,uint64_t z,'
            'const struct rf_gd_layer *l,unsigned c){return rf_gd_program_direct(o,n,s,p,z,l,c);}\n'
            'int panel_page(uint64_t p){return rf_gd_panel_page(p);}\n')
        subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
            '-I', HERE/'include', root/'display.c', '-o', root/'display.so'], check=True, capture_output=True)
        cls.lib = C.CDLL(str(root/'display.so'))
        cls.lib.program.argtypes = [C.POINTER(C.c_uint32), C.c_uint, C.POINTER(Surface),
            C.c_uint64, C.c_uint64, C.POINTER(Layer), C.c_uint]
        cls.lib.panel_page.argtypes = [C.c_uint64]
        cls.lib.program_direct.argtypes=cls.lib.program.argtypes

    def scene(self, count=1):
        stage = Surface(0x18000000, STAGE_SIZE, 0, W, H, STAGE_PITCH)
        source = Surface(0x14000000, 4608*2436, 0, 1125, 2436, 4608)
        layers = (Layer*count)()
        for i in range(count):
            layers[i] = Layer(source, Rect(0,0,1125,2436), Rect(31,136,1017,2204))
        return stage, layers

    def emit(self, stage, layers, packed=0x1a000000, size=PANEL_SIZE):
        out = (C.c_uint32*WORDS)(*([0xdeadbeef]*WORDS))
        count = self.lib.program(out, WORDS, C.byref(stage), packed, size, layers, len(layers))
        return list(out[:count]), out

    def emit_direct(self,stage,layers,packed=0x1a000000,size=PANEL_SIZE):
        out=(C.c_uint32*WORDS)(*([0xdeadbeef]*WORDS))
        count=self.lib.program_direct(out,WORDS,C.byref(stage),packed,size,layers,len(layers))
        return list(out[:count]),out

    def test_fused_output_covers_every_physical_row_once_without_an_intermediate_image(self):
        for width,height,pitch in ((1080,2340,4352),(1125,2436,4608),(1125,2435,4608),
                                   (80,61,320),(2,2,64),(16384,16384,65536)):
            # Keep the actual128MiB BO limit: a larger declaration must fail.
            with self.subTest(source=(width,height,pitch)):
                stage,layers=self.scene()
                layers[0].surface=Surface(0x24000000,pitch*height,0,width,height,pitch)
                layers[0].source=Rect(0,0,width,height)
                layers[0].destination=Rect(0,0,W,H)
                words,raw=self.emit_direct(stage,layers)
                if pitch*height>128*1024*1024:
                    self.assertFalse(words);self.assertEqual(raw[0],0xdeadbeef);continue
                _,blits,events=decode(words)
                self.assertEqual(len(blits),2)
                rows=[]
                for registers in blits:
                    self.assertFalse(registers[0x8c00]&(1<<7))
                    self.assertTrue(registers[0xb4c0]&(1<<16))
                    self.assertEqual(registers[0xb4c0]&((1<<20)|(1<<22)),(1<<20)|(1<<22))
                    src=registers[0xb4c2]|(registers[0xb4c3]<<32)
                    dst=registers[0x8c18]|(registers[0x8c19]<<32)
                    self.assertEqual(src,layers[0].surface.address)
                    self.assertNotEqual(dst,stage.address)
                    self.assertEqual(registers[0x8c1a]*64,PITCH*2)
                    self.assertEqual(((registers[0xb4c4]>>9)&0x7fff)*64,pitch)
                    dx,dy=registers[0x8405]&65535,registers[0x8405]>>16
                    dw=(registers[0x8406]&65535)-dx+1
                    dh=(registers[0x8406]>>16)-dy+1
                    self.assertEqual((dw,dh),(W,H//2))
                    def signed_fixed(value):
                        self.assertEqual(value&~0x01ffffff,0)
                        return (value-(1<<25) if value&(1<<24) else value)/256
                    sy1=signed_fixed(registers[0x8403]);sy2=signed_fixed(registers[0x8404])
                    for row in range(dh):
                        physical=dst+(dy+row)*PITCH*2+dx*4
                        y=(physical-0x1a000000)//PITCH
                        # Hardware uses pixel-centred source rectangles. The
                        # only permitted difference is rounding its8fraction
                        # bits once, not selecting a different source row.
                        actual=sy1-0.5+(row+0.5)*(sy2-sy1+1)/dh
                        expected=-0.5+(y+0.5)*height/H
                        self.assertLessEqual(abs(actual-expected),1/256+1e-9)
                        rows.append((physical,y,dw*4))
                rows.sort();self.assertEqual(len(rows),H)
                for y,(address,index,length) in enumerate(rows):
                    self.assertEqual((address,index,length),(0x1a000000+y*PITCH,y,PITCH))
                self.assertEqual(rows[-1][0]+rows[-1][2],0x1a000000+PITCH*H)
                # No staged-image source or destination; only the retained
                # native event timestamp touches its separate control page.
                for event in events:
                    if len(event)==4:self.assertEqual(event[1]|(event[2]<<32),stage.address+CONTROL)

    def test_fusion_rejects_partial_cropped_multi_layer_and_invalid_extents_without_emitting(self):
        for mode in ('margin','crop','small-source','extra-layer','alias','short','pitch','overflow'):
            stage,layers=self.scene(2 if mode=='extra-layer' else 1)
            for l in layers:l.destination=Rect(0,0,W,H)
            if mode=='margin':layers[0].destination=Rect(0,0,W,H-1)
            if mode=='crop':layers[0].source=Rect(1,0,1124,2436)
            if mode=='small-source':layers[0].surface.height=layers[0].source.h=1
            if mode=='alias':layers[0].surface=stage;layers[0].source=Rect(0,0,W,H)
            if mode=='short':layers[0].surface.length=64
            if mode=='pitch':layers[0].surface.pitch=4320
            if mode=='overflow':layers[0].surface.address=0xfffffffffffff000
            words,raw=self.emit_direct(stage,layers)
            self.assertFalse(words);self.assertEqual(raw[0],0xdeadbeef)
            if mode in ('margin','crop','small-source','extra-layer'):
                self.assertTrue(self.emit(stage,layers)[0])

    def test_final_owned_display_sources_match_the_actual_ordered_kernel_overlay(self):
        from test_smp_gui import patched_source
        for target, owned in (
            ('iokit/Kernel/arm/RedfinGPUDisplay.inc', 'gpu-display.inc'),
            ('iokit/Kernel/arm/redfin_gpu_display.h', 'include/redfin_gpu_display.h'),
            ('bsd/dev/redfin_gpu_display.h', 'include/redfin_gpu_display.h')):
            self.assertEqual(patched_source(target), (HERE/owned).read_text())

    def test_decoded_gpu_pack_covers_every_panel_row_exactly_without_cpu_copy(self):
        stage, layers = self.scene()
        words, _ = self.emit(stage, layers)
        _, blits, events = decode(words)
        self.assertEqual(len(blits), 6)  # three margins, scaled layer, even, odd
        for clear in blits[:3]:
            self.assertTrue(clear[0x8c00] & (1 << 7))
            self.assertEqual(clear[0x8c2f], 255)
        rows = []
        for registers in blits[-2:]:
            src = registers[0xb4c2] | (registers[0xb4c3] << 32)
            dst = registers[0x8c18] | (registers[0x8c19] << 32)
            sp = ((registers[0xb4c4] >> 9) & 0x7fff) * 64
            dp = registers[0x8c1a] * 64
            sx, sy = registers[0x8401] >> 8, registers[0x8403] >> 8
            dx, dy = registers[0x8405] & 65535, registers[0x8405] >> 16
            dw = (registers[0x8406] & 65535) - dx + 1
            dh = (registers[0x8406] >> 16) - dy + 1
            self.assertEqual((dst & 63, dw, dh), (0, W, H//2))
            self.assertFalse(registers[0xb4c0] & (1 << 16))  # packing does not resample
            for row in range(dh):
                rows.append((dst + (dy+row)*dp + dx*4, src + (sy+row)*sp + sx*4, dw*4))
        rows.sort()
        self.assertEqual(len(rows), H)
        for y, (dst, src, length) in enumerate(rows):
            self.assertEqual((dst, src, length), (0x1a000000+y*PITCH, stage.address+y*STAGE_PITCH, PITCH))
        self.assertEqual(rows[-1][0] + rows[-1][2], 0x1a000000 + PITCH*H)
        for event in events:
            if len(event) == 4:
                self.assertIn(event[0] & 255, (28,29))
                self.assertEqual(event[1] | (event[2] << 32), stage.address + CONTROL)

    def test_scaler_uses_the_existing_complete_canvas_and_cutout_viewport(self):
        stage, layers = self.scene(4)
        words, _ = self.emit(stage, layers)
        _, blits, _ = decode(words)
        self.assertEqual(len(blits), 9)
        for registers in blits[3:7]:
            self.assertEqual([registers[n] >> 8 for n in range(0x8401,0x8405)], [0,1124,0,2435])
            self.assertEqual(registers[0x8405], 31 | (136 << 16))
            self.assertEqual(registers[0x8406], 1047 | (2339 << 16))
            self.assertTrue(registers[0xb4c0] & (1 << 16))
        regs, _, _ = decode(words)
        allowed = {0x8e07,0x8e04,0x8c00,0x8400,0xacc0,0x8c01}
        for start, end in ((0x8401,0x8406),(0xb4c0,0xb4c4),(0x8c17,0x8c1a),(0x8c2c,0x8c2f)):
            allowed.update(range(start,end+1))
        self.assertFalse(set(regs)-allowed)

    def test_actual_clears_and_first_overwrite_tile_the_panel_without_overlap_or_old_pixels(self):
        # Decode the emitted operations rather than calling the clear planner.
        # Every cell cut by their rectangle edges must be written exactly once
        # by the first overwrite or an opaque black clear, including corners.
        cases = ((0,0,W,H), (5,6,1070,2328), (31,136,1017,2204),
                 (0,0,1,1), (W-1,H-1,1,1), (7,9,1,1),
                 (0,13,W,17), (17,0,31,H), (0,0,W-1,H-1))
        for cover in cases:
            with self.subTest(cover=cover):
                stage, layers = self.scene(2)
                layers[0].destination = Rect(*cover)
                layers[1].destination = Rect(17,23,41,53)
                words, _ = self.emit(stage, layers)
                _, blits, _ = decode(words)
                clears = [r for r in blits if r[0x8c00] & (1 << 7)]
                draws = [r for r in blits[:-2] if not r[0x8c00] & (1 << 7)]
                self.assertEqual(len(draws), 2)
                if cover == (0,0,W,H):
                    self.assertEqual(len(blits), 4)  # two layers and two packs
                    self.assertFalse(clears)
                rects = [cover]
                for r in clears:
                    self.assertEqual([r[n] for n in range(0x8c2c,0x8c30)], [0,0,0,255])
                    x,y = r[0x8405] & 65535,r[0x8405] >> 16
                    right,bottom = (r[0x8406] & 65535)+1,(r[0x8406] >> 16)+1
                    self.assertTrue(0 <= x < right <= W and 0 <= y < bottom <= H)
                    rects.append((x,y,right-x,bottom-y))
                self.assertEqual(sum(w*h for _,_,w,h in rects), W*H)
                xs = sorted({0,W,*(v for x,_,w,_ in rects for v in (x,x+w))})
                ys = sorted({0,H,*(v for _,y,_,h in rects for v in (y,y+h))})
                for x in xs[:-1]:
                    for y in ys[:-1]:
                        self.assertEqual(sum(a <= x < a+w and b <= y < b+h
                                             for a,b,w,h in rects), 1)

    def test_fullscreen_first_layer_does_not_hide_invalid_later_layers(self):
        for invalid in ('source', 'destination', 'alias'):
            stage, layers = self.scene(4)
            layers[0].destination = Rect(0,0,W,H)
            if invalid == 'source':
                layers[3].source = Rect(1124,0,2,1)
            elif invalid == 'destination':
                layers[3].destination = Rect(W-1,H-1,2,1)
            else:
                layers[3].surface = stage
            words, raw = self.emit(stage,layers)
            self.assertFalse(words)
            self.assertEqual(raw[0], 0xdeadbeef)

    def test_invalid_bos_rectangles_and_aliases_emit_nothing(self):
        for field, value in (('pitch',4320),('offset',4),('width',16385),
                             ('length',1),('address',0xfffffffffffff000)):
            stage, layers = self.scene()
            setattr(layers[0].surface, field, value)
            words, raw = self.emit(stage,layers)
            self.assertFalse(words)
            self.assertEqual(raw[0],0xdeadbeef)
        for rect in (Rect(0,0,0,1),Rect(1124,0,2,1),Rect(0,2436,1,1)):
            stage,layers=self.scene();layers[0].source=rect
            self.assertFalse(self.emit(stage,layers)[0])
        stage,layers=self.scene()
        for packed, size in ((stage.address,STAGE_SIZE),(0x1a000020,PANEL_SIZE),
                             (0x1a000000,PANEL_SIZE-1)):
            self.assertFalse(self.emit(stage,layers,packed,size)[0])

    def test_only_exact_reserved_panel_pages_are_eligible_for_the_internal_mapper(self):
        self.assertEqual(self.lib.panel_page(0xa0000000),1)
        self.assertEqual(self.lib.panel_page(0xa0000000+PANEL_SIZE-4096),1)
        for address in (0x9ffff000,0xa0000001,0xa0000000+PANEL_SIZE,0x180000000,0xfffffffffffff000):
            self.assertEqual(self.lib.panel_page(address),0)


if __name__ == '__main__':
    unittest.main()
