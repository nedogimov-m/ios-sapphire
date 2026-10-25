"""Bind native Redfin power resources before publishing the opt-in ADT leaf."""
import hashlib
import json
from pathlib import Path
import struct
from ports.redfin.memory import _tree

PROPERTY='redfin-platform-power'
# ABI, SID, QG, SDAM, ADC5, CHGR, DCDC, BATIF, USBIN, DCIN, TYPEC,
# SROT/TM pairs, three standard (not EPSS) cpufreq-hw domains.
VALUES=(1,2,0x4800,0xb100,0x3100,0x1000,0x1100,0x1200,0x1300,0x1400,0x1500,
        0x0c222000,0x0c263000,0x0c223000,0x0c265000,
        0x18323000,0x18325800,0x18327800)


def validate(blob):
    nodes,_=_tree(blob)
    def need(ok,message):
        if not ok:raise ValueError('native Redfin power contract: '+message)
    def node(path,compatible=None,reg=None):
        value=nodes.get(path,{})
        need(value.get('status',b'okay\0') in (b'okay\0',b'ok\0'),'disabled or absent '+path)
        if compatible is not None:need(value.get('compatible')==compatible+b'\0','compatible '+path)
        if reg is not None:need(value.get('reg')==struct.pack('>'+len(reg)*'I',*reg),'registers '+path)
        return value
    pmic='/soc/qcom,spmi@c440000/qcom,pm7250b@2'
    qg=node(pmic+'/qpnp,qg',b'qcom,qpnp-qg')
    node(pmic+'/qpnp,qg/qcom,qgauge@4800',reg=(0x4800,0x100))
    node(pmic+'/qpnp,qg/qcom,qg-sdam@b100',reg=(0xb100,0x100))
    adc=node(pmic+'/vadc@3100',b'qcom,spmi-adc5',(0x3100,0x100))
    need(qg.get('io-channels')==adc.get('phandle',b'')+struct.pack('>I',0x4a)+
         adc.get('phandle',b'')+struct.pack('>I',0x4b),'native battery thermistor/provider')
    smb=pmic+'/qcom,qpnp-smb5';node(smb,b'qcom,qpnp-smb5')
    for name,base in [('chgr',0x1000),('dcdc',0x1100),('batif',0x1200),('usb',0x1300),('dc',0x1400),('typec',0x1500)]:
        node(smb+'/qcom,'+name+'@'+format(base,'x'),reg=(base,0x100))
    for base,tm in [(0x0c222000,0x0c263000),(0x0c223000,0x0c265000)]:
        node('/soc/tsens@'+format(base,'x'),b'qcom,tsens26xx',(base,8,tm,0x1ff))
    frequency=node('/soc/qcom,cpufreq-hw',b'qcom,cpufreq-hw',
         (0x18323000,0x1000,0x18325800,0x1000,0x18327800,0x1000))
    need(frequency.get('#freq-domain-cells')==struct.pack('>I',2),'native frequency domain ABI')
    for cpu in range(8):
        info=node('/cpus/cpu@'+format(cpu<<8,'x'))
        domain=0 if cpu<6 else cpu-5;maximum=6 if cpu<6 else 2
        need(info.get('qcom,freq-domain')==frequency.get('phandle',b'')+struct.pack('>II',domain,maximum),
             'native LUT max_cores differs from domain membership')
    node('/soc/qcom,spmi@c440000/qcom,pm8150@0/qcom,pm8150_rtc',b'qcom,pm8941-rtc')
    battery=node('/soc/google,battery',b'google,battery')
    need(battery.get('google,chg-battery-capacity')==struct.pack('>I',4000),'native nominal capacity')
    return dict(version=1,live_fdt_sha256=hashlib.sha256(blob).hexdigest(),values=VALUES,
                tsens='26xx',cpufreq='standard-OSM',lut_max_cores=[6,2,2],battery='PM7250B/QG/ADC5/SMB5')


def load_anchor(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or not 1<=p.stat().st_size<=4096:
        raise ValueError('bounded private RTC anchor required')
    v=json.loads(p.read_text())
    if (type(v) is not dict or v.get('version')!=1 or v.get('product')!='redfin' or
        v.get('source')!='verified-offline-recovery/host-UTC' or
        any(type(v.get(k)) is not int for k in ['rtc_seconds','unix_offset_seconds','uncertainty_ms']) or
        not 0<v['rtc_seconds']<2**32 or not 0<=v['unix_offset_seconds']<2**32 or
        not 0<=v['uncertainty_ms']<=2500 or
        not 1577836800<=v['rtc_seconds']+v['unix_offset_seconds']<4102444800):
        raise ValueError('unsupported native RTC epoch mapping')
    return v


def apply(root,blob,anchor=None):
    from ports.redfin.mkadt import node,u32,u64
    proof=validate(blob)
    if any(n.name=='redfin-power' for n in root.children):
        raise ValueError('conflicting native power leaf')
    props=[('native-contract',u32(*VALUES))]
    if anchor is not None:
        props.append(('rtc-anchor',u64(anchor['rtc_seconds'],anchor['unix_offset_seconds'])))
    root.children.append(node('redfin-power',props))
    return dict(proof,rtc_anchored=anchor is not None,physical_rtc_written=False)
