"""Bounded actual SDK history recovery after the original owner grant boundary."""
import asyncio
import logging
import time

from .gateway import digest, Conflict

DISCORD_EPOCH = 1420070400000


def boundary(binding):
    since = binding.get('since')
    if type(since) is not int or since < DISCORD_EPOCH or not binding.get('generation'):
        return None
    # Exclude the entire millisecond containing the grant, including messages
    # that preceded its sub-millisecond owner publication.
    value = ((since-DISCORD_EPOCH) << 22) | ((1 << 22)-1)
    return value if 0 < value < 2**64 else None


def cursor(inbox, binding):
    inbox.db.execute('''CREATE TABLE IF NOT EXISTS discord_history (
        binding_digest TEXT PRIMARY KEY, cursor TEXT NOT NULL, updated_at REAL NOT NULL)''')
    floor = boundary(binding)
    if floor is None: return None
    row = inbox.db.execute('SELECT cursor FROM discord_history WHERE binding_digest=?',(digest(binding),)).fetchone()
    if row:
        value = row['cursor']
        if not isinstance(value,str) or not value.isascii() or not value.isdigit() or len(value)>20 or not 0<int(value)<2**64:
            raise ValueError('invalid durable Discord history cursor')
        floor = max(floor,int(value))
    return floor


def record_status(adapter, kind):
    if kind not in {'ready','permission-denied','rate-limited','transport-unavailable','storage-unavailable','invalid-source'}:
        raise ValueError('invalid Discord history status')
    key = getattr(adapter,'_haos_history_binding',None)
    if key is None:return
    db=adapter._haos_native.inbox.db
    db.execute('''CREATE TABLE IF NOT EXISTS discord_history_status (
        binding_digest TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at REAL NOT NULL)''')
    db.execute('''INSERT INTO discord_history_status(binding_digest,status,updated_at) VALUES(?,?,?)
        ON CONFLICT(binding_digest) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at''',
        (key,kind,time.time()))


async def recover_one(adapter, current_policy, connector):
    import discord
    from . import gateway_discord
    native = adapter._haos_native
    policy = current_policy()
    bindings = [item for item in policy.bindings.values() if item['connector']==connector and boundary(item) is not None]
    if not bindings: return 0
    index = getattr(adapter,'_haos_history_index',0) % len(bindings)
    adapter._haos_history_index = index+1
    binding = bindings[index]
    adapter._haos_history_binding = digest(binding)
    route = {'binding_id':binding['id'],'binding_digest':digest(binding)}
    before = cursor(native.inbox,binding)
    channel = await adapter._resolve_channel(binding['chat'])
    guild = getattr(channel,'guild',None)
    if (not isinstance(channel,(discord.TextChannel,discord.Thread,discord.DMChannel))
            or str(channel.id)!=binding['chat'] or (str(guild.id) if guild else '')!=binding['scope']
            or (str(channel.id) if isinstance(channel,discord.Thread) else '')!=binding['thread']):
        raise PermissionError('Discord history target differs from the owner grant')
    # The installed SDK owns auth, HTTP encoding and rate-limit handling.
    payloads = await adapter._client.http.logs_from(channel.id,100,after=before)
    if not isinstance(payloads,list) or len(payloads)>100:
        raise ValueError('invalid Discord history page')
    ordered = []
    for payload in payloads:
        identity = payload.get('id') if isinstance(payload,dict) else None
        if (not isinstance(identity,str) or not identity.isascii() or not identity.isdigit()
                or len(identity)>20 or not before<int(identity)<2**64
                or ((int(identity)>>22)+DISCORD_EPOCH)/1000 > time.time()+300
                or str(payload.get('channel_id'))!=binding['chat']
                or payload.get('guild_id',binding['scope'])!=binding['scope']):
            raise ValueError('Discord history page changed its source or cursor')
        ordered.append((int(identity),payload))
    if len({item[0] for item in ordered})!=len(ordered):
        raise ValueError('duplicate Discord history page identity')
    admitted = 0
    for identity,payload in sorted(ordered,key=lambda item:item[0]):
        current = current_policy();current.current_binding(route)
        decoded = dict(payload)
        if guild is not None: decoded.setdefault('guild_id',str(guild.id))
        envelope = gateway_discord.capture_envelope(adapter,adapter._client,decoded,current,connector)
        if envelope is not None:
            matched = current.authorize(connector,envelope)
            floor = boundary(matched)
            if floor is not None and identity>floor and native.inbox.find_discord(connector,str(identity)) is None:
                native.inbox.admit(current,connector,envelope,decoded,
                    received_at=((identity>>22)+DISCORD_EPOCH)/1000)
                admitted += 1
        # Commit/definitive refusal precedes cursor advancement. Any failure
        # leaves this ID recoverable; retained raw rows make retry idempotent.
        native.inbox.db.execute('''INSERT INTO discord_history(binding_digest,cursor,updated_at) VALUES(?,?,?)
            ON CONFLICT(binding_digest) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at''',
            (digest(binding),str(identity),time.time()))
    record_status(adapter,'ready')
    return admitted


async def maintain(adapter, stop, current_policy, connector):
    while not stop.is_set():
        try:
            if adapter.is_connected:
                await asyncio.wait_for(recover_one(adapter,current_policy,connector),15)
        except Exception as error:
            logging.warning('Discord history recovery deferred: %s',type(error).__name__)
            import discord
            import sqlite3
            kind = ('permission-denied' if isinstance(error,(discord.Forbidden,discord.NotFound,PermissionError)) else
                'rate-limited' if isinstance(error,discord.RateLimited) else
                'storage-unavailable' if isinstance(error,(sqlite3.Error,Conflict)) else
                'invalid-source' if isinstance(error,ValueError) else 'transport-unavailable')
            try:record_status(adapter,kind)
            except (sqlite3.Error,OSError):logging.warning('Discord recovery status could not be persisted')
        try: await asyncio.wait_for(stop.wait(),2)
        except TimeoutError: pass
