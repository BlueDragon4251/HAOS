"""Owner/source-bound sealed output upload; independent from message delivery."""
from copy import deepcopy
import re

from .gateway_feishu_send import specification as reply_specification
from .gateway_feishu_upload_http import target
from .gateway_feishu_process import ERRORS


def specification(value,policy,connector,item,redactor):
    base={'binding_id','binding_digest','delivery_id','attempt','source_id','source_sha256','source_base64'}
    if not isinstance(item,dict) or set(item)!=base|{'output'}:raise ValueError('exact sealed Feishu upload intent required')
    checked=reply_specification(value,policy,connector,{**{key:item[key] for key in base},'body':'Sealed owner-approved output.'},redactor)
    binding=policy.current_binding(checked)
    if binding.get('allow_outbound_media') is not True:raise PermissionError('separate current output/read consent required')
    output=item['output']
    if (not isinstance(output,dict) or set(output)!={'id','kind','name','size','sha256','file_type','duration_ms'}
            or not isinstance(output['id'],str) or not re.fullmatch('[0-9a-f]{64}',output['id'])):
        raise ValueError('opaque immutable controller output offer required')
    blueprint=target({key:part for key,part in output.items() if key!='id'})
    return {'intent':deepcopy(item),'target':blueprint}


def response(result,expected):
    if result=={'state':'uncertain'}:return result
    if (isinstance(result,dict) and set(result)=={'state','error'} and result['state']=='rejected'
            and isinstance(result['error'],str) and result['error'] in ERRORS|{'native-refused'}):return result
    if (not isinstance(result,dict) or set(result)!={'state','kind','key'} or result['state']!='confirmed'
            or result['kind']!=expected['kind'] or not isinstance(result['key'],str)
            or not re.fullmatch(('img_' if expected['kind']=='image' else 'file_')+'[A-Za-z0-9_-]{8,251}',result['key'])):
        raise ValueError('exact private native upload acceptance required')
    return result
