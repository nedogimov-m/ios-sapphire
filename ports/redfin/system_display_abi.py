"""Reviewed actual20H392 native backlight route and finite idle assertion ABI.

Only metadata and hashes are retained. Native Apple images stay private;
this audit neither fabricates brightness capability nor claims hardware success.
"""
import hashlib
import struct

CONTAINER_IVARS={'_displayService':('I',4),'_display':('@"CADisplay"',8),
    '_brtCtl':('@"<CBBrightnessProxy>"',8),'_displayControlModule':('@"<CBContainerModuleProtocol>"',8)}

REVIEWED = {'BSSimpleAssertion__isValid': {'library': '/System/Library/PrivateFrameworks/BaseBoard.framework/BaseBoard',
                                'uuid': '809da722a9b53acfa0e7e41632331f2b',
                                'cls': 'BSSimpleAssertion',
                                'selector': '-isValid',
                                'types': 'B16@0:8',
                                'bytes': 28,
                                'sha256': '3bf6229d06d761b724a5b658298278bf3ca3c8c738132c5bdb2eb3b27d2a1f10'},
 'BSSimpleAssertion__invalidate': {'library': '/System/Library/PrivateFrameworks/BaseBoard.framework/BaseBoard',
                                   'uuid': '809da722a9b53acfa0e7e41632331f2b',
                                   'cls': 'BSSimpleAssertion',
                                   'selector': '-invalidate',
                                   'types': 'v16@0:8',
                                   'bytes': 88,
                                   'sha256': '5d3a56ccf0f4fc9982b904c7e5214e1b6f689f641e95be5a577fee9bcedd360c'},
 'CAWindowServerDisplay__brightnessAvailable': {'library': '/System/Library/Frameworks/QuartzCore.framework/QuartzCore',
                                                'uuid': '9e40b2eb260c3af1ae45a1a551a8c1b9',
                                                'cls': 'CAWindowServerDisplay',
                                                'selector': '-brightnessAvailable',
                                                'types': 'B16@0:8',
                                                'bytes': 144,
                                                'sha256': 'e4b9c9d2de3d6794144eee1e26cf68a91ba118867fb23f38172ef43c93c95358'},
 'CAWindowServerDisplay__displayType': {'library': '/System/Library/Frameworks/QuartzCore.framework/QuartzCore',
                                        'uuid': '9e40b2eb260c3af1ae45a1a551a8c1b9',
                                        'cls': 'CAWindowServerDisplay',
                                        'selector': '-displayType',
                                        'types': 'q16@0:8',
                                        'bytes': 52,
                                        'sha256': 'e4ebb3fbed2c472b3410b9b2fb5e765fdf66d7f86e8a5f3255883024f1fecc64'},
 'CAWindowServerDisplay__displayId': {'library': '/System/Library/Frameworks/QuartzCore.framework/QuartzCore',
                                      'uuid': '9e40b2eb260c3af1ae45a1a551a8c1b9',
                                      'cls': 'CAWindowServerDisplay',
                                      'selector': '-displayId',
                                      'types': 'I16@0:8',
                                      'bytes': 32,
                                      'sha256': '2082608cd267586ef36f82a1849a5e2ec7d72b994fd7e5c1a151f7b6da0bc9aa'},
 'SBIdleTimerGlobalCoordinator__isIdleTimerDisabled': {'library': '/System/Library/PrivateFrameworks/SpringBoard.framework/SpringBoard',
                                                       'uuid': '22034aba9a9a3b9493a5a0de02befd2e',
                                                       'cls': 'SBIdleTimerGlobalCoordinator',
                                                       'selector': '-isIdleTimerDisabled',
                                                       'types': 'B16@0:8',
                                                       'bytes': 52,
                                                       'sha256': '059347a29f84ae8b929cdeb36f533a04871f5205762c51641c4db8d4fbf59d32'},
 'SBIdleTimerGlobalCoordinator__acquireIdleTimerDisableAssertionForReason_': {'library': '/System/Library/PrivateFrameworks/SpringBoard.framework/SpringBoard',
                                                                              'uuid': '22034aba9a9a3b9493a5a0de02befd2e',
                                                                              'cls': 'SBIdleTimerGlobalCoordinator',
                                                                              'selector': '-acquireIdleTimerDisableAssertionForReason:',
                                                                              'types': '@24@0:8@16',
                                                                              'bytes': 956,
                                                                              'sha256': '539bcce84e0933b72cae06c4de25e395a7258bb939896b932f84348a0b1ecf9c'},
 'SBIdleTimerGlobalCoordinator__sharedInstanceIfExists': {'library': '/System/Library/PrivateFrameworks/SpringBoard.framework/SpringBoard',
                                                          'uuid': '22034aba9a9a3b9493a5a0de02befd2e',
                                                          'cls': 'SBIdleTimerGlobalCoordinator',
                                                          'selector': '+sharedInstanceIfExists',
                                                          'types': '@16@0:8',
                                                          'bytes': 8,
                                                          'sha256': 'ccb9c2dc444a956ed024317ba8906318c7fe4a5e516fe06264bf5fda0fd9f35e'},
 'BLControl__findBacklight': {'library': '/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness',
                              'uuid': '6c7092504a87363088ef325ae48779cb',
                              'cls': 'BLControl',
                              'selector': '-findBacklight',
                              'types': 'B16@0:8',
                              'bytes': 1024,
                              'sha256': '389aee116dbe7be084742631cac388446f140087af5ce6607f3a49b595811cc3'},
 'BLControl__useSyncBrightnessTransactionForDisplay_': {'library': '/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness',
                                                        'uuid': '6c7092504a87363088ef325ae48779cb',
                                                        'cls': 'BLControl',
                                                        'selector': '-useSyncBrightnessTransactionForDisplay:',
                                                        'types': 'B24@0:8@16',
                                                        'bytes': 508,
                                                        'sha256': 'eaa98b5bf5e5e263de82c66d67fcd4bf8cb5aab9b33b115768377bf9d4f6a354'},
 'BLControl__findDisplays': {'library': '/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness',
                             'uuid': '6c7092504a87363088ef325ae48779cb',
                             'cls': 'BLControl',
                             'selector': '-findDisplays',
                             'types': 'B16@0:8',
                             'bytes': 1660,
                             'sha256': '5dd02066810310cfe22a7f2c39c377dba32c29cba00411f0e69ec2abefce361f'},
 'CBDisplayContaineriOS__setupInternalModules': {'library': '/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness',
                                                 'uuid': '6c7092504a87363088ef325ae48779cb',
                                                 'cls': 'CBDisplayContaineriOS',
                                                 'selector': '-setupInternalModules',
                                                 'types': 'B16@0:8',
                                                 'bytes': 4724,
                                                 'sha256': 'd148467cf815fce85352c8ec14cce3c6d94f9e448835aa96819eb6203b4266c0'},
 'CBDisplayContaineriOS__start': {'library': '/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness',
                                  'uuid': '6c7092504a87363088ef325ae48779cb',
                                  'cls': 'CBDisplayContaineriOS',
                                  'selector': '-start',
                                  'types': 'B16@0:8',
                                  'bytes': 204,
                                  'sha256': '9eb19dfb4dd3d4f64343dcadc5c7a997694020d21fafbf09de0fb1afd272a61e'},
 'CBDisplayModuleiOS__start': {'library': '/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness',
                               'uuid': '6c7092504a87363088ef325ae48779cb',
                               'cls': 'CBDisplayModuleiOS',
                               'selector': '-start',
                               'types': 'v16@0:8',
                               'bytes': 20,
                               'sha256': '9fb52d6e9000768d5b39d1635bc0c286393e4b598343de875bd166905a593a2c'}}

