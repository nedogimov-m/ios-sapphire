"""Validate Redfin's captured panel/TE/register facts for physical90Hz."""
import struct

PROPERTY='redfin,panel-mode'
VALUES=(1,1080,2340,554000000,0x0af00000,0x0ae94000,0x0ae6b800,0x0f50a000,10,0x80152853,0x80153853)


def add_contract(root,nodes):
    from ports.redfin import mkadt
    def require(path,key,wanted):
        if nodes.get(path,{}).get(key)!=wanted:
            raise ValueError('physical panel contract differs: '+path+':'+key)
    require('/soc/qcom,dispcc@af00000','reg',struct.pack('>II',0xaf00000,0x20000))
    require('/soc/qcom,mdss_dsi0_ctrl','compatible',b'qcom,dsi-ctrl-hw-v2.4\0')
    require('/soc/qcom,mdss_dsi0_ctrl','reg',struct.pack('>4I',0xae94000,0x400,0xaf08000,4))
    require('/soc/pinctrl@f000000','reg',struct.pack('>II',0xf000000,0x1000000))
    primary=nodes.get('/soc/qcom,dsi-display-primary',{})
    reference=primary.get('qcom,dsi-default-panel')
    panels=[path for path,props in nodes.items() if props.get('phandle')==reference]
    if not reference or len(panels)!=1:
        raise ValueError('one source-identified primary panel required')
    panel=panels[0]
    if not panel.startswith('/soc/qcom,mdss_mdp/qcom,mdss_dsi_s6e3hc2_'):
        raise ValueError('primary display is not the native S6E3HC2')
    require(panel,'qcom,mdss-dsi-panel-type',b'dsi_cmd_mode\0')
    require('/soc/qcom,mdss_mdp','qcom,sde-intf-off',struct.pack('>4I',0x6b000,0x6b800,0x6c000,0x6c800))
    require('/soc/qcom,mdss_mdp','qcom,sde-intf-type',b'dp\0dsi\0dsi\0dp\0')
    gpio=primary.get('qcom,platform-te-gpio',b'')
    if len(gpio)!=12 or struct.unpack('>III',gpio)[1:]!=(10,0):
        raise ValueError('native TE input must be GPIO10')
    phandle=struct.unpack('>I',gpio[:4])[0]
    require('/soc/pinctrl@f000000','phandle',struct.pack('>I',phandle))
    for index,hz,transfer,command in [(0,60,14000,0x28),(1,90,9000,0x38)]:
        timing=panel+'/qcom,mdss-dsi-display-timings/timing@'+str(index)
        for key,value in [('qcom,mdss-dsi-panel-framerate',hz),('qcom,mdss-dsi-panel-clockrate',554000000),
                ('qcom,mdss-mdp-transfer-time-us',transfer),('qcom,mdss-dsi-panel-width',1080),
                ('qcom,mdss-dsi-panel-height',2340)]:
            require(timing,key,struct.pack('>I',value))
        require(timing,'qcom,mdss-dsi-timing-switch-command',bytes([0x15,1,0,0,0,0,2,0x53,command]))
        require(timing,'qcom,mdss-dsi-timing-switch-command-state',b'dsi_lp_mode\0')
    arm=[child for child in root.children if child.name=='arm-io']
    displays=[child for parent in arm for child in parent.children if child.name=='disp0']
    if len(displays)!=1 or any(key==PROPERTY for key,_,_ in displays[0].props):
        raise ValueError('one verified display without duplicate mode contract required')
    displays[0].props.append((PROPERTY,0,mkadt.u32(*VALUES)))
    return dict(panel=panel,requested_hz=90,physical_refresh_requires_TE_verification=True,
        memory_DMA_used=False,PLL_or_SMMU_changes=False)
