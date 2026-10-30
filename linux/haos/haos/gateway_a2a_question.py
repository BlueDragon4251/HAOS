"""Explicit current-question pointer in native Task/StreamResponse metadata."""
from copy import deepcopy
import sqlite3

from .gateway import Conflict


def decorate(adapter,payload):
    from plugins.platforms.a2a import protocol
    def question(task_id):
        try:context=adapter._haos_a2a_inputs.question(task_id)
        except (PermissionError,Conflict,sqlite3.OperationalError):return None
        return {'epoch':context['group_sha256'],'requestId':context['request_id'],'method':context['request_method']}
    def task(value):
        if not isinstance(value,dict) or not isinstance(value.get('id'),str) or value.get('status',{}).get('state')!=protocol.STATE_INPUT_REQUIRED:return value
        pointer=question(value['id'])
        metadata={'haosQuestion':pointer} if pointer is not None else {'haosQuestionUnavailable':True,'haosAction':'inspect-owner-console'}
        return {**value,'metadata':{**value.get('metadata',{}),**metadata}}
    result=deepcopy(payload)
    if not isinstance(result,dict):return result
    if 'result' in result:
        value=result['result']
        if not isinstance(value,dict):return result
        if 'task' in value:value['task']=task(value['task'])
        elif 'tasks' in value and isinstance(value['tasks'],list):value['tasks']=[task(item) for item in value['tasks']]
        elif isinstance(value.get('statusUpdate'),dict):
            update=value['statusUpdate']
            if update.get('status',{}).get('state')==protocol.STATE_INPUT_REQUIRED:
                pointer=question(update.get('taskId'))
                metadata={'haosQuestion':pointer} if pointer is not None else {'haosQuestionUnavailable':True,'haosAction':'inspect-owner-console'}
                update['metadata']={**update.get('metadata',{}),**metadata}
        else:result['result']=task(value)
    return result
