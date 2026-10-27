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
