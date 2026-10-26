#!/usr/bin/env python3
"""Actual pinned IRC codec and durable admission, no server/account/TLS claim."""
import asyncio
import copy
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from types import SimpleNamespace


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.gateway import GatewayPolicy
    from haos.gateway_irc_ingress import PreparedIRCPolicy,REQUIRED_CAPS,snapshot,envelope,capture,dispatch_stored,install
    from haos.gateway_ingress import durable_adapter
    from haos.gateway_raw import NativeInbox
    from haos.gateway_relay import RelayInbox
    from haos.gateway_runtime import adapter_envelope
    from haos.redaction import Redactor
    cases=[]
    async def exercise(directory):
        os.environ['HERMES_HOME']=str(directory/'hermes');os.environ['HERMES_SAFE_MODE']='1'
        from gateway.config import PlatformConfig
        from plugins.platforms.irc.adapter import IRCAdapter,_parse_irc_message
        config={'version':1,'connectors':[{'id':'irc','platform':'irc'}],'bindings':[{
            'id':'owner','connector':'irc','sender':'owner-account','chat':'#haos','scope':'irc.fixture.invalid:6697',
            'thread':'','identity':'owner','capabilities':['create','read'],'generation':'a'*64,'since':int((time.time()-10)*1000)}]}
        policy=lambda:PreparedIRCPolicy(config)
        def denied(action):
            try:action()
            except (ValueError,PermissionError):return
            raise AssertionError('unapproved IRC authority admitted')
        denied(lambda:GatewayPolicy(config));cases.append('public_owner_policy_still_refuses_unfinished_irc_transport')
        native=NativeInbox(directory/'native.db',Redactor());relay=RelayInbox(directory/'relay.db',Redactor())
        adapter=install(durable_adapter(IRCAdapter(PlatformConfig(enabled=True,extra={
            'server':'irc.fixture.invalid','nickname':'haos-bot','channel':'#haos','use_tls':True}))))
        adapter._haos_native=SimpleNamespace(connector='irc',policy=policy,inbox=native)
        accepted=[];fail=[False]
        def receive(event):
            source=adapter_envelope(event,'irc')
            with sqlite3.connect(directory/'native.db') as observer:
                assert observer.execute('SELECT state FROM native_inbox WHERE message_id=?',(source['message_id'],)).fetchone()==('processing',)
            if fail[0]:raise ConnectionError('disposable local admission interruption')
            relay.admit(policy(),'irc',source);accepted.append(source);return True
        adapter.set_durable_message_handler(receive)
        def frame(identity='message_1',account='owner-account',nick='ChangingNick',stamp=None):
            stamp=stamp or datetime.now(timezone.utc).isoformat()
            return f'@account={account};time={stamp};msgid={identity} :{nick}!user@host PRIVMSG #haos :haos-bot: hello owner'
        authority=snapshot(policy(),'irc','irc.fixture.invalid:6697');raw=frame()
        assert _parse_irc_message(raw)['command'].startswith('@account=')
        cases.append('actual_pinned_parser_does_not_decode_ircv3_tags_without_reviewed_boundary')
        key=capture(adapter,raw,authority,REQUIRED_CAPS)
        assert await dispatch_stored(adapter,key)
        assert accepted[0]['sender']=='owner-account' and accepted[0]['text']=='hello owner'
        assert accepted[0]['scope']=='irc.fixture.invalid:6697' and len(accepted[0]['message_id'])==64
        cases.append('actual_native_codec_after_observable_commit_uses_server_account_not_nickname')
        assert not await dispatch_stored(adapter,key) and len(accepted)==1
        cases.append('same_server_message_identity_cannot_repeat_mission_admission')
        raw=frame('message_2',nick='EntirelyDifferentNick')
        assert await dispatch_stored(adapter,capture(adapter,raw,authority,REQUIRED_CAPS))
        assert accepted[-1]['sender']=='owner-account'
        cases.append('nick_change_does_not_change_authenticated_account_route')
        for name,bad in [
            ('nickname_impersonation_without_account',frame('bad','*',nick='owner-account')),
            ('client_only_account_tag',frame('bad').replace('@account=','@+account=')),
            ('duplicate_account_tag',frame('bad').replace('@account=','@account=attacker;account=')),
            ('missing_server_time',frame('bad').replace('time=','client-time=')),
            ('missing_stable_server_identity',frame('bad').replace('msgid=','client-msgid=')),
            ('naive_timestamp',frame('bad',stamp='2026-10-26T10:00:00')),
            ('escaped_account',frame('bad',account='owner\\saccount')),
            ('wrong_command',frame('bad').replace(' PRIVMSG ',' NOTICE ')),
            ('direct_message_not_channel',frame('bad').replace(' #haos ',' haos-bot ')),
            ('unaddressed_channel_text',frame('bad').replace(':haos-bot: hello',':hello')),
            ('ctcp_not_mission',frame('bad').replace('hello owner','\x01VERSION\x01')),
            ('line_injection',frame('bad')+'\r\nPRIVMSG #other :bad'),
            ('oversized_frame',frame('bad')+'x'*4096),
            ('server_prefix_not_person',frame('bad').replace('ChangingNick!user@host','irc.fixture.invalid')),
        ]:
            assert envelope(adapter,bad,authority['server'],REQUIRED_CAPS) is None,name
            cases.append(name)
        for capability in REQUIRED_CAPS:
            denied(lambda capability=capability:capture(adapter,frame('missing'),authority,REQUIRED_CAPS-{capability}))
            cases.append('unnegotiated_'+capability+'_denied')
        denied(lambda:capture(adapter,frame('unknown','unknown-account',nick='owner-account'),authority,REQUIRED_CAPS))
        cases.append('known_nickname_cannot_authorize_unknown_server_account')
        denied(lambda:capture(adapter,frame('foreign'),{**authority,'server':'other.fixture.invalid:6697'},REQUIRED_CAPS))
        cases.append('authenticated_account_on_different_server_is_not_same_owner')
        for label,seconds in [('before_owner_grant',-30),('future_original_time',301)]:
            bad=frame(label,stamp=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat())
            denied(lambda:capture(adapter,bad,authority,REQUIRED_CAPS));cases.append(label)
        for callback,args in [(adapter._handle_line,(raw,)),(adapter._handle_privmsg,('ChangingNick','#haos','haos-bot: hello'))]:
            try:await callback(*args)
            except PermissionError:pass
            else:raise AssertionError('direct IRC native callback bypassed retained account')
        cases.append('direct_native_callbacks_cannot_bypass_retained_account')
        key=capture(adapter,frame('retained'),authority,REQUIRED_CAPS);fail[0]=True
        try:await dispatch_stored(adapter,key)
        except ConnectionError:pass
        else:raise AssertionError('local failed admission accepted')
        native.close();native=NativeInbox(directory/'native.db',Redactor());adapter._haos_native.inbox=native
        native.db.execute('UPDATE native_inbox SET next_attempt=0 WHERE id=?',(key,))
        fail[0]=False;assert await dispatch_stored(adapter,key)
        cases.append('actual_sqlite_reopen_replays_failed_local_admission_without_network')
        from haos.gateway_runtime import credential_redactor
        from haos.gateway_irc_transport import sasl_chunks
        private={'server_password':'private-server-fixture','sasl_username':'bot-account','sasl_password':'private-sasl-fixture-'*32}
        chunks=[x for x in sasl_chunks(private) if x!='+']
        aliases=[private['server_password'],private['sasl_password'],''.join(chunks),*chunks]
        redactor=credential_redactor({'connectors':{'irc':private}},policy())
        native.redactor=redactor;relay.redactor=redactor
        reflected=frame('private_aliases').replace('hello owner','echo '+' '.join(aliases))
        key=capture(adapter,reflected,authority,REQUIRED_CAPS)
        pending=native.db.execute('SELECT payload,envelope FROM native_inbox WHERE id=?',(key,)).fetchone()
        assert all(alias not in str(tuple(pending)) for alias in aliases)
        assert await dispatch_stored(adapter,key)
        assert all(alias not in json.dumps(accepted[-1]) for alias in aliases)
        assert '[REDACTED]' in accepted[-1]['text']
        cases.append('actual_native_decode_and_durable_relay_never_receive_reflected_private_password_or_sasl_wire_aliases')
        config['bindings'][0]['sender']='Owner-Account'
        mixed_authority=snapshot(policy(),'irc','irc.fixture.invalid:6697')
        mixed=frame('mixed_case',account='Owner-Account').replace(' #haos ',' #HAOS ')
        assert await dispatch_stored(adapter,capture(adapter,mixed,mixed_authority,REQUIRED_CAPS))
        assert accepted[-1]['sender']=='Owner-Account' and accepted[-1]['chat']=='#haos'
        denied(lambda:capture(adapter,frame('wrong_account_case',account='owner-account'),mixed_authority,REQUIRED_CAPS))
        cases.append('actual_native_codec_canonicalizes_channel_case_but_preserves_exact_authenticated_account_case')
        config['bindings'][0].update(sender='owner-account',chat='&haos')
        local_authority=snapshot(policy(),'irc','irc.fixture.invalid:6697')
        local=frame('local_channel').replace(' #haos ',' &HAOS ')
        assert await dispatch_stored(adapter,capture(adapter,local,local_authority,REQUIRED_CAPS))
        assert accepted[-1]['chat']=='&haos'
        cases.append('actual_native_local_channel_codec_requires_exact_canonical_owner_channel')
        config['bindings'][0]['chat']='#haos'
        key=capture(adapter,frame('withdrawn'),authority,REQUIRED_CAPS);config['bindings']=[]
        assert not await dispatch_stored(adapter,key)
        assert native.db.execute('SELECT state FROM native_inbox WHERE id=?',(key,)).fetchone()[0]=='revoked'
        cases.append('owner_withdrawal_blocks_retained_native_event')
        native.close();relay.close()
    with tempfile.TemporaryDirectory(prefix='haos-irc-ingress-') as value:asyncio.run(exercise(Path(value)))
    receipt={'passed':len(cases),'cases':cases,'actual_pinned_native_irc_codec_and_sqlite':True,
        'public_gateway_enabled':False,'network_requested':False,'tls_or_capability_negotiation_accepted':False,
        'live_account_or_installed_acceptance':False}
    Path(sys.argv[2]).write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))


if __name__=='__main__':main()
