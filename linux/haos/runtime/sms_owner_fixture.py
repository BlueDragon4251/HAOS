"""Disposable actual-root SMS owner publication; no installed seat/service claim."""
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
    from haos.gateway_sms import credentials
    from haos.gateway_runtime import credential_redactor
    from haos.gateway import GatewayPolicy
    cases=[];config=directory/'owner-config';config.mkdir(mode=0o700)
    audit=directory/'owner-audit';canary=directory/'retained-owner-data';canary.write_text('preserve-owner-recovery')
    certificate=directory/'owner-chain.pem';certificate.write_text(tls['certificate']);certificate.chmod(0o600)
    key=directory/'owner-key.pem';key.write_text(tls['private_key']);key.chmod(0o600)
    original_load,original_persist=gateway_setup.load,gateway_setup.persist
    real_path=Path
    def audit_path(value):return audit if value=='/var/lib/haos-owner' else real_path(value)
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
        account='AC'+'a'*32;number='+12025550100';destination=account+':'+number;sender='+12025550101'
        prompts=iter([account,number,'8647',tls['public_url'],str(certificate),str(key),'0.0.0.0','PUBLIC'])
        secrets=iter(['b'*32])
        with patch('builtins.input',lambda *_args:next(prompts)),patch.object(gateway_setup.getpass,'getpass',lambda *_args:next(secrets)):
            result=gateway_setup.owner_gateway(SimpleNamespace(gateway_action='setup',connector='sms-main',platform='sms'))
        assert result['external_reachability_verified'] is False
        policy,private=original_load(config)
        assert private['connectors']['sms-main']['tls']['public_listener'] is True
        assert private['connectors']['sms-main']['tls']['bind_host']=='0.0.0.0'
        assert not policy['bindings']
        assert (config/'gateways.json').stat().st_mode&0o777==0o640
        assert (config/'gateway-credentials').stat().st_mode&0o777==0o600
        public=initial_setup.gateway_configuration()
        assert public['sms']['sms-main']=={'account_sid':account,'from_number':number,'port':8647,'public_url':tls['public_url'],'bind_host':'0.0.0.0'}
        assert 'PRIVATE KEY' not in repr(public) and 'b'*32 not in repr(public)
        cases.append('actual_cli_private_prompts_verified_public_consent_and_atomic_root_publication')
        redactor=credential_redactor(private,GatewayPolicy(policy))
        assert tls['private_key'] not in redactor.text(tls['private_key'])
        import base64
        basic=base64.b64encode((account+':'+'b'*32).encode()).decode()
        assert basic not in redactor.text(basic) and 'b'*32 not in redactor.text('b'*32)
        cases.append('actual_runtime_redactor_excludes_private_pem_and_channel_credentials')
        before=(config/'gateway-credentials').read_bytes()
        try:initial_setup.configure_sms_gateway('sms-main',account,'b'*32,number,8647,
            {**tls,'bind_host':'0.0.0.0','public_listener':False})
        except ValueError:pass
        else:raise AssertionError('public listener configured without explicit consent')
        assert (config/'gateway-credentials').read_bytes()==before
        cases.append('actual_owner_public_listener_refuses_missing_consent_without_configuration_mutation')
        for invalid_port in ['private-not-a-port','443']:
            prompts=iter([account,number,invalid_port])
            with patch('builtins.input',lambda *_args:next(prompts)),patch.object(gateway_setup.getpass,'getpass',lambda *_args:'private-input-fixture'):
                try:gateway_setup.owner_gateway(SimpleNamespace(gateway_action='setup',connector='sms-main',platform='sms'))
                except ValueError as error:assert invalid_port not in str(error)
                else:raise AssertionError('invalid CLI port accepted')
            assert (config/'gateway-credentials').read_bytes()==before
        cases.append('actual_cli_invalid_port_rejected_without_input_echo_or_credential_mutation')
        gateway_setup.owner_gateway(SimpleNamespace(gateway_action='pair',binding='owner',connector='sms-main',
            sender=sender,chat=sender,scope='',thread='',identity='personal',capabilities=['create','read']))
        cli_policy,_=original_load(config)
        assert cli_policy['bindings'][0]['scope']==destination and cli_policy['bindings'][0]['generation']
        cases.append('actual_cli_pair_derives_saved_bot_scope_and_publishes_exact_sender_grant')
        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read','pause','resume'))
        policy,private=original_load(config);epoch=policy['bindings'][0]['generation']
        assert policy['bindings'][0]['scope']==destination and policy['bindings'][0]['since']>0
        cases.append('actual_graphical_backend_derives_bot_scope_and_publishes_fresh_timed_grant')
        assert not policy['bindings'][0].get('allow_media',False)
        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'),allow_media=True)
        policy,private=original_load(config)
        assert policy['bindings'][0]['allow_media'] is True and policy['bindings'][0]['generation']!=epoch
        before=(config/'gateways.json').read_bytes()
        try:initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('read',),allow_media=True)
        except ValueError:pass
        else:raise AssertionError('media without create permission accepted')
        assert (config/'gateways.json').read_bytes()==before
        cases.append('actual_graphical_media_opt_in_persisted_and_missing_create_refused_without_mutation')
        gateway_setup.owner_gateway(SimpleNamespace(gateway_action='pair',binding='owner',connector='sms-main',
            sender=sender,chat=sender,scope='',thread='',identity='personal',capabilities=['create','read'],allow_media=True))
        policy,private=original_load(config);assert policy['bindings'][0]['allow_media'] is True
        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'))
        policy,private=original_load(config);assert not policy['bindings'][0]['allow_media']
        cases.append('actual_cli_media_opt_in_and_graphical_repair_default_withdrawal_persisted')
        from haos import speech_setup
        before=(config/'gateways.json').read_bytes()
        with patch.object(speech_setup,'status',lambda:{'enabled':False,'runtime_ready':True,'model_ready':True}):
            try:initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'),allow_voice=True)
            except PermissionError:pass
            else:raise AssertionError('voice approved before local speech configuration')
        assert (config/'gateways.json').read_bytes()==before
        with patch.object(speech_setup,'status',lambda:{'enabled':True,'runtime_ready':True,'model_ready':True}):
            initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'),allow_voice=True)
            voiced,_=original_load(config)
            assert voiced['bindings'][0]['allow_voice'] is True and voiced['bindings'][0]['allow_media'] is False
            gateway_setup.owner_gateway(SimpleNamespace(gateway_action='pair',binding='owner',connector='sms-main',
                sender=sender,chat=sender,scope='',thread='',identity='personal',capabilities=['create','read'],allow_voice=True))
            voiced,_=original_load(config);assert voiced['bindings'][0]['allow_voice'] is True
            before=(config/'gateways.json').read_bytes()
            try:initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('read',),allow_voice=True)
            except ValueError:pass
            else:raise AssertionError('voice approved without create permission')
            assert (config/'gateways.json').read_bytes()==before
        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'))
        policy,private=original_load(config);assert policy['bindings'][0]['allow_voice'] is False
        cases.append('actual_owner_gui_cli_voice_approval_requires_configured_speech_create_and_resets_on_default_repair')

        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'),allow_video=True,allow_outbound_media=True)
        public,_=original_load(config)
        assert public['bindings'][0]['allow_video'] is True and public['bindings'][0]['allow_outbound_media'] is True
        for rights,options in [(('read',),{'allow_video':True}),(('create',),{'allow_outbound_media':True})]:
            before=(config/'gateways.json').read_bytes()
            try:initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',rights,**options)
            except ValueError:pass
            else:raise AssertionError('media granted without the corresponding create/read right')
            assert (config/'gateways.json').read_bytes()==before
        cases.append('actual_owner_video_and_output_opt_ins_persist_and_require_separate_create_read_rights')
        gateway_setup.owner_gateway(SimpleNamespace(gateway_action='pair',binding='owner',connector='sms-main',
            sender=sender,chat=sender,scope='',thread='',identity='personal',capabilities=['create','read'],allow_video=True,allow_outbound_media=True))
        public,_=original_load(config);assert public['bindings'][0]['allow_video'] and public['bindings'][0]['allow_outbound_media']
        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal',('create','read'))
        public,_=original_load(config);assert not public['bindings'][0]['allow_video'] and not public['bindings'][0]['allow_outbound_media']
        cases.append('actual_cli_video_output_opt_ins_and_default_repair_withdrawal')

        for changes in [{'sender':number},{'scope':'AC'+'e'*32+':'+number},{'thread':'unapproved'}]:
            args={'sender':sender,'scope':'','thread':''};args.update(changes)
            before=(config/'gateways.json').read_bytes()
            try:initial_setup.pair_gateway_sender('other','sms-main',args['sender'],sender,'personal',scope=args['scope'],thread=args['thread'])
            except ValueError:pass
            else:raise AssertionError('invalid SMS pairing accepted')
            assert (config/'gateways.json').read_bytes()==before
        cases.append('actual_pairing_refuses_self_bot_wrong_destination_and_threads_without_mutation')
        initial_setup.configure_sms_gateway('sms-main',account,'c'*32,number,8647,tls)
        policy,private=original_load(config);assert not policy['bindings']
        cases.append('actual_credential_and_listener_rotation_withdraws_old_grants_without_data_deletion')
        initial_setup.pair_gateway_sender('owner','sms-main',sender,sender,'personal')
        policy,private=original_load(config);assert policy['bindings'][0]['generation']!=epoch
        invalid=copy.deepcopy(private);invalid['connectors']['sms-main']['from_number']='+12025550199'
        try:validate_snapshot(policy,invalid)
        except ValueError:pass
        else:raise AssertionError('mismatched credential bot destination accepted')
        cases.append('actual_repairing_renews_epoch_and_publication_rejects_cross_bot_credential_mix')
        retained=copy.deepcopy(private);retained['connectors']['sms-main']['tls']=expired_tls
        original_persist(policy,retained,config=config,gid=0)
        loaded=original_load(config)
        try:credentials(loaded[1]['connectors']['sms-main'])
        except ValueError:pass
        else:raise AssertionError('expired TLS certificate activated')
        assert initial_setup.gateway_configuration()['sms']['sms-main']['from_number']==number
        cases.append('actual_expired_pem_remains_inspectable_but_strict_activation_refuses_it')
        initial_setup.configure_sms_gateway('sms-main',account,'d'*32,number,8647,tls)
        assert credentials(original_load(config)[1]['connectors']['sms-main'])['tls']==tls
        cases.append('actual_owner_can_replace_expired_certificate_without_resetting_retained_data')
        child=os.fork()
        if child==0:
            try:
                os.setgroups([]);os.setgid(65534);os.setuid(65534)
                for action in [lambda:initial_setup.read_line_tls_file(str(key),'private_key'),initial_setup.gateway_configuration,
                        lambda:initial_setup.configure_sms_gateway('sms-main',account,'b'*32,number,8647,tls)]:
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
        initial_setup.manage_gateway('remove','sms-main')
        assert original_load(config)==({'version':1,'connectors':[],'bindings':[]},{'connectors':{}})
        assert canary.read_text()=='preserve-owner-recovery'
        rows=[json.loads(line) for line in (audit/'audit.jsonl').read_text().splitlines()]
        assert any(row['kind']=='gateway.remove' for row in rows)
        assert 'PRIVATE KEY' not in repr(rows) and 'b'*32 not in repr(rows)
        cases.append('actual_remove_preserves_owner_canary_and_audits_no_secrets')
    return cases
