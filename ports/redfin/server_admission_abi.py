"""Read-only actual20H392 CA window-server admission ABI; never changes state."""
import hashlib
from pathlib import Path
import re

LIBRARY='/System/Library/Frameworks/QuartzCore.framework/QuartzCore'
UUID='9e40b2eb260c3af1ae45a1a551a8c1b9'
PREFIX_SHA256={'SERVER_IF_RUNNING': '9fa7f098abe6a01144b1e3a43c817dbec2957883dc38e2cd2a4edbe6c7846f35', 'SERVER_DISPLAYS': '2856141cbe7b09bdfda651b9e7db3086872a345ca6967ebf450a8f01f7dd3527', 'DISPLAY_ID': 'f9a43ac9c2d38d0d59632589fa39e5fcef81715a13071af7ba6167cc6fa1ba28', 'DISPLAY_ENABLED': 'ec06392b8830fd8b5a91ef2a69e86eedb940dc1fa24b2c318bdb752642df440e', 'DISPLAY_DISABLED': '3d6f5c4a14d095507a276c11e9bba05bafcc7d0cf7b0f3a3b2265b7cc94dd8cf', 'DISPLAY_COMPOSITING': '12b11f9b04d9a39c720d363ba833e03ca0b6668990477f19fcc783a88f2dc5e4', 'DISPLAY_NEEDS_UPDATE': 'ab7a8a7d6b684df2570bd5964b2a3b00db547e952c69de21e169f22353074292', 'DISPLAY_FLIPBOOK': '327a52cc173ed15a1aa0bc50f7faa534125f5d92ce015650fa0b56a8a5258839', 'DISPLAY_MIN_FRAME': '1ce743504713d9a653ade6133d91eff6a37b3f65585c736ad1a95d2ac310693e', 'DISPLAY_MAX_FRAME': '41c44c159c2f17912cd25b4c336395d1937966a296bbba413f3847adbed1c669', 'DISPLAY_UPDATE_CALLBACK': '432a84951cadffde70838567c2919eb86c3efc71ad748bd0a66c4edecfcaf10b', 'DISPLAY_FRAME_CALLBACK': 'c5e60bd04ea25ecadeaf5d4ad67062b93615b64a8344a0f104224849632383a1', 'DISPLAY_HIT': 'f041be98a60462e1edea2922fa1574ec8c5d62a2b38dd3e9b34f653b6070b769', 'DISPLAY_UPDATE': '915c1f330d6a31bd0948f967b6103ab034d867529f5441df9552bcfe329369d0', 'DISPLAY_RENDER': '5e4d2fa87541824605e02d65b629f84dfccfec0bfe98bed765b689c26e5caf2e', 'DISPLAY_CAN_UPDATE': '13de21b8ae7e9ec2de5b1d3f4a467920dc867ef10bb26acd1603745ad3ac9b32', 'DISPLAY_CAN_FLAGS': '711c9d0ea34ac6cb941add504d235f74be04b4da22f17c79e492f2750095355a', 'DISPLAY_SET_ENABLED': 'b9e38afdf7cac955a8633531687fe3817170dcb3d1e75f3a569678a88d63dd96', 'DISPLAY_SET_DISABLED': '311dede707e9cbc215b56d37bda51186058410f4efc66079a932f46394a1902c', 'DISPLAY_SET_COMPOSITING': '7325cdbab6a966d6fd7e7eca8649d52ce3143b3d3bdac2ad41d0f6d8b4c84f36', 'DISPLAY_POWER': '85ad6e49bb7a93d3382df7dbb05e1699daa0157535bd95636e332500b5c9c54a', 'DISPLAY_MAIN': '49222df81a237546566b88b6406d0140dffae4b501ba9bf71b37fa2bb6dc8c12', 'DISPLAY_FRAME': '24ac1f7d72498887da596080ba4cd0f0de7259b9ecd95482261e0e7d4a708d9b'}


def methods():
    source=Path(__file__).with_name('server-admission-methods.def').read_text()
    rows=re.findall(r'^RF_SERVER_METHOD\((\w+),"([^"]+)","([^"]+)","([^"]+)",([01]),([01])\)$',source,re.M)
    if len(rows)!=len(PREFIX_SHA256) or {row[0] for row in rows}!=set(PREFIX_SHA256):
        raise ValueError('native server admission inventory changed')
    return rows


def derive(cache):
    image=cache.image(LIBRARY)
    if image.uuid!=UUID:raise ValueError('unreviewed native server admission image')
    result={}
    for key,cls,selector,types,meta,hook in methods():
        name=('+' if meta=='1' else '-')+selector
        method=image.objc_methods(cls,selectors=[name]).get(name)
        if not method or method['types']!=types or hashlib.sha256(cache.read(image.base+method['rva'],48)).hexdigest()!=PREFIX_SHA256[key]:
            raise ValueError('native server admission method changed: '+key)
        result[key]=dict(cls=cls,selector=selector,types=types,meta=meta=='1',observe_original_calls=hook=='1',prefix_sha256=PREFIX_SHA256[key])
    return dict(version=1,uuid=image.uuid,methods=result,forwards_original_arguments_and_results=True,
                queries_create_server=False,forces_render=False,changes_display_state=False)
