"""Task-to-wire identity bridge, usable only during verified parent dispatch."""
from contextlib import contextmanager
from contextvars import ContextVar

_DISPATCH=ContextVar('haos_private_a2a_parent_dispatch',default=None)


@contextmanager
def dispatch(adapter,event,proof,*,parent_event=None):
    actual,_=adapter._haos_a2a_source(event)
    if actual!=proof:raise PermissionError('native A2A event changed retained parent proof')
    parent=event if parent_event is None else parent_event
    if (parent.source is not event.source or parent.message_id!=event.message_id or parent.text!=event.text
            or parent.internal or parent.raw_message is not None):
        raise PermissionError('mapped A2A parent event changed its sealed native source')
    token=_DISPATCH.set((adapter,parent,proof,event))
    try:yield
    finally:_DISPATCH.reset(token)


def envelope(event):
    state=_DISPATCH.get()
    if state is None or state[1] is not event:raise PermissionError('native A2A wire identity requires exact active parent dispatch')
    adapter,_,proof,original=state;actual,_=adapter._haos_a2a_source(original)
    if actual!=proof:raise PermissionError('native A2A parent source changed')
    # The native task ID is generated locally. The immutable wire client ID is
    # the controller/relay deduplication key; the task index proves their link.
    return adapter._haos_a2a_envelope(proof)
