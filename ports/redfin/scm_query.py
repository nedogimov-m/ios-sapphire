"""Read-only SCM/PAS capability ABI; no image metadata or DMA contract."""
from ports.redfin import mkadt

TARGETS = (0x02000201, 0x02000202, 0x02000205, 0x02000206, 0x02000207)


def add_contract(tree, nodes):
    compatible = nodes.get('/', {}).get('compatible', b'').split(b'\0')
    if b'google,redfin-sm7250' not in compatible or b'qcom,sm7250' not in compatible:
        raise ValueError('SCM capability query requires the native Redfin FDT')
    if any(child.name == 'redfin-scm-query' for child in tree.children):
        raise ValueError('duplicate SCM query contract')
    tree.children.append(mkadt.node('redfin-scm-query', [
        ('query-only', mkadt.u32(1)), ('pas-ids', mkadt.u32(4, 13)),
        ('functions', mkadt.u32(*TARGETS))]))
