"""Read-only audit of the installed20H392 CoreBrightness service contract."""
import hashlib

LIBRARY='/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness'
UUID='6c7092504a87363088ef325ae48779cb'
# Reviewed native bodies: dictionary-required DisplayCreateWithID; CFData
# ignore-IOMFB test in DisplayOpen; driver nits remain separate from IOMFB.
BODIES={
    '_DisplayCreateWithID':(22204,'36c7c45a6b378ffc873aea2d3aeaf0969048207bed33d88f1155399dacf26959'),
    '_DisplayOpen':(3704,'c55482ae256a248f4493dea51f991191e839575a1c2c275d3a5fbf89e5e50987'),
    '_SetBLDriverNitsValue':(1500,'d6031d2d69cd22c59043472e403aaa07f76d6ccbca0c100485bc3e8f586a1672'),
}
SYSTEM_LIBRARY='/System/Library/PrivateFrameworks/BackBoardServices.framework/BackBoardServices'
SYSTEM_UUID='a9d6b8ce7863381fb1ab1055a11412d5'
SYSTEM_BODIES={
    '_BKSDisplayBrightnessSetWithImplicitTransaction':(68,'f44c0accd444c0897e52e0cba2bf5faa07eca76fc038689fc2e5fbbe1ca21520'),
    '_BKSDisplayBrightnessGetCurrent':(80,'d6eb8011f59328a38d78c18d11559048310cc8f3ecb7b8f5fc18aef912593edb'),
}


def derive(cache):
    image=cache.image(LIBRARY)
    if image.uuid!=UUID:raise ValueError('unreviewed native CoreBrightness UUID')
    symbols=cache.local_symbols(image,set(BODIES))
    for name,(size,digest) in BODIES.items():
        if hashlib.sha256(cache.read(symbols[name],size)).hexdigest()!=digest:
            raise ValueError('native CoreBrightness contract changed: '+name)
    return dict(version=1,uuid=image.uuid,required_dictionary='IODisplayParameters',
        brightness_fields=['min','max','value'],raw_brightness_units='panel DBV',
        nits_units='16.16',independent_native_backlight=True,
        ignore_IOMFB_property='uint32 CFData',bodies={name:dict(bytes=size,sha256=digest)
            for name,(size,digest) in BODIES.items()},physical_calibration_claimed=False)


def derive_system(cache):
    image=cache.image(SYSTEM_LIBRARY)
    if image.uuid!=SYSTEM_UUID:raise ValueError('unreviewed native system-brightness UUID')
    exports,_=image.exports()
    for name,(size,digest) in SYSTEM_BODIES.items():
        if not exports.get(name) or hashlib.sha256(cache.read(exports[name],size)).hexdigest()!=digest:
            raise ValueError('native system-brightness ABI changed: '+name)
    uikit=cache.image('/System/Library/PrivateFrameworks/UIKitCore.framework/UIKitCore')
    method=uikit.objc_methods('UIDevice',selectors=['-_setBacklightLevel:'])['-_setBacklightLevel:']
    if method['types']!='v20@0:8f16' or hashlib.sha256(cache.read(uikit.base+method['rva'],152)).hexdigest()!=\
            '84616347b38087c9f120d8914ecaa115d24e86499b9ed9b01d240bea9cfe7082':
        raise ValueError('native application-scene brightness route changed')
    return dict(version=1,uuid=image.uuid,set_signature='void(float)',get_signature='float(void)',
        set_export='BKSDisplayBrightnessSetWithImplicitTransaction',get_export='BKSDisplayBrightnessGetCurrent',
        scene_independent=True,UIKit_setter_requires_application_scene=True,
        actual_native_functions_unmodified=True,bodies={name:dict(bytes=size,sha256=digest)
            for name,(size,digest) in SYSTEM_BODIES.items()})
