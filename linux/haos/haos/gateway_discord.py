"""Exact owner-scoped Discord admission, independent of native env/role grants."""
from contextvars import ContextVar
from types import SimpleNamespace
import logging

_CURRENT = ContextVar('haos_discord_owner_source', default=None)


def source_envelope(adapter, message):
    thread, chat = adapter._thread_id_and_chat_for_channel(message.channel)
    guild = getattr(message, 'guild', None)
    source = adapter.build_source(chat_id=chat, chat_type='thread' if thread else 'group' if guild else 'dm',
        user_id=str(message.author.id), thread_id=thread, guild_id=str(guild.id) if guild else None,
        is_bot=bool(message.author.bot), message_id=str(message.id))
    return {'platform': 'discord', 'sender': str(source.user_id), 'chat': str(source.chat_id),
        'scope': str(source.scope_id or ''), 'thread': str(source.thread_id or ''),
        'message_id': str(message.id), 'is_bot': source.is_bot, 'text': message.content}


async def dispatch(adapter, original, message, *args, **kwargs):
    handler = getattr(adapter, '_haos_source_authorizer', None)
    if handler is None:
        return False
    envelope = source_envelope(adapter, message)
    if handler(envelope) is not True:
        logging.warning('Discord source refused by HAOS owner policy')
        return False
    reference = getattr(message, 'reference', None)
    referenced = getattr(reference, 'resolved', None)
    snapshots = getattr(message, 'message_snapshots', ()) or ()
    if (message.attachments or getattr(referenced, 'attachments', None)
            or any(getattr(item, 'attachments', None) for item in snapshots)):
        logging.warning('Discord media refused: no approved HAOS media broker configured')
        return False
    state = SimpleNamespace(adapter=adapter, envelope=envelope, accepted=False)
    token = _CURRENT.set(state)
    try:
        result = await original(adapter, message, *args, **kwargs)
        if state.accepted:
            # Native claim=True records before dispatch. Only HAOS's committed
            # admission may consume this cache key; a failed write can retry.
            adapter._dedup.is_duplicate(str(message.id))
        return result
    finally:
        _CURRENT.reset(token)


def allowed(adapter, user_id, author=None, *, guild=None, is_dm=False, channel_ids=None):
    state = _CURRENT.get()
    if state is None or state.adapter is not adapter:
        return False
    source = state.envelope
    return (source['sender'] == str(user_id) and source['is_bot'] is False
        and source['scope'] == (str(guild.id) if guild else '')
        and (is_dm and source['scope'] == '' or channel_ids is not None and source['chat'] in channel_ids))


def admitted(adapter, accepted):
    state = _CURRENT.get()
    if state is not None and state.adapter is adapter:
        state.accepted = accepted is True
