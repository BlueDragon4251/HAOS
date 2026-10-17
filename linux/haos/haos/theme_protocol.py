"""Data-only theme generation through the existing mission GUI queue."""
import re

COLORS=['bg','bg2','surface','fg','fg_dim','accent','accent_strong','border_active','border_inactive','urgent','ok','warn']
OPERATIONS={'theme.sdk','theme.stage','theme.preview','theme.apply'}
SDK={'colors':COLORS,'shell_themes':['ocean','graphite'],'accents':['blue','ice','violet'],
     'schemes':['dark','light'],'wallpaper':'drawn','executable_extensions':False}


def action(value):
    if not isinstance(value,dict) or value.get('operation') not in OPERATIONS:
        raise PermissionError('mission data theme capability denied')
    if value['operation']=='theme.sdk':
        if set(value)!={'operation'}:raise PermissionError('closed theme schema request required')
        return value
    if value['operation'] in {'theme.preview','theme.apply'}:
        if set(value)!={'operation','revision'} or not isinstance(value['revision'],str) or not re.fullmatch(r'[a-f0-9]{64}',value['revision']):
            raise PermissionError('only an exact saved mission revision is allowed')
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
    if (op not in OPERATIONS or not isinstance(value,dict) or not isinstance(value.get('name'),str)
            or not re.fullmatch(r'haos-t-[a-f0-9]{32}',value['name']) or not isinstance(value['revision'],str)
            or not re.fullmatch(r'[a-f0-9]{64}',value['revision'])):
        raise ValueError('verified mission theme revision required')
    if op=='theme.stage':
        if set(value)!={'name','revision','scope'} or value['scope']!='mission-data-theme':raise ValueError('closed staged theme receipt required')
    elif op=='theme.apply':
        if set(value)!={'name','revision','applied','verified'} or value['applied'] is not True or value['verified'] is not True:
            raise ValueError('confirmed actual shell activation required')
    else:
        import base64,hashlib
        checks={'sandbox','rendered','controlsVisible','textContrast','secondaryContrast','controlContrast','rasterDecoded'}
        if (set(value)!={'name','revision','passed','checks','stylesheet_sha256','png_sha256','mime','bytes','sha256','base64'}
                or type(value['passed']) is not bool or not isinstance(value['checks'],dict) or set(value['checks'])!=checks
                or any(type(v) is not bool for v in value['checks'].values()) or value['passed']!=all(value['checks'].values())
                or any(not isinstance(value[k],str) or not re.fullmatch(r'[a-f0-9]{64}',value[k]) for k in ('stylesheet_sha256','png_sha256'))
                or value['mime']!='image/jpeg' or not isinstance(value['base64'],str) or len(value['base64'])>1398104):
            raise ValueError('actual isolated theme preview required')
        pixels=base64.b64decode(value['base64'],validate=True)
        if (type(value['bytes']) is not int or not 100<=len(pixels)<=1048576 or value['bytes']!=len(pixels)
                or hashlib.sha256(pixels).hexdigest()!=value['sha256'] or not pixels.startswith(b'\xff\xd8') or not pixels.endswith(b'\xff\xd9')):
            raise ValueError('bounded actual preview pixels required')
    return value
