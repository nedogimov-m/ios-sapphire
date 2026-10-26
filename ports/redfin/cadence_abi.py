"""Audit the installed20H392 native CLCD heartbeat configuration, read-only."""
import hashlib
import struct

QUARTZ='/System/Library/Frameworks/QuartzCore.framework/QuartzCore'
LIBC='/usr/lib/system/libsystem_c.dylib'
UUID='9e40b2eb260c3af1ae45a1a551a8c1b9'
HEARTBEAT='__ZNK2CA12WindowServer16AppleCLCDDisplay14heartbeat_rateEv'


def need(ok,message):
    if not ok:raise ValueError('native display cadence: '+message)


def signed(value,bits):
    return value-(1<<bits) if value&(1<<(bits-1)) else value


def page_address(word,pc,register):
    need(word&0x9f00001f==0x90000000|register,'unreviewed native address formation')
    immediate=((word>>5)&0x7ffff)<<2|((word>>29)&3)
    return (pc&~4095)+(signed(immediate,21)<<12)


def add_address(word,page,register):
    need(word&0xffc003ff==0x91000000|(register<<5)|register,
         'unreviewed native address offset')
    return page+((word>>10)&4095)


def call_target(cache,word,pc):
    need(word&0xfc000000==0x94000000,'unreviewed native call')
    target=pc+(signed(word&0x3ffffff,26)<<2)
    first,second,last=struct.unpack('<III',cache.read(target,12))
    need(last==0xd61f0200,'unreviewed shared-cache branch stub')
    return add_address(second,page_address(first,target,16),16)


def derive(cache):
    image=cache.image(QUARTZ)
    need(image.uuid==UUID,'unreviewed QuartzCore UUID')
    address=cache.local_symbols(image,{HEARTBEAT})[HEARTBEAT]
    body=cache.read(address,200);words=struct.unpack('<50I',body)
    key=add_address(words[8],page_address(words[7],address+28,0),0)
    need(cache.string(key)=='CA_HEARTBEAT_RATE','native heartbeat environment key changed')
    exports,_=cache.image(LIBC).exports()
    need(call_target(cache,words[9],address+36)==exports.get('_getenv'),
         'native heartbeat no longer reads its environment')
    need(call_target(cache,words[11],address+44)==exports.get('_atof'),
         'native heartbeat rate parser changed')
    # Native code computes1.0/atof(value), then caches that period. Keeping
    # the exact reviewed image and instructions avoids a guessed unit or API.
    need(words[13]==0x1e601820,'native heartbeat reciprocal changed')
    return {'version':1,'quartz_uuid':image.uuid,'environment':'CA_HEARTBEAT_RATE',
            'input_units':'Hz','native_output_units':'seconds per heartbeat',
            'native_symbol':HEARTBEAT,'native_body_sha256':hashlib.sha256(body).hexdigest(),
            'real_native_timer':True,'changes_timestamps':False}
