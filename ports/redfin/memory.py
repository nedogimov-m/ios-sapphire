"""Validate an explicit Redfin RAM window against a captured bootloader FDT."""
import argparse
from pathlib import Path
import struct
import sys

LIMIT = 1 << 64


def _interval(base, size):
    if size <= 0 or base < 0 or base + size > LIMIT:
        raise ValueError("empty or overflowing address interval")
    return base, size


def _tree(blob):
    if not isinstance(blob, bytes) or not 40 <= len(blob) <= 16 * 1024 * 1024:
        raise ValueError("FDT must be bytes, between 40 bytes and 16 MiB")
    magic, total, start, strings, reserve, ver, compat, _, ns, nt = struct.unpack_from(">10I", blob)
    if magic != 0xD00DFEED or ver < 17 or compat > 17 or compat > ver:
        raise ValueError("unsupported FDT header")
    if total > len(blob) or total < 40 or start % 4 or reserve % 8:
        raise ValueError("invalid FDT bounds/alignment")
    blocks = [(start, start + nt), (strings, strings + ns)]
    if any(a < 40 or b > total or a >= b for a, b in blocks) or reserve < 40:
        raise ValueError("invalid FDT block")
    fixed, pos = [], reserve
    while True:
        if pos + 16 > total:
            raise ValueError("unterminated FDT reservation map")
        base, size = struct.unpack_from(">QQ", blob, pos)
        pos += 16
        if base == size == 0:
            break
        fixed.append(_interval(base, size))
    blocks.append((reserve, pos))
    if any(a < d and c < b for i, (a, b) in enumerate(blocks) for c, d in blocks[i + 1:]):
        raise ValueError("overlapping FDT blocks")

    def name_at(pos, end):
        stop = blob.find(b"\0", pos, end)
        if stop < 0:
            raise ValueError("unterminated FDT name")
        try:
            return blob[pos:stop].decode("ascii"), stop + 1
        except UnicodeDecodeError as error:
            raise ValueError("non-ASCII FDT name") from error

    nodes, stack, cursor, end = {}, [], start, start + nt
    while cursor + 4 <= end:
        token = struct.unpack_from(">I", blob, cursor)[0]
        cursor += 4
        if token == 1:
            name, cursor = name_at(cursor, end)
            cursor = (cursor + 3) & ~3
            if "/" in name or (not stack and (name or nodes)) or len(stack) >= 64:
                raise ValueError("invalid FDT node/nesting")
            stack.append(name)
            path = "/".join(stack) or "/"
            if path in nodes:
                raise ValueError("duplicate FDT node")
            nodes[path] = {}
        elif token == 2:
            if not stack:
                raise ValueError("unbalanced FDT end-node")
            stack.pop()
        elif token == 3:
            if not stack or cursor + 8 > end:
                raise ValueError("invalid FDT property header")
            size, offset = struct.unpack_from(">II", blob, cursor)
            cursor += 8
            if offset >= ns or cursor + size > end:
                raise ValueError("FDT property outside block")
            name, _ = name_at(strings + offset, strings + ns)
            props = nodes["/".join(stack) or "/"]
            if not name or name in props:
                raise ValueError("empty/duplicate FDT property")
            props[name] = blob[cursor:cursor + size]
            cursor = (cursor + size + 3) & ~3
        elif token == 9:
            if stack or not nodes or any(blob[cursor:end]):
                raise ValueError("unbalanced FDT or data after END")
            return nodes, fixed
        elif token != 4:
            raise ValueError("unknown FDT token")
    raise ValueError("missing FDT END")


def memory_map(blob):
    """Return banks, all fixed reservations and unallocated dynamic pool rules."""
    nodes, fixed = _tree(blob)
    root = nodes["/"]
    compatibles = root.get("compatible", b"")
    if not compatibles.endswith(b"\0") or not {b"google,redfin", b"google,redfin-sm7250"}.intersection(compatibles.split(b"\0")):
        raise ValueError("FDT is not compatible with Google Redfin")
    reserved = nodes.get("/reserved-memory")
    if reserved is None or reserved.get("ranges") != b"":
        raise ValueError("reserved-memory requires empty ranges")
    for props in (root, reserved):
        if any(props.get(key) != struct.pack(">I", 2) for key in ("#address-cells", "#size-cells")):
            raise ValueError("Redfin root/reserved-memory must use 2/2 cells")

    def regions(data):
        if not data or len(data) % 16:
            raise ValueError("invalid or empty reg/alloc-ranges")
        return [_interval(*pair) for pair in struct.iter_unpack(">QQ", data)]

    banks, dynamic = [], []
    for path, props in nodes.items():
        if path.count("/") == 1 and (props.get("device_type") == b"memory\0" or path.split("@", 1)[0] == "/memory"):
            banks.extend(regions(props.get("reg", b"")))
        if path.startswith("/reserved-memory/"):
            if path.count("/") != 2:
                raise ValueError("unsupported nested reserved-memory node")
            if "reg" in props:
                fixed.extend(regions(props["reg"]))
            else:
                size = props.get("size", b"")
                if len(size) != 8 or not int.from_bytes(size, "big"):
                    raise ValueError("reserved node has no valid reg or dynamic size")
                ranges = regions(props["alloc-ranges"]) if "alloc-ranges" in props else None
                dynamic.append({"name": path.rsplit("/", 1)[-1], "size": int.from_bytes(size, "big"), "alloc_ranges": ranges})
    banks.sort()
    if not banks or any(a + size > b for (a, size), (b, _) in zip(banks, banks[1:])):
        raise ValueError("missing or overlapping RAM banks")
    return {"banks": banks, "reserved": fixed, "dynamic_pools": dynamic}


def validate_window(blob, base, size):
    """Return True or raise ValueError; no defaults or automatic RAM selection."""
    if type(base) is not int or type(size) is not int:
        raise ValueError("base and size must be integers")
    _interval(base, size)
    if base % 0x4000 or size % 0x4000:
        raise ValueError("RAM window must be 16 KiB aligned")
    layout = memory_map(blob)
    if not any(a <= base and base + size <= a + n for a, n in layout["banks"]):
        raise ValueError("RAM window must fit within one live RAM bank")
    if any(base < a + n and a < base + size for a, n in layout["reserved"]):
        raise ValueError("RAM window overlaps a fixed reservation")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--base", type=lambda x: int(x, 0), required=True)
    parser.add_argument("--size", type=lambda x: int(x, 0), required=True)
    args = parser.parse_args()
    try:
        blob = args.dtb.read_bytes()
        validate_window(blob, args.base, args.size)
        pools = memory_map(blob)["dynamic_pools"]
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"accepted base={args.base:#x} size={args.size:#x}")
    print(f"dynamic pools: {len(pools)} Linux allocation rules, not fixed reservations", file=sys.stderr)
    for pool in pools:
        ranges = pool["alloc_ranges"]
        detail = "unspecified" if ranges is None else ", ".join(f"{a:#x}+{n:#x}" for a, n in ranges)
        print(f"  {pool['name']}: size={pool['size']:#x}, alloc-ranges={detail}", file=sys.stderr)


if __name__ == "__main__":
    main()
