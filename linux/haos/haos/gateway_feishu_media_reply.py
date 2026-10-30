"""Exact native media payload/reply after a confirmed owner-bound upload."""
import asyncio
import json

from .gateway import digest
from .gateway_feishu_upload import specification as upload_specification,response as upload_response
from .gateway_feishu_send import bind_single_native_send
from .gateway_feishu import MESSAGE_ID


def specification(value,policy,connector,item,redactor):
    if not isinstance(item,dict) or set(item)!={'upload','receipt','caption'}:
        raise ValueError('exact confirmed upload media reply required')
    checked=upload_specification(value,policy,connector,item['upload'],redactor)
    receipt=upload_response(item['receipt'],checked['target'])
    if receipt['state']!='confirmed':raise PermissionError('confirmed upload receipt required before media reply')
    caption=item['caption']
    if (not isinstance(caption,str) or len(caption)>4000 or len(caption.encode())>16000 or '\0' in caption
            or redactor.text(caption)!=caption):raise ValueError('bounded credential-free media caption required')
    return {'upload':checked,'receipt':receipt,'caption':caption}


def wire_target(adapter,blueprint):
    original=blueprint['upload']['intent'];output=blueprint['upload']['target'];receipt=blueprint['receipt'];key=receipt['key']
    if output['kind']=='image':msg_type='image';payload={'image_key':key};tag={'tag':'img','image_key':key}
    else:
        file_type,msg_type=adapter._resolve_outbound_file_routing(file_path=output['name'],requested_message_type='file')
        if file_type!=output['file_type']:raise PermissionError('media upload routing differs from pinned native codec')
        payload={'file_key':key};tag={'tag':'media','file_key':key,'file_name':output['name']}
    caption=blueprint['caption']
    content=adapter._build_media_post_payload(caption=caption,media_tag=tag) if caption else json.dumps(payload,ensure_ascii=False)
    binding=adapter._haos_media_binding
    exact={'chat_id':binding['chat'],'reply_to':original['source_id'],'thread_id':binding['thread'],
        'msg_type':'post' if caption else msg_type,'content':content,
        'uuid':digest([original['delivery_id'],original['binding_digest'],original['source_id'],original['output']['id'],caption,key])[:32]}
    from .gateway_feishu_media_reply_http import target
    return target(exact),{'key_msg_type':msg_type,'key_payload':payload,'media_tag':tag}


def send(request,value,home,current,redactor):
    from pathlib import Path
    from .gateway_feishu import PreparedFeishuPolicy,DOMAINS
    from .sandbox import trusted_json
    from .gateway_feishu_http import sdk_scope
    from .gateway_feishu_media_reply_http import MediaReplyBoundary
    from .gateway_matrix_profile import scope
    from .gateway_feishu_process import ERRORS
    def policy():current();return PreparedFeishuPolicy(trusted_json(Path('/etc/haos/gateways.json')))
    blueprint=specification(value,policy(),request['connector'],request['media_reply'],redactor)
    operation=None
    try:
        with scope(home,{'HERMES_SAFE_MODE':'1'}):
            from plugins.platforms.feishu import adapter as native
            from gateway.config import PlatformConfig
            if not native._load_lark_oapi():return {'state':'rejected','error':'sdk-unavailable'}
            adapter=native.FeishuAdapter(PlatformConfig(enabled=True))
            adapter._haos_media_binding=policy().current_binding(blueprint['upload']['intent'])
            exact,arguments=wire_target(adapter,blueprint);bind_single_native_send(adapter,exact)
            def authorize(purpose,target):
                latest=specification(value,policy(),request['connector'],request['media_reply'],redactor)
                return purpose=='media-reply' and latest==blueprint and target==exact
            boundary=MediaReplyBoundary(value,current,authorize,redactor);boundary.remember(blueprint['receipt']['key'])
            with sdk_scope():
                client=native._build_lark_client(value['app_id'],value['app_secret'],DOMAINS[value['domain']]);adapter._client=client
                with boundary.operation(client._config,'media-reply',exact) as operation:
                    response=asyncio.run(native.FeishuAdapter._send_uploaded_key(adapter,chat_id=exact['chat_id'],reply_to=exact['reply_to'],
                        metadata={'thread_id':exact['thread_id']},caption=blueprint['caption'] or None,**arguments))
                    current();body=operation.get('reply_response',{});data=body.get('data')
                    identity=getattr(getattr(response,'data',None),'message_id',None)
                    if (response.success() and body.get('code')==0 and isinstance(data,dict) and isinstance(identity,str)
                            and MESSAGE_ID.fullmatch(identity) and redactor.text(identity)==identity
                            and data.get('message_id')==identity and data.get('chat_id')==exact['chat_id']
                            and data.get('thread_id') in {None,'',exact['thread_id']}):
                        return {'state':'confirmed','message_id':identity}
                    if type(body.get('code')) is int and body['code']!=0:
                        return {'state':'rejected','error':'rate-limited' if body['code']==99991400 else 'native-refused'}
                    return {'state':'uncertain'}
    except Exception as error:
        known=operation is None or not operation.get('write_started') or operation.get('http_status') in {401,403,429}
        kind=getattr(error,'kind','authority-or-protocol-refused')
        return {'state':'rejected','error':kind if kind in ERRORS else 'authority-or-protocol-refused'} if known else {'state':'uncertain'}
