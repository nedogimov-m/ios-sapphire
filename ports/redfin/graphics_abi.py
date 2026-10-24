"""Bounded readers for the *installed* arm64 iOS graphics ABI.

Generated headers, Apple code and cache contents belong in the ignored build
directory. Nothing here changes the cache, a root image or the phone. In
20H392 the public GL stubs index a native context, while getMacroContextPrivate
returns native+32. Confusing those two bases shifts every QuartzCore call.
"""
import hashlib
import mmap
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = ROOT / ('research/ipsw-redfin/extracted/mounts/systemos/'
    'System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64')
OPEN_GLES = '/System/Library/Frameworks/OpenGLES.framework/OpenGLES'
EAGL_METHODS = (
    '-initWithAPI:properties:', '-commonInitWithAPI:properties:', '-API',
    '-sharegroup', '-setParameter:to:', '-getMacroContextPrivate',
    '-texImageIOSurface:target:internalFormat:width:height:format:type:plane:invert:',
    '-attachImage:toCoreSurface:invertedRender:', '-dealloc',
    '+setCurrentContext:', '+currentContext',
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def uleb(data, at):
    value = 0
    for shift in range(0, 70, 7):
        require(0 <= at < len(data), 'truncated export trie integer')
        byte = data[at]; at += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, at
    raise ValueError('oversized export trie integer')


def commands(read, base):
    header = read(base, 32)
    require(struct.unpack_from('<II', header) == (0xfeedfacf, 0x100000c),
            'graphics requires a plain arm64 Mach-O')
    count, size = struct.unpack_from('<II', header, 16)
    require(0 < count < 4096 and 0 < size <= 1024 * 1024, 'unbounded Mach-O load commands')
    data = read(base + 32, size)
    result = []; at = 0
    for _ in range(count):
        require(at + 8 <= size, 'truncated Mach-O load command')
        kind, length = struct.unpack_from('<II', data, at)
        require(length >= 8 and not length % 4 and at + length <= size, 'bad load command size')
        result.append((kind, data[at:at + length])); at += length
    require(at == size, 'trailing Mach-O load command bytes')
    return result


def dylib_name(command):
    at = struct.unpack_from('<I', command, 8)[0]
    require(24 <= at < len(command), 'invalid dylib name offset')
    return command[at:].split(b'\0', 1)[0].decode('utf-8')


class Cache:
    def __init__(self, path=DEFAULT_CACHE):
        self.path = Path(path).resolve()
        self.files = []; self.maps = []; self.images = {}
        try:
            for path in sorted(self.path.parent.glob(self.path.name + '*')):
                if path.name.endswith('.symbols') or not path.is_file():
                    continue
                stream = path.open('rb')
                header = stream.read(512)
                if not header.startswith(b'dyld_v1') or b'arm64e' in header[:16]:
                    stream.close(); continue
                mapping, count = struct.unpack_from('<II', header, 16)
                require(0 < count <= 64, 'unbounded dyld cache mappings')
                stream.seek(mapping); raw = stream.read(32 * count)
                require(len(raw) == count * 32, 'short dyld mapping table')
                data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
                self.files.append((stream, data))
                for index in range(count):
                    address, size, offset, _, _ = struct.unpack_from('<QQQII', raw, index * 32)
                    require(0 < size and offset + size <= len(data) and address + size < 1 << 36,
                            'unexpected 20H392 arm64 cache mapping')
                    self.maps.append((address, size, offset, data))
                if path == self.path:
                    self.main = data
            require(bool(self.maps) and hasattr(self, 'main'), 'main arm64 dyld cache absent')
            offset, count = struct.unpack_from('<II', self.main, 448)
            require(0 < count < 20000 and offset + count * 32 <= len(self.main), 'bad image table')
            for index in range(count):
                address, _, _, name, _ = struct.unpack_from('<QQQII', self.main, offset + index * 32)
                require(name < len(self.main), 'bad cache image name')
                end = self.main.find(b'\0', name, min(name + 4096, len(self.main)))
                require(end > name, 'unbounded image name')
                self.images[self.main[name:end].decode()] = address
            self.uuid = self.main[88:104].hex()
        except BaseException:
            self.close()
            raise

    def close(self):
        for stream, data in self.files:
            data.close(); stream.close()
        self.files.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def read(self, address, size):
        require(0 <= size <= 64 * 1024 * 1024, 'unbounded shared cache read')
        for base, length, offset, data in self.maps:
            if base <= address and size <= base + length - address:
                at = offset + address - base
                return data[at:at + size]
        raise ValueError(f'unmapped shared cache address {address:#x}+{size:#x}')

    def pointer(self, address):
        # The upper bits in this arm64 cache contain v2 slide-chain deltas.
        # All accepted mappings were bounded below 2**36 above.
        return struct.unpack('<Q', self.read(address, 8))[0] & 0xfffffffff

    def string(self, address):
        data = self.read(address, 4096)
        end = data.find(b'\0')
        require(end >= 0, 'unbounded cache string')
        return data[:end].decode()

    def image(self, path):
        require(path in self.images, 'library absent from actual iOS cache: ' + path)
        return Image(self, path, self.images[path])

    def local_symbols(self, image, wanted):
        """Read only this image's nlists from the paired .symbols subcache."""
        path = self.path.with_name(self.path.name + '.symbols')
        with path.open('rb') as stream:
            header = stream.read(512)
            require(header[88:104] == self.main[400:416], 'unpaired dyld local-symbols UUID')
            offset, size = struct.unpack_from('<QQ', header, 72)
            stream.seek(offset)
            nlists, count, strings, string_size, entries, entry_count = struct.unpack('<6I', stream.read(24))
            require(0 < entry_count < 20000 and 0 < count < 20000000, 'unbounded local symbols')
            require(offset + size <= path.stat().st_size and nlists + count * 16 <= size and
                    strings + string_size <= size and entries + entry_count * 16 <= size,
                    'truncated local symbols')
            stream.seek(offset + entries); records = stream.read(16 * entry_count)
            cache_base = struct.unpack_from('<Q', self.main, 224)[0]
            matches = [(start, length) for dylib, start, length in struct.iter_unpack('<QII', records)
                       if dylib == image.base - cache_base]
            require(len(matches) == 1, 'local-symbol image is ambiguous')
            start, length = matches[0]
            require(start + length <= count, 'local-symbol image range is invalid')
            result = {}
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for index in range(start, start + length):
                    name, kind, _, _, address = struct.unpack_from('<IBBHQ', data, offset + nlists + index * 16)
                    if not name or kind & 0xe0:
                        continue
                    require(name < string_size, 'invalid local-symbol string index')
                    at = offset + strings + name
                    end = data.find(b'\0', at, min(at + 8192, offset + strings + string_size))
                    require(end >= at, 'unbounded local-symbol name')
                    name = data[at:end].decode()
                    if name in wanted:
                        require(name not in result, 'duplicate requested local symbol')
                        result[name] = address
            require(set(result) == set(wanted), 'missing requested actual-cache local symbol')
            return result


class Image:
    def __init__(self, cache, path, base):
        self.cache, self.path, self.base = cache, path, base
        self.commands = commands(cache.read, base)
        self.uuid = next(raw[8:24].hex() for kind, raw in self.commands if kind == 27)
        self.sections = {}
        for kind, raw in self.commands:
            if kind == 25:
                count = struct.unpack_from('<I', raw, 64)[0]
                require(72 + count * 80 == len(raw), 'invalid segment section list')
                for index in range(count):
                    section = raw[72 + index * 80:152 + index * 80]
                    name = section[:16].rstrip(b'\0').decode()
                    self.sections[name] = struct.unpack_from('<QQ', section, 32)

    def exports(self):
        link = next(raw for kind, raw in self.commands if kind == 25 and
                    raw[8:24].rstrip(b'\0') == b'__LINKEDIT')
        vm, _, file_offset, _ = struct.unpack_from('<QQQQ', link, 24)
        command = next((raw for kind, raw in self.commands if kind == 0x80000033), None)
        if command is not None:
            offset, size = struct.unpack_from('<II', command, 8)
        else:
            command = next((raw for kind, raw in self.commands if kind in (0x22, 0x80000022)), None)
            if command is None:
                return {}, []
            offset, size = struct.unpack_from('<II', command, 40)
        require(0 <= size <= 32 * 1024 * 1024, 'unbounded export trie')
        if size == 0:
            return {}, [dylib_name(raw) for kind, raw in self.commands if kind == 0x8000001f]
        trie = self.cache.read(vm + offset - file_offset, size)
        libraries = [dylib_name(raw) for kind, raw in self.commands
                     if kind in (0xc, 0x80000018, 0x8000001f, 0x80000023)]
        forwarded = {dylib_name(raw) for kind, raw in self.commands if kind == 0x8000001f}
        exports = {}; visited = set()

        def walk(at, name, depth=0):
            require(depth < 256 and at not in visited, 'cyclic/unbounded export trie')
            visited.add(at)
            terminal, pos = uleb(trie, at); end = pos + terminal
            require(end < len(trie), 'truncated export trie terminal')
            if terminal:
                flags, value_at = uleb(trie, pos)
                value, _ = uleb(trie, value_at)
                if flags & 8:
                    require(0 < value <= len(libraries), 'bad export reexport ordinal')
                    forwarded.add(libraries[value - 1]); exports[name] = None
                else:
                    exports[name] = self.base + value
            children = trie[end]; pos = end + 1
            for _ in range(children):
                nul = trie.find(b'\0', pos)
                require(pos <= nul < len(trie), 'truncated export trie name')
                suffix = trie[pos:nul].decode(); child, pos = uleb(trie, nul + 1)
                walk(child, name + suffix, depth + 1)
            visited.remove(at)

        walk(0, '')
        return exports, sorted(forwarded)

    def objc_methods(self, class_name):
        objc = self.cache.image('/usr/lib/libobjc.A.dylib')
        opt, size = objc.sections['__objc_opt_ro']
        version, _ = struct.unpack('<II', self.cache.read(opt, 8))
        require(version == 16 and size >= 48, 'unreviewed ObjC cache optimization version')
        selector_base = opt + struct.unpack('<q', self.cache.read(opt + 40, 8))[0]
        address, size = self.sections['__objc_classlist']
        require(not size % 8 and size <= 1024 * 1024, 'unbounded ObjC class list')
        for at in range(address, address + size, 8):
            obj = self.cache.pointer(at)
            ro = self.cache.pointer(obj + 32) & ~7
            if self.cache.string(self.cache.pointer(ro + 24)) != class_name:
                continue
            methods = {}
            for meta in (False, True):
                cls = self.cache.pointer(obj) if meta else obj
                ro = self.cache.pointer(cls + 32) & ~7
                method_list = self.cache.pointer(ro + 32)
                if not method_list:
                    continue
                flags, count = struct.unpack('<II', self.cache.read(method_list, 8))
                stride = flags & 0xfffc
                require(stride in (12, 24) and count < 4096, 'bad ObjC method list')
                for index in range(count):
                    entry = method_list + 8 + index * stride
                    if flags & 0x80000000:
                        require(stride == 12 and not flags & 0x20000000, 'unknown relative method layout')
                        name, types, imp = struct.unpack('<iii', self.cache.read(entry, 12))
                        name = selector_base + name if flags & 0x40000000 else self.cache.pointer(entry + name)
                        types += entry + 4; imp += entry + 8
                    else:
                        require(stride == 24, 'unknown absolute method layout')
                        name, types, imp = (self.cache.pointer(entry + 8 * i) for i in range(3))
                    key = ('+' if meta else '-') + self.cache.string(name)
                    require(key not in methods, 'duplicate ObjC method')
                    methods[key] = dict(types=self.cache.string(types), rva=imp - self.base)
            return methods
        raise ValueError('actual cache lacks ObjC class ' + class_name)


def decode_gl_wrapper(code):
    """Decode the actual plain A64 TLS -> table -> context/function -> BR ABI."""
    require(0 < len(code) <= 512 and not len(code) % 4, 'unbounded GL wrapper')
    tls_register = table_register = tls_offset = None
    loads = []; context = None
    for word, in struct.iter_unpack('<I', code):
        if word & ~31 == 0xd53bd060:  # mrs xN, TPIDRRO_EL0
            tls_register = word & 31
        elif word & 0xffc00000 == 0xf9400000:  # ldr xT,[xN,#uimm12*8]
            base, target, offset = (word >> 5) & 31, word & 31, ((word >> 10) & 4095) * 8
            if table_register is None and base == tls_register:
                table_register, tls_offset = target, offset
            elif base == table_register:
                loads.append((target, offset))
        elif word & 0xfffffc1f in (0xd61f0000, 0xd63f0000):  # br/blr xN
            target = (word >> 5) & 31
            slots = [offset for register, offset in loads if register == target]
            contexts = [offset for register, offset in loads if register != target]
            require(len(slots) == len(contexts) == 1 and tls_offset is not None,
                    'unreviewed GL function/context dispatch')
            context = contexts[0]
            return dict(native_slot=slots[0], context_offset=context, tls_offset=tls_offset)
        elif word & 0xfffffc1f == 0xd65f0000:
            break
    raise ValueError('GL export has no reviewed TLS table branch')


def derive_eagl(cache):
    image = cache.image(OPEN_GLES)
    methods = image.objc_methods('EAGLContext')
    require(all(name in methods for name in EAGL_METHODS), 'missing EAGL bridge method')
    getter = image.base + methods['-getMacroContextPrivate']['rva']
    first, add, ret = struct.unpack('<3I', cache.read(getter, 12))
    require(first == 0xf9400408 and add & 0xffc003ff == 0x91000100 and ret == 0xd65f03c0,
            'unreviewed native getMacroContextPrivate getter')
    bias = (add >> 10) & 4095
    require(bias == 32, 'unreviewed EAGLMacroContext native prefix')
    symbols, _ = image.exports()
    wrappers = {}; groups = {}; layouts = set()
    for symbol, address in sorted(symbols.items()):
        if not symbol.startswith('_gl'):
            continue
        require(address is not None, 'forwarded public GL stub')
        code = cache.read(address, 512)
        dispatch = decode_gl_wrapper(code)
        require(dispatch['context_offset'] == bias and dispatch['native_slot'] > bias,
                'GL stub and macro context bases differ')
        name = symbol[1:]; slot = dispatch['native_slot'] - bias
        require(not slot % 8 and 8 <= slot < 0x2100, 'unbounded EAGL function table')
        wrappers[name] = dict(rva=address - image.base, slot=slot, **dispatch)
        groups.setdefault(slot, []).append(name)
        layouts.add((dispatch['context_offset'], dispatch['tls_offset']))
    require(len(wrappers) == 457 and len(layouts) == 1, 'unreviewed complete OpenGLES export set')
    context_offset, tls_offset = layouts.pop()
    require(tls_offset == 240, 'unreviewed OpenGLES TLS slot')
    return dict(system='iOS16.7.16/20H392', path=OPEN_GLES, uuid=image.uuid,
        cache_uuid=cache.uuid, macro_bias=bias, context_offset=context_offset,
        tls_offset=tls_offset, methods={name: methods[name] for name in EAGL_METHODS},
        wrappers=wrappers, groups=groups)


def derive_ca(cache):
    """Bind the upstream function-uniform observer to 20H392, without code patches."""
    image = cache.image('/System/Library/Frameworks/QuartzCore.framework/QuartzCore')
    names = ('__ZTVN2CA3OGL11GLESContextE', '__ZNK2CA3OGL9GLContext18function_supportedEv',
             '__ZN2CA3OGL9GLContext16function_uniformEjmmPKf')
    symbols = cache.local_symbols(image, names)
    vtable, supported, uniform = (symbols[name] for name in names)
    load, byte, compare = struct.unpack('<3I', cache.read(supported, 12))
    require(load & 0xffc003ff == 0xf9400008 and byte & 0xffc003ff == 0x39400109 and
            compare == 0x7101653f, 'unreviewed CoreAnimation function-state layout')
    state_offset, function_offset = ((load >> 10) & 4095) * 8, (byte >> 10) & 4095
    require(state_offset == function_offset == 16, 'unreviewed CA function field offsets')
    entries = [cache.pointer(vtable + offset) for offset in range(16, 0x500, 8)]
    require(entries.count(supported) == entries.count(uniform) == 1, 'ambiguous GLES vtable entries')
    return dict(path=image.path, uuid=image.uuid, state_offset=state_offset, function_offset=function_offset,
        supported_rva=supported-image.base, uniform_rva=uniform-image.base,
        supported_slot_rva=vtable+16+entries.index(supported)*8-image.base,
        uniform_slot_rva=vtable+16+entries.index(uniform)*8-image.base)


def audit_bundle(cache, paths):
    """Resolve all nonweak imports through the actual cache's reexports."""
    local = set(); imports = {}; direct = {}
    for path in paths:
        path = Path(path); data = path.read_bytes()
        cmds = commands(lambda at, size: data[at:at + size], 0)
        symtab = next(raw for kind, raw in cmds if kind == 2)
        offset, count, strings, string_size = struct.unpack_from('<4I', symtab, 8)
        require(offset + count * 16 <= len(data) and strings + string_size <= len(data), 'bad local symbol table')
        required = set()
        for index in range(count):
            name, kind, _, desc, _ = struct.unpack_from('<IBBHQ', data, offset + index * 16)
            if not name or kind & 0xe0 or not kind & 1:
                continue
            require(name < string_size, 'bad local symbol name')
            symbol = data[strings + name:strings + string_size].split(b'\0', 1)[0].decode()
            if kind & 0xe:
                local.add(symbol)
            elif not desc & 0x40:
                required.add(symbol)
        imports[str(path)] = required
        direct[str(path)] = [dylib_name(raw) for kind, raw in cmds
                            if kind in (0xc, 0x80000018, 0x8000001f, 0x80000023)]
    pending = {name for names in direct.values() for name in names if not name.startswith('/redfin/')}
    available = set(); visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        exports, forwarded = cache.image(name).exports()
        visited.add(name); available.update(exports); pending.update(forwarded)
    missing = {name: sorted(required - available - local) for name, required in imports.items()}
    return dict(compatible=not any(missing.values()), actual_system='iOS16.7.16/20H392',
        libraries_checked=len(visited), direct_dependencies=direct, missing_nonweak_symbols=missing)
