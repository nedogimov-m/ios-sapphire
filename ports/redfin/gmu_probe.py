"""Translate the native Lito reset-held GMU experiment into its exact ADT.

The optional SMMU leaf permits a separately selected global snapshot;
context=True additionally binds read-only CB0/1 inspection.
No firmware, PDC, GX or SMMU writes are authorized.
All native inputs are checked before appending any new node.
"""
import struct
from ports.redfin import mkadt


REG = (0x100000, 0x1F0000, 0x3D90000, 0x9000,
       0x3D6A000, 0x30000, 0x17A00000, 0x4000)
CLOCK_POLICY = (200000000, 31, 0x4000, 2, 6, 2, 0x71028, 3, 3, 0xf03, 0x103)
TCM_POLICY = (2, 0x10004000, 0x7000, 2, 1, 1000)
CX_PARENT = (0x30000, 64, 65535, 7, 416)
INTERRUPTS = (336, 337)
SMMU_REG = (0x3DA0000, 0x10000)
SMMU_STREAM_MAP = (4, 0x400, 5, 0x400)
SMMU_FORMAT_POLICY = (0x1000, 0x8000, 128, 8, 39, 36)
# unit, byte offset, mask, expected. AHB's native HALT_DELAY is not a HALT proof.
SMMU_CLOCK_POLICY = (0, 0x7100C, 0x80000001, 1,
                     0, 0x71018, 0x80000001, 1,
                     1, 0x1078, 1, 1,
                     1, 0x5000, 0x80000001, 1)
SMMU_INTERRUPTS = (705, *range(710, 718))
CONTEXT_POLICY = (1, 0x8000, 0x4000, 2, 0x1000, 12)


