"""Fresh independent owner authority for each native delivery operation."""
from .gateway import GatewayPolicy


def current_delivery(adapter,platform,chat,metadata):
    if (not isinstance(metadata,dict) or not isinstance(metadata.get('haos_binding'),dict)
            or set(metadata['haos_binding'])!={'binding_id','binding_digest'}
            or not isinstance(metadata.get('haos_scope'),str)
            or not isinstance(metadata.get('thread_id',''),str)):
        raise PermissionError('exact independent owner delivery metadata required')
    native=getattr(adapter,'_haos_native',None)
    connector=getattr(native,'connector',None);policy=getattr(native,'policy',None)
    if not isinstance(connector,str) or not callable(policy):
        raise PermissionError('private native owner authority unavailable')
    route=dict(metadata['haos_binding']);scope=metadata['haos_scope'];thread=metadata.get('thread_id','')
    chat=str(chat)
    def current():
        try:
            if (adapter._haos_native is not native or native.connector!=connector or native.policy is not policy):
                raise PermissionError
            latest=policy()
            if not isinstance(latest,GatewayPolicy) or latest.connectors.get(connector,{}).get('platform')!=platform:
                raise PermissionError
            binding=latest.current_binding(route)
            thread_matches=binding['thread']==thread
            if platform=='google_chat':
                from .gateway_google_chat import thread_allowed
                thread_matches=thread_allowed(binding,thread)
            if (binding['connector']!=connector or binding['chat']!=chat or binding['scope']!=scope
                    or not thread_matches or 'read' not in binding['capabilities']):
                raise PermissionError
        except Exception:
            raise PermissionError('current exact owner delivery grant required') from None
    current()
    return current
