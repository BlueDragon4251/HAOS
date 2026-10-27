"""Disposable actual-root LINE owner publication; no installed seat/service claim."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def exercise(directory,tls,expired_tls):
    assert os.geteuid()==0 and os.environ.get('HAOS_DISPOSABLE_LINE_OWNER')=='1'
    from haos import initial_setup,gateway_setup,owner
    from haos.gateway_publication import validate_snapshot
    from haos.gateway_line_profile import credentials
    from haos.gateway_runtime import credential_redactor
    from haos.gateway import GatewayPolicy
    cases=[];config=directory/'owner-config';config.mkdir(mode=0o700)
    audit=directory/'owner-audit';canary=directory/'retained-owner-data';canary.write_text('preserve-owner-recovery')
    certificate=directory/'owner-chain.pem';certificate.write_text(tls['certificate']);certificate.chmod(0o600)
    key=directory/'owner-key.pem';key.write_text(tls['private_key']);key.chmod(0o600)
    original_load,original_persist=gateway_setup.load,gateway_setup.persist
    real_path=Path
    def audit_path(value):
        if value=='/var/lib/haos-owner':return audit
        if value=='/var/lib/haos-control/missions.db':return directory/'media-missions.db'
        return real_path(value)
    with patch.object(gateway_setup,'load',lambda *args:original_load(config)), \
            patch.object(gateway_setup,'persist',lambda policy,private:original_persist(policy,private,config=config,gid=0)), \
            patch.object(gateway_setup,'stopped_gateway',lambda:None), \
            patch.object(initial_setup,'quiesce_for_setup',lambda **kwargs:None),patch.object(owner,'Path',audit_path):
        assert initial_setup.read_line_tls_file(str(certificate),'certificate')==tls['certificate']
        assert initial_setup.read_line_tls_file(str(key),'private_key')==tls['private_key']
        cases.append('actual_root_private_single_link_pem_descriptor_reads')
        for kind,path in [('certificate',certificate),('private_key',key)]:
            for attack in ['world-readable','symlink','hardlink','non-pem','oversized']:
                bad=directory/(kind+'-'+attack)
                if attack=='symlink':bad.symlink_to(path)
                elif attack=='hardlink':os.link(path,bad)
                else:
                    bad.write_bytes(path.read_bytes() if attack=='world-readable' else b'x'*(16385 if attack=='oversized' else 8))
                    bad.chmod(0o644 if attack=='world-readable' else 0o600)
                try:initial_setup.read_line_tls_file(str(bad),kind)
                except (OSError,ValueError,PermissionError):pass
                else:raise AssertionError('unsafe PEM '+kind+' '+attack)
                if attack=='hardlink':bad.unlink()
                cases.append('actual_pem_'+kind+'_'+attack+'_refused')
        destination='U'+'d'*32;sender='U'+'a'*32
        prompts=iter([destination,'8646',tls['public_url'],str(certificate),str(key),'0.0.0.0','PUBLIC'])
        secrets=iter(['a'*32,'private-owner-line-access'])
        with patch('builtins.input',lambda *_args:next(prompts)),patch.object(gateway_setup.getpass,'getpass',lambda *_args:next(secrets)):
            result=gateway_setup.owner_gateway(SimpleNamespace(gateway_action='setup',connector='line-main',platform='line'))
        assert result['external_reachability_verified'] is False
        policy,private=original_load(config)
        assert private['connectors']['line-main']['tls']['public_listener'] is True
        assert private['connectors']['line-main']['tls']['bind_host']=='0.0.0.0'
        assert not policy['bindings']
        assert (config/'gateways.json').stat().st_mode&0o777==0o640
        assert (config/'gateway-credentials').stat().st_mode&0o777==0o600
        public=initial_setup.gateway_configuration()
        assert public['line']['line-main']=={'destination':destination,'port':8646,'public_url':tls['public_url'],'bind_host':'0.0.0.0'}
        assert 'PRIVATE KEY' not in repr(public) and 'private-owner-line-access' not in repr(public)
        cases.append('actual_cli_private_prompts_verified_public_consent_and_atomic_root_publication')
        redactor=credential_redactor(private,GatewayPolicy(policy))
        assert tls['private_key'] not in redactor.text(tls['private_key'])
        cases.append('actual_runtime_redactor_excludes_private_pem_and_channel_credentials')
        before=(config/'gateway-credentials').read_bytes()
        try:initial_setup.configure_line_gateway('line-main','a'*32,'private-owner-line-access',destination,8646,
            {**tls,'bind_host':'0.0.0.0','public_listener':False})
        except ValueError:pass
        else:raise AssertionError('public listener configured without explicit consent')
        assert (config/'gateway-credentials').read_bytes()==before
        cases.append('actual_owner_public_listener_refuses_missing_consent_without_configuration_mutation')
        for invalid_port in ['private-not-a-port','443']:
            prompts=iter([destination,invalid_port])
            with patch('builtins.input',lambda *_args:next(prompts)),patch.object(gateway_setup.getpass,'getpass',lambda *_args:'private-input-fixture'):
                try:gateway_setup.owner_gateway(SimpleNamespace(gateway_action='setup',connector='line-main',platform='line'))
                except ValueError as error:assert invalid_port not in str(error)
                else:raise AssertionError('invalid CLI port accepted')
            assert (config/'gateway-credentials').read_bytes()==before
        cases.append('actual_cli_invalid_port_rejected_without_input_echo_or_credential_mutation')
        gateway_setup.owner_gateway(SimpleNamespace(gateway_action='pair',binding='owner',connector='line-main',
            sender=sender,chat=sender,scope='',thread='',identity='personal',capabilities=['create','read']))
        cli_policy,_=original_load(config)
        assert cli_policy['bindings'][0]['scope']==destination and cli_policy['bindings'][0]['generation']
        cases.append('actual_cli_pair_derives_saved_bot_scope_and_publishes_exact_sender_grant')
        initial_setup.pair_gateway_sender('owner','line-main',sender,'C'+'b'*32,'personal',('create','read','pause','resume'))
        policy,private=original_load(config);epoch=policy['bindings'][0]['generation']
        assert policy['bindings'][0]['scope']==destination and policy['bindings'][0]['since']>0
        cases.append('actual_graphical_backend_derives_bot_scope_and_publishes_fresh_timed_grant')
        assert not policy['bindings'][0].get('allow_media',False)
        initial_setup.pair_gateway_sender('owner','line-main',sender,'C'+'b'*32,'personal',('create','read'),allow_media=True)
        policy,private=original_load(config)
        assert policy['bindings'][0]['allow_media'] is True and policy['bindings'][0]['generation']!=epoch
        before=(config/'gateways.json').read_bytes()
        try:initial_setup.pair_gateway_sender('owner','line-main',sender,'C'+'b'*32,'personal',('read',),allow_media=True)
        except ValueError:pass
        else:raise AssertionError('media without create permission accepted')
        assert (config/'gateways.json').read_bytes()==before
        cases.append('actual_graphical_media_opt_in_persisted_and_missing_create_refused_without_mutation')
        gateway_setup.owner_gateway(SimpleNamespace(gateway_action='pair',binding='owner',connector='line-main',
            sender=sender,chat=sender,scope='',thread='',identity='personal',capabilities=['create','read'],allow_media=True))
        policy,private=original_load(config);assert policy['bindings'][0]['allow_media'] is True
        initial_setup.pair_gateway_sender('owner','line-main',sender,'C'+'b'*32,'personal',('create','read'))
        policy,private=original_load(config);assert not policy['bindings'][0]['allow_media']
        cases.append('actual_cli_media_opt_in_and_graphical_repair_default_withdrawal_persisted')
        from haos.store import MissionStore
        from haos.gateway import GatewayEngine
        from haos.gateway_media import describe
        import base64
        ledger=MissionStore(directory/'media-missions.db');engine=GatewayEngine(ledger)
        media_policy=copy.deepcopy(policy);media_policy['bindings'][0]['allow_media']=True
        media_event={'platform':'line','sender':sender,'chat':'C'+'b'*32,'scope':destination,'thread':'',
            'message_id':'c'*64,'is_bot':False,'text':'Inspect retained document'}
        payload=b'private owner inspected document'
        upload=engine.media.begin(GatewayPolicy(media_policy),{'connector':'line-main','envelope':media_event,'descriptor':describe(payload,'document')})
        engine.media.chunk(GatewayPolicy(media_policy),{'id':upload['id'],'offset':0,'data':base64.b64encode(payload).decode()});ledger.close()
        with patch.object(owner,'stopped',lambda:None):
            assert owner.manage_media('list')['stored_bytes']==len(payload)
            try:owner.manage_media('purge',[upload['id']],'Inspected retained payload')
            except PermissionError:pass
            else:raise AssertionError('root media purge accepted without explicit confirmation')
            assert owner.manage_media('list')['stored_bytes']==len(payload)
            assert owner.manage_media('purge',[upload['id']],'Inspected retained payload',confirmed=True)['removed_payload_bytes']==len(payload)
            assert owner.manage_media('list')['uploads'][0]['state']=='purged'
        assert canary.read_text()=='preserve-owner-recovery'
        cases.append('actual_root_shared_cli_gui_media_inspection_and_explicit_purge_keep_owner_canary_and_tombstone')


        for changes in [{'sender':destination},{'scope':'U'+'e'*32},{'thread':'unapproved'}]:
            args={'sender':sender,'scope':'','thread':''};args.update(changes)
            before=(config/'gateways.json').read_bytes()
            try:initial_setup.pair_gateway_sender('other','line-main',args['sender'],'C'+'b'*32,'personal',scope=args['scope'],thread=args['thread'])
            except ValueError:pass
            else:raise AssertionError('invalid LINE pairing accepted')
            assert (config/'gateways.json').read_bytes()==before
        cases.append('actual_pairing_refuses_self_bot_wrong_destination_and_threads_without_mutation')
        initial_setup.configure_line_gateway('line-main','a'*32,'private-owner-line-access-rotated',destination,8646,tls)
        policy,private=original_load(config);assert not policy['bindings']
        cases.append('actual_credential_and_listener_rotation_withdraws_old_grants_without_data_deletion')
        initial_setup.pair_gateway_sender('owner','line-main',sender,sender,'personal')
        policy,private=original_load(config);assert policy['bindings'][0]['generation']!=epoch
        invalid=copy.deepcopy(private);invalid['connectors']['line-main']['destination']='U'+'e'*32
        try:validate_snapshot(policy,invalid)
        except ValueError:pass
        else:raise AssertionError('mismatched credential bot destination accepted')
        cases.append('actual_repairing_renews_epoch_and_publication_rejects_cross_bot_credential_mix')
        retained=copy.deepcopy(private);retained['connectors']['line-main']['tls']=expired_tls
        original_persist(policy,retained,config=config,gid=0)
        loaded=original_load(config)
        try:credentials(loaded[1]['connectors']['line-main'])
        except ValueError:pass
        else:raise AssertionError('expired TLS certificate activated')
        assert initial_setup.gateway_configuration()['line']['line-main']['destination']==destination
        cases.append('actual_expired_pem_remains_inspectable_but_strict_activation_refuses_it')
        initial_setup.configure_line_gateway('line-main','a'*32,'private-owner-line-access-renewed',destination,8646,tls)
        assert credentials(original_load(config)[1]['connectors']['line-main'])['tls']==tls
        cases.append('actual_owner_can_replace_expired_certificate_without_resetting_retained_data')
        child=os.fork()
        if child==0:
            try:
                os.setgroups([]);os.setgid(65534);os.setuid(65534)
                for action in [lambda:initial_setup.read_line_tls_file(str(key),'private_key'),initial_setup.gateway_configuration,
                        lambda:initial_setup.configure_line_gateway('line-main','a'*32,'private-owner-line-access',destination,8646,tls)]:
                    try:action()
                    except PermissionError:continue
                    raise AssertionError('foreign UID gained owner authority')
                try:(config/'gateway-credentials').read_bytes()
                except PermissionError:pass
                else:raise AssertionError('foreign UID read private credential store')
                os._exit(0)
            except BaseException:os._exit(3)
        _,status=os.waitpid(child,0);assert os.waitstatus_to_exitcode(status)==0
        cases.append('actual_foreign_uid_cannot_read_pem_credentials_or_invoke_owner_mutations')
        initial_setup.manage_gateway('remove','line-main')
        assert original_load(config)==({'version':1,'connectors':[],'bindings':[]},{'connectors':{}})
        assert canary.read_text()=='preserve-owner-recovery'
        rows=[json.loads(line) for line in (audit/'audit.jsonl').read_text().splitlines()]
        assert any(row['kind']=='gateway.remove' for row in rows)
        assert 'PRIVATE KEY' not in repr(rows) and 'private-owner-line-access' not in repr(rows)
        cases.append('actual_remove_preserves_owner_canary_and_audits_no_secrets')
    return cases
