"""Frozen host contract for the bounded eight-core iOS/touch boot."""
import re

REQUIRED = frozenset(('debug=0xc serial=3 cpus=8 keepsyms=1 -noprogress rd=ufsroot0 '
    'sweettouch=0 sweetkeys=0 sweetusb=0 sweetcpufreq=0 sweetbattery=0 modem=0 wifi=0 gpu=0 '
    'unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin '
    'launchd_unsecure_cache=1 wdt=-1 redfinfb=1 sweetfb_noconsole=1 sweetfb_hz=10 '
    'redfinshutdown=180 redfintouch=2 redfinrail=1 redfintouchsetup=1 redfinrpmhtouch=1 '
    'redfintouchevents=1 redfinufs=3 redfinspmi=0 redfinreturn=0 redfinroot=1 '
    'ufsroot=userdata ufsrw=1 rootrw=1 sweetlog=0 redfinsmp=1 redfinshim=1 redfingui=1').split())


def validate(arguments):
    if not isinstance(arguments, str) or len(arguments) >= 608 or not arguments.isascii():
        raise ValueError('GUI8 requires bounded ASCII boot args')
    tokens = arguments.split()
    ids = [token for token in tokens if token.startswith('redfinbootid=')]
    match = re.fullmatch(r'redfinbootid=0x([0-9a-f]{16})', ids[0]) if len(ids) == 1 else None
    flags = [token for token in tokens if token not in ids and token != '-enable_kprintf_spam']
    fits = [token for token in flags if token.startswith('redfinfit')]
    if len(fits) > 1 or any(token not in ('redfinfit=1', 'redfinfit=2') for token in fits):
        raise ValueError('GUI8 fit must be full-canvas mode1 or camera-exclusion mode2')
    screens = [token for token in flags if token.startswith('redfinscreen')]
    if screens and (screens != ['redfinscreen=1'] or fits != ['redfinfit=2']):
        raise ValueError('GUI8 screen capture requires the camera-exclusion profile')
    flags = [token for token in flags if token not in screens]
    flags = [token for token in flags if token not in fits]
    rates = [token for token in flags if token.startswith('sweetfb_hz=')]
    if len(rates) != 1 or rates[0] not in ('sweetfb_hz=10', 'sweetfb_hz=30', 'sweetfb_hz=60'):
        raise ValueError('GUI8 copy cadence must be exactly 10, 30 or 60 Hz')
    flags = ['sweetfb_hz=10' if token == rates[0] else token for token in flags]
    if (arguments != ' '.join(tokens) or len(flags) != len(REQUIRED) or set(flags) != REQUIRED or
            tokens.count('-enable_kprintf_spam') > 1 or match is None or not int(match[1], 16)):
        raise ValueError('GUI8 requires its exact eight-core, touch, RW root and 180s return profile')
    return match[1]


def cadence(arguments):
    validate(arguments)
    return next(int(token.split('=', 1)[1]) for token in arguments.split() if token.startswith('sweetfb_hz='))
