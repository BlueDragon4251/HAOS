"""Data-only theme generation through the existing mission GUI queue."""
import re

COLORS=['bg','bg2','surface','fg','fg_dim','accent','accent_strong','border_active','border_inactive','urgent','ok','warn']
OPERATIONS={'theme.sdk','theme.stage'}
SDK={'colors':COLORS,'shell_themes':['ocean','graphite'],'accents':['blue','ice','violet'],
     'schemes':['dark','light'],'wallpaper':'drawn','executable_extensions':False}


def action(value):
    if not isinstance(value,dict) or value.get('operation') not in OPERATIONS:
        raise PermissionError('mission data theme capability denied')
    if value['operation']=='theme.sdk':
        if set(value)!={'operation'}:raise PermissionError('closed theme schema request required')
        return value
    if set(value)!={'operation','theme'} or not isinstance(value['theme'],dict):
        raise PermissionError('closed theme data required')
    spec=value['theme']
    if set(spec)-{'colors','label','description','shell'} or 'colors' not in spec:
        raise PermissionError('no theme names, paths, assets, code or plugins accepted')
    if not isinstance(spec['colors'],dict) or set(spec['colors'])!=set(COLORS) or any(
            not isinstance(v,str) or not re.fullmatch(r'#[a-f0-9]{6}',v,re.I) for v in spec['colors'].values()):
        raise ValueError('complete closed hex palette required')
    for key,limit in [('label',128),('description',2048)]:
        if key in spec and (not isinstance(spec[key],str) or len(spec[key].encode())>limit
                or any(ord(c)<32 or 127<=ord(c)<=159 for c in spec[key])):
            raise ValueError('bounded plain theme metadata required')
    if 'shell' in spec:
        shell=spec['shell'];allowed={'theme':SDK['shell_themes'],'accent':SDK['accents'],'scheme':SDK['schemes']}
        if not isinstance(shell,dict) or set(shell)-set(allowed) or any(shell[k] not in allowed[k] for k in shell):
            raise PermissionError('only installed theme presets accepted')
    return value


def receipt(op,value):
    if op=='theme.sdk':
        if value!=SDK or type(value['executable_extensions']) is not bool:raise ValueError('installed theme schema identity differs')
        return value
    if (op!='theme.stage' or not isinstance(value,dict) or set(value)!={'name','revision','scope'}
            or value['scope']!='mission-data-theme' or not isinstance(value['name'],str)
            or not re.fullmatch(r'haos-t-[a-f0-9]{32}',value['name']) or not isinstance(value['revision'],str)
            or not re.fullmatch(r'[a-f0-9]{64}',value['revision'])):
        raise ValueError('verified mission theme revision required')
    return value