def add_contract(tree, nodes, *, smmu=False, context=False):
    def need(path, key, expected):
        if nodes.get(path, {}).get(key) != expected:
            raise ValueError(f'GMU FDT mismatch: {path} {key}')

    def compatible(path, value):
        if value not in nodes.get(path, {}).get('compatible', b'').split(b'\0'):
            raise ValueError(f'GMU FDT incompatible controller: {path}')

    def phandle(path):
        value = nodes.get(path, {}).get('phandle', b'')
        if len(value) != 4 or not int.from_bytes(value, 'big'):
            raise ValueError(f'GMU FDT missing phandle: {path}')
        if sum(properties.get('phandle') == value for properties in nodes.values()) != 1:
            raise ValueError(f'GMU FDT ambiguous phandle: {path}')
        return value

    if any(child.name == 'redfin-gmu' for child in tree.children):
        raise ValueError('duplicate GMU contract')
    if not isinstance(smmu, bool):
        raise ValueError('GMU SMMU selection must be a boolean')
    if not isinstance(context, bool) or (context and not smmu):
        raise ValueError('GPU context snapshot requires boolean selection and SMMU')
    if smmu and any(child.name == 'redfin-gpu-smmu' for child in tree.children):
        raise ValueError('duplicate GPU SMMU contract')
    parents = [child for child in tree.children if child.name == 'redfin-gpu-power']
    if len(parents) != 1 or parents[0].prop('cx-parent') != mkadt.u32(*CX_PARENT) or \
            parents[0].prop('chip-id') != mkadt.u32(0x06020001):
        raise ValueError('GMU contract requires the matching CX power contract first')

    gcc, gpucc = '/soc/qcom,gcc@100000', '/soc/qcom,gpucc@3d90000'
    gmu, gpu = '/soc/qcom,gmu@3d6a000', '/soc/qcom,kgsl-3d0@3d00000'
    gic, aop = '/soc/interrupt-controller@17a00000', '/soc/qcom,aopclk'
    cx = '/soc/qcom,gdsc@3d9106c'
    compatible(gcc, b'qcom,gcc-lito')
    compatible(gpucc, b'qcom,lito-gpucc')
    compatible(gic, b'arm,gic-v3')
    compatible(aop, b'qcom,aop-qmp-clk')
    need(gcc, 'reg', struct.pack('>II', 0x100000, 0x1F0000))
    need(gpucc, 'reg', struct.pack('>II', 0x3D90000, 0x9000))
    need(gic, 'reg', struct.pack('>4I', 0x17A00000, 0x10000, 0x17A60000, 0x100000))
    need(gmu, 'compatible', b'qcom,gpu-gmu\0')
    need(gmu, 'reg', struct.pack('>6I', 0x3D6A000, 0x30000,
                                0xB290000, 0x10000, 0xB490000, 0x10000))
    need(gmu, 'reg-names', b'kgsl_gmu_reg\0kgsl_gmu_pdc_cfg\0kgsl_gmu_pdc_seq\0')
    need(gmu, 'interrupts', struct.pack('>6I', 0, 304, 4, 0, 305, 4))
    need(gmu, 'interrupt-names', b'kgsl_hfi_irq\0kgsl_gmu_irq\0')
    need(gmu, 'clock-names', b'gmu_clk\0cxo_clk\0axi_clk\0memnoc_clk\0'
                           b'gpu_cc_ahb\0smmu_vote\0apb_pclk\0')
    need(gpu, 'qcom,chipid', struct.pack('>I', 0x06020001))
    need(gpu, 'reg', struct.pack('>8I', 0x3D00000, 0x40000, 0x3D61000, 0x800,
                                0x3DE0000, 0x1000, 0x3D8B000, 0x2000))

    gcc_handle, gpucc_handle, aop_handle = phandle(gcc), phandle(gpucc), phandle(aop)
    clocks = ((gpucc_handle, 3), (gpucc_handle, 6), (gcc_handle, 13),
              (gcc_handle, 35), (gpucc_handle, 0), (gpucc_handle, 12), (aop_handle, 0))
    # The IDs correspond to the pinned Lito clock bindings, not SC7280 IDs.
    need(gmu, 'clocks', b''.join(handle + struct.pack('>I', clock) for handle, clock in clocks))
    need(gmu, 'vddcx-supply', phandle(cx))
    interrupt_parent = nodes[gmu].get('interrupt-parent',
        nodes.get('/soc', {}).get('interrupt-parent', nodes.get('/', {}).get('interrupt-parent')))
    if interrupt_parent != phandle(gic):
        raise ValueError('GMU FDT interrupt parent is not the verified GIC')

    additions = [mkadt.node('redfin-gmu', [
        ('reg', mkadt.u64(*REG)), ('chip-id', mkadt.u32(0x06020001)),
        ('clock-policy', mkadt.u32(*CLOCK_POLICY)),
        ('tcm-policy', mkadt.u32(*TCM_POLICY)),
        ('cx-parent', mkadt.u32(*CX_PARENT)),
        ('gic-intids', mkadt.u32(*INTERRUPTS)),
    ])]
    if smmu:
        modern, legacy = '/soc/kgsl-smmu@3da0000', '/soc/qcom,kgsl-iommu@3da0000'
        need(modern, 'compatible', b'qcom,qsmmu-v500\0')
        need(modern, 'reg', struct.pack('>4I', 0x3DA0000, 0x10000, 0x3DC2000, 0x20))
        need(modern, 'reg-names', b'base\0tcu-base\0')
        need(modern, '#iommu-cells', struct.pack('>I', 2))
        for flag in ('qcom,skip-init', 'qcom,use-3-lvl-tables', 'qcom,no-dynamic-asid'):
            need(modern, flag, b'')
        need(modern, '#global-interrupts', struct.pack('>I', 1))
        need(modern, 'vdd-supply', phandle(cx))
        smmu_clocks = ((gcc_handle, 35), (gcc_handle, 36), (gpucc_handle, 0), (gpucc_handle, 12))
        clock_bytes = b''.join(handle + struct.pack('>I', clock) for handle, clock in smmu_clocks)
        need(modern, 'clocks', clock_bytes)
        need(modern, 'clock-names', b'gcc_gpu_memnoc_gfx\0gcc_gpu_snoc_dvm_gfx\0gpu_cc_ahb\0'
                                  b'gpu_cc_hlos1_vote_gpu_smmu_clk\0')
        need(modern, 'interrupts', b''.join(struct.pack('>3I', 0, irq - 32, 4)
                                           for irq in SMMU_INTERRUPTS))
        smmu_parent = nodes[modern].get('interrupt-parent',
            nodes.get('/soc', {}).get('interrupt-parent', nodes.get('/', {}).get('interrupt-parent')))
        if smmu_parent != phandle(gic):
            raise ValueError('GPU SMMU FDT interrupt parent is not the verified GIC')
        need(legacy, 'compatible', b'qcom,kgsl-smmu-v2\0')
        need(legacy, 'reg', struct.pack('>2I', *SMMU_REG))
        need(legacy, 'qcom,protect', struct.pack('>2I', 0xA0000, 0xC000))
        need(legacy, 'qcom,secure_align_mask', struct.pack('>I', 0xFFF))
        need(legacy, 'qcom,retention', b'')
        need(legacy, 'qcom,hyp_secure_alloc', b'')
        need(legacy, 'clocks', clock_bytes)
        need(legacy, 'clock-names', b'gcc_gpu_memnoc_gfx\0gcc_gpu_snoc_dvm_gfx\0gpu_cc_ahb\0smmu_vote\0')
        smmu_handle = phandle(modern)
        for child, stream, kind in (('gmu_user', 4, b'qcom,smmu-gmu-user-cb\0'),
                                     ('gmu_kernel', 5, b'qcom,smmu-gmu-kernel-cb\0')):
            path = gmu + '/' + child
            need(path, 'compatible', kind)
            need(path, 'iommus', smmu_handle + struct.pack('>2I', stream, 0x400))
            need(path, 'qcom,iommu-dma', b'disabled\0')
        additions.append(mkadt.node('redfin-gpu-smmu', [
            ('reg', mkadt.u64(*SMMU_REG)), ('chip-id', mkadt.u32(0x06020001)),
            ('stream-map', mkadt.u32(*SMMU_STREAM_MAP)),
            ('format-policy', mkadt.u32(*SMMU_FORMAT_POLICY)),
            ('clock-policy', mkadt.u32(*SMMU_CLOCK_POLICY)),
            ('gic-intids', mkadt.u32(*SMMU_INTERRUPTS)),
        ] + ([('context-policy', mkadt.u32(*CONTEXT_POLICY))] if context else [])))
    tree.children.extend(additions)