REVIEWED['CADisplay__isExternal'] = {'library': '/System/Library/Frameworks/QuartzCore.framework/QuartzCore',
 'uuid': '9e40b2eb260c3af1ae45a1a551a8c1b9',
 'cls': 'CADisplay',
 'selector': '-isExternal',
 'types': 'B16@0:8',
 'bytes': 64,
 'sha256': '5f3a6f11936c7a3355d81453ccb16b619e38b7dcd43c4421a9dcf2c3daaeb212'}


BACKBOARD_UUID = '70b72340737a39738b474e9970f4ecb9'
BACKBOARD_METHODS = {'-setBrightnessLevel:reason:options:': {'types': 'v36@0:8f16@20Q28',
                                         'rva': 494428,
                                         'bytes': 860,
                                         'sha256': '52ef544e9702adac671b38bf03e89ef9d188dab19bbc32de5cd45fd56fcf1f2a'},
 '-isBrightnessLevelControlAvailable': {'types': 'B16@0:8',
                                        'rva': 495380,
                                        'bytes': 92,
                                        'sha256': '80037a2352ee78a9c41f45058348277b44d6ef6044533a0f580a09e0f9e1b297'}}

IOKIT_PROPERTIES = {
    'library':'/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit',
    'uuid':'bcae5dd845f9387792cb44190c3bad70',
    'export':'_IORegistryEntrySetCFProperties',
    'signature':'kern_return_t(io_registry_entry_t,CFTypeRef)',
    'bytes':148,
    'sha256':'e9e04c0978ec5ccccb172f31a23d35b02ecd12fb7f434072d5ff847cc2ff9829',
}


