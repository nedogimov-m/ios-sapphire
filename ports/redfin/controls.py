"""Bind Redfin's physical side/volume inputs and panel controls to its live FDT."""
import hashlib
import struct
from ports.redfin.memory import _tree

KEY_VALUES=(1,0x0c440000,0x0c40a000,0x0e600000,0,0x008,0x4c4,0x0810,0xc410,15)
DISPLAY_VALUES=(1,0x0af00000,0x0ae94000,1080,2340,4,1023,8,500)
DISPLAY_PROPERTY='redfin,panel-controls'


def validate(blob):
    nodes,_=_tree(blob)
    def node(path):
        value=nodes.get(path)
        if value is None or value.get('status',b'okay\0') not in (b'okay\0',b'ok\0'):
            raise ValueError('native controls: absent/disabled '+path)
        return value
    def require(path,key,value):
        if node(path).get(key)!=value:
            raise ValueError('native controls: '+path+':'+key)
    def words(*values):
        return struct.pack('>'+len(values)*'I',*values)
    spmi='/soc/qcom,spmi@c440000'
    require(spmi,'compatible',b'qcom,spmi-pmic-arb\0')
    require(spmi,'reg',words(0xc440000,0x1100,0xc600000,0x2000000,
        0xe600000,0x100000,0xe700000,0xa0000,0xc40a000,0x26000))
    require(spmi,'reg-names',b'core\0chnls\0obsrvr\0intr\0cnfg\0')
    for key in ('qcom,ee','qcom,channel'):
        require(spmi,key,words(0))
    primary=spmi+'/qcom,pm8150@0';secondary=spmi+'/qcom,pm8150l@4'
    for path,sid in ((primary,0),(secondary,4)):
        require(path,'compatible',b'qcom,spmi-pmic\0');require(path,'reg',words(sid,0))
    pon=primary+'/qcom,power-on@800'
    require(pon,'compatible',b'qcom,qpnp-power-on\0');require(pon,'reg',words(0x800,0x100))
    for index,code in ((0,116),(1,114)):
        path=pon+'/qcom,pon_'+str(index+1)
        require(path,'qcom,pon-type',words(index));require(path,'linux,code',words(code))
    pinctrl=secondary+'/pinctrl@c000'
    require(pinctrl,'compatible',b'qcom,spmi-gpio\0');require(pinctrl,'reg',words(0xc000,0xc00))
    phandle=node(pinctrl).get('phandle')
    if not phandle or len(phandle)!=4:
        raise ValueError('native controls: GPIO provider identity missing')
    require('/soc/gpio_keys','compatible',b'gpio-keys\0')
    require('/soc/gpio_keys/vol_up','gpios',phandle+words(5,1))
    require('/soc/gpio_keys/vol_up','linux,code',words(115))
    require('/soc/gpio_keys/vol_up','debounce-interval',words(15))
    pin=pinctrl+'/key_vol_up/key_vol_up_default'
    for key,value in (('pins',b'gpio5\0'),('function',b'normal\0'),
                      ('input-enable',b''),('bias-pull-up',b'')):
        require(pin,key,value)
    primary_display=node('/soc/qcom,dsi-display-primary')
    ref=primary_display.get('qcom,dsi-default-panel')
    panels=[p for p,v in nodes.items() if ref and v.get('phandle')==ref]
    if len(panels)!=1 or not panels[0].startswith('/soc/qcom,mdss_mdp/qcom,mdss_dsi_s6e3hc2_'):
        raise ValueError('native controls: one physical S6E3HC2 panel required')
    panel=panels[0]
    for key,value in (('qcom,mdss-dsi-panel-type',b'dsi_cmd_mode\0'),
            ('qcom,mdss-dsi-bl-pmic-control-type',b'bl_ctrl_dcs\0'),
            ('qcom,mdss-dsi-bl-min-level',words(4)),('qcom,mdss-dsi-bl-max-level',words(1023)),
            ('qcom,mdss-brightness-max-level',words(1023)),('google,dsi-bl-cmd-high-byte-offset',words(8))):
        require(panel,key,value)
    require('/soc/qcom,mdss_dsi0_ctrl','compatible',b'qcom,dsi-ctrl-hw-v2.4\0')
    require('/soc/qcom,mdss_dsi0_ctrl','reg',words(0xae94000,0x400,0xaf08000,4))
    require('/soc/qcom,dispcc@af00000','reg',words(0xaf00000,0x20000))
    timing=panel+'/qcom,mdss-dsi-display-timings/timing@0'
    require(timing,'qcom,mdss-dsi-panel-width',words(1080))
    require(timing,'qcom,mdss-dsi-panel-height',words(2340))
    return dict(live_fdt_sha256=hashlib.sha256(blob).hexdigest(),
        key_contract=KEY_VALUES,display_contract=DISPLAY_VALUES,panel=panel,
        physical_key_inputs=['PM8150/PON KPDPWR','PM8150L/GPIO5','PM8150/PON RESIN'],
        pmic_writes=False,panel_memory_DMA=False,physical_behaviour_requires_verification=True)


def apply(root,blob):
    from ports.redfin.mkadt import node,u32
    proof=validate(blob)
    if any(child.name=='redfin-controls' for child in root.children):
        raise ValueError('native controls: conflicting leaf')
    displays=[child for parent in root.children if parent.name=='arm-io'
        for child in parent.children if child.name=='disp0']
    if len(displays)!=1 or any(key==DISPLAY_PROPERTY for key,_,_ in displays[0].props):
        raise ValueError('native controls: one display without conflicting control policy required')
    displays[0].props.append((DISPLAY_PROPERTY,0,u32(*DISPLAY_VALUES)))
    root.children.append(node('redfin-controls',[('keys-contract',u32(*KEY_VALUES))]))
    return proof
