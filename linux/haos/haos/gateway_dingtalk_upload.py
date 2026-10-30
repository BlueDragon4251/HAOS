"""Source/read-grant-bound sealed Robot output upload; no agent host paths."""
from copy import deepcopy
import re

from .gateway_dingtalk_send import specification as reply_specification
from .gateway_dingtalk_upload_http import target,MEDIA_ID
from .gateway_dingtalk_reply_process import ERRORS

MAX_INPUT=14*1024*1024


def specification(value,policy,connector,item,redactor):
    base={'binding_id','binding_digest','delivery_id','attempt','source_id','source_sha256','source_base64'}
    if (not isinstance(item,dict) or set(item)!=base|{'output'} or value.get('reply_mode','session')!='robot'):
        raise PermissionError('exact sealed output and explicit owner Robot reply mode required')
    checked=reply_specification(value,policy,connector,{**{key:item[key] for key in base},'body':'Sealed owner-approved output.'},redactor)
    binding=policy.current_binding(checked)
    if binding.get('allow_outbound_media') is not True:raise PermissionError('separate current output/read approval required')
    output=item['output']
    if (not isinstance(output,dict) or set(output)!={'id','kind','name','size','sha256','mime'}
            or not isinstance(output['id'],str) or not re.fullmatch('[0-9a-f]{64}',output['id'])):
        raise ValueError('exact immutable controller output offer required')
    prepared=target({key:part for key,part in output.items() if key!='id'})
    if (prepared['kind']=='voice' and binding.get('allow_voice') is not True
            or prepared['kind']=='video' and binding.get('allow_video') is not True):
        raise PermissionError('separate current voice/video output approval required')
    return {'intent':deepcopy(item),'target':prepared}


def response(result,expected):
    if result=={'state':'uncertain'}:return result
    if (isinstance(result,dict) and set(result)=={'state','error','retry_after'}
            and result['state']=='rejected' and isinstance(result['error'],str) and result['error'] in ERRORS
            and type(result['retry_after']) is int and 0<=result['retry_after']<=86400
            and (result['error']=='rate-limited' or result['retry_after']==0)):
        return result
    if (not isinstance(result,dict) or set(result)!={'state','kind','media_id','created_at'}
            or result['state']!='confirmed' or result['kind']!=expected['kind']
            or not isinstance(result['media_id'],str) or not MEDIA_ID.fullmatch(result['media_id'])
            or '://' in result['media_id'] or type(result['created_at']) is not int or result['created_at']<=0):
        raise ValueError('exact private native upload acceptance required')
    return result