def derive_backboard():
    from ports.redfin.graphics_abi import ROOT
    path=ROOT/'research/ipsw-redfin/extracted/mounts/os/usr/libexec/backboardd'
    raw=path.read_bytes()
    if len(raw)>8*1024*1024 or struct.unpack_from('<II',raw)!=(0xfeedfacf,0x100000c):
        raise ValueError('bounded native arm64 backboardd required')
    count,size=struct.unpack_from('<II',raw,16)
    if not 0<count<256 or not 0<size<len(raw)-32:raise ValueError('invalid native backboardd commands')
    at=32;segments=[];uuid=None
    for _ in range(count):
        command,length=struct.unpack_from('<II',raw,at)
        if length<8 or at+length>32+size:raise ValueError('truncated native backboardd commands')
        if command==27:uuid=raw[at+8:at+24].hex()
        if command==25:
            va,_,offset,filesize=struct.unpack_from('<QQQQ',raw,at+24)
            segments.append((va,offset,filesize))
        at+=length
    if uuid!=BACKBOARD_UUID:raise ValueError('unreviewed native backboardd UUID')
    for name,method in BACKBOARD_METHODS.items():
        address=0x100000000+method['rva']
        matches=[(offset+address-va,method['bytes']) for va,offset,filesize in segments
            if va<=address and address+method['bytes']<=va+filesize]
        if len(matches)!=1:raise ValueError('unmapped native backboardd method: '+name)
        offset,length=matches[0]
        if hashlib.sha256(raw[offset:offset+length]).hexdigest()!=method['sha256']:
            raise ValueError('native backboardd brightness ABI changed: '+name)
    return dict(uuid=uuid,methods=BACKBOARD_METHODS,source_sha256=hashlib.sha256(raw).hexdigest(),
        original_native_handling_preserved=True,manual_backlight_only=True,auto_ALS_claimed=False)


def derive(cache):
    for name,record in REVIEWED.items():
        image=cache.image(record['library'])
        if image.uuid!=record['uuid']:
            raise ValueError('unreviewed native display image: '+name)
        method=image.objc_methods(record['cls'],selectors=[record['selector']]).get(record['selector'])
        if not method or method['types']!=record['types']:
            raise ValueError('native display method ABI changed: '+name)
        raw=cache.read(image.base+method['rva'],record['bytes'])
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:
            raise ValueError('native display method body changed: '+name)
    iokit=cache.image(IOKIT_PROPERTIES['library'])
    if iokit.uuid!=IOKIT_PROPERTIES['uuid']:raise ValueError('unreviewed native IOKit UUID')
    exports,_=iokit.exports()
    setter=exports.get(IOKIT_PROPERTIES['export'])
    if not setter or hashlib.sha256(cache.read(setter,IOKIT_PROPERTIES['bytes'])).hexdigest()!=IOKIT_PROPERTIES['sha256']:
        raise ValueError('native registry dictionary setter ABI changed')
    image=cache.image('/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness')
    start,size=image.sections['__objc_classlist'];found=None
    for at in range(start,start+size,8):
        cls=cache.pointer(at);ro=cache.pointer(cls+32)&~7
        if cache.string(cache.pointer(ro+24))!='CBDisplayContaineriOS':continue
        ivars=cache.pointer(ro+48);stride,count=struct.unpack('<II',cache.read(ivars,8))
        if stride!=32 or count>128:raise ValueError('unreviewed native container ivar layout')
        found={}
        for index in range(count):
            entry=ivars+8+index*stride;name=cache.string(cache.pointer(entry+8))
            if name in CONTAINER_IVARS:
                found[name]=(cache.string(cache.pointer(entry+16)),struct.unpack('<I',cache.read(entry+28,4))[0])
        break
    if found!=CONTAINER_IVARS:raise ValueError('native typed container observation fields changed')
    return dict(version=1,reviewed=REVIEWED,backboard=derive_backboard(),iokit_properties=IOKIT_PROPERTIES,
        backlight_transport='native CoreBrightness AppleARMBacklight',
        synchronous_IOMFB_brightness_supported=False,
        integrated_display_only=True,other_displays_preserved=True,
        idle_assertion='owned BSSimpleAssertion through SBIdleTimerGlobalCoordinator',
        idle_assertion_main_thread_only=True,hardware_success_claimed=False)
