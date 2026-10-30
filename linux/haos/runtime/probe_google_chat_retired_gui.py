#!/usr/bin/env python3
"""Actual Tk historical recovery controls; Root responses are explicit fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,google_chat_retired_setup as owner,google_chat_retired_gui as gui
    from haos.gateway import digest
    from haos.gateway_google_chat_identity import account_scope
    from haos.gateway_google_chat_oauth import SCOPES
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    gui.current_policy=lambda:None
    def snap(row):return {**row,'snapshot_sha256':digest(row)}
    identity={'version':1,'project_id':'haos-fixture','service_account_email':'gateway@haos-fixture.iam.gserviceaccount.com','bot_user':'users/999'}
    scope=account_scope(identity);account=snap({'profile':'google-chat-'+digest(scope),'identity':identity,'identity_sha256':digest(identity)})
    public={'installed':{'client_id':'123456789-fixture.apps.googleusercontent.com','project_id':'haos-fixture',
        'auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','redirect_uris':['http://localhost']}}
    token=snap({'id':'a'*64,'account_scope':scope,'subject':'users/123','client_sha256':'b'*64,'status':'active','updated_at':1793400000,
        'generation':2,'public_client':public,'transport_status':'ready','next_attempt':0,'scopes':list(SCOPES),
        'scope_upgrade_required':False,'current_file_grants':0,'private_credentials_returned':False})
    capsule=snap({'id':'c'*64,'pending_id':'d'*64,'account_scope':scope,'subject_expected':'users/123','client_sha256':'b'*64,
        'tokens_sha256':'e'*64,'state':'rejected','created_at':1793400000,'origin':'enrollment','public_client':public,'stored_bytes':128,
        'has_refresh_token':True,'actual_user_verified':False,'api_use_authorized':False,'remote_revocation_verified':False,'private_credentials_returned':False})
    output=snap({'id':'f'*64,'delivery_id':'1'*64,'binding_id':'owner','binding_digest':'2'*64,'filename':'result-0.pdf','mime':'application/pdf',
        'size':128,'created_at':1793430000,'expected_sha256':'3'*64,'actual_sha256':'3'*64,'stored_bytes':128,'state':'retained',
        'current_grant':False,'purge_allowed':True,'private_bytes_returned':False,'remote_deletion_verified':False,
        'other_copies_backups_and_WAL_erasure_not_claimed':True})
    owned=snap({**{k:v for k,v in output.items() if k!='snapshot_sha256'},'connector':'google','account_scope':scope,'ownership_sha256':'4'*64})
    mode={'private':False,'block':False,'wrong':False,'active':False};entered=threading.Event();release=threading.Event();calls=[]
    def profiles():return {'profiles':[account],'identity_missing':['google-chat-'+'0'*64],'history_truncated':False,'network_requested':False,'private_credentials_returned':False}
    def inspect(kind,profile=None):
        if mode['block']:entered.set();assert release.wait(5)
        row=deepcopy({'tokens':token,'quarantines':capsule,'outputs':owned,'unassociated-outputs':output}[kind])
        if mode['active'] and kind in {'outputs','unassociated-outputs'}:
            row.update(current_grant=True,purge_allowed=False);row=snap({k:v for k,v in row.items() if k!='snapshot_sha256'})
        if mode['private']:row['private_payload']='must-never-render'
        result={'outputs' if kind=='unassociated-outputs' else kind:[row],'history_truncated':False,'network_requested':False,
            'private_credentials_returned' if kind in {'tokens','quarantines'} else 'private_bytes_returned':False}
        return ({'result':result,'active_authorization_returned':False,'app_association_inferred':False} if kind=='unassociated-outputs'
            else {'account':account,'result':result,'active_authorization_returned':False})
    def decide(kind,app,row,note,**options):
        assert options=={'confirmed':True} and note.strip();calls.append((kind,deepcopy(app),deepcopy(row)))
        result={'id':'0'*64 if mode['wrong'] else row['id'],'receipt':'5'*64,'network_requested':False,'message_sent':False}
        if kind in {'outputs','unassociated-outputs'}:result.update(tombstones_retained=True,remote_deletion_verified=False,other_copies_backups_and_WAL_erasure_not_claimed=True)
        else:
            result.update(network_requested=True,remote_status='confirmed',remote_revocation_verified=True,retry_after=0,private_credentials_returned=False)
            if kind=='tokens':result['locally_revoked']=True
            else:result['api_use_authorized']=False
        return ({'result':result,'active_authorization_returned':False,'app_association_inferred':False} if app is None
            else {'account':app,'result':result,'active_authorization_returned':False})
    owner.profiles=profiles
    owner.tokens=lambda profile:inspect('tokens',profile);owner.quarantines=lambda profile:inspect('quarantines',profile)
    owner.outputs=lambda profile:inspect('outputs',profile);owner.unassociated_outputs=lambda:inspect('unassociated-outputs')
    owner.revoke=lambda app,row,note,**kw:decide('tokens',app,row,note,**kw)
    owner.dispose=lambda app,row,note,**kw:decide('quarantines',app,row,note,**kw)
    owner.purge_output=lambda app,row,note,**kw:decide('outputs',app,row,note,**kw)
    owner.purge_unassociated_output=lambda row,note,**kw:decide('unassociated-outputs',None,row,note,**kw)
    wizard=Wizard(tk)
    for child in wizard.content.winfo_children():child.destroy()
    form=gui.HistoricalRecoveryForm(wizard,wizard.content);form.frame.pack(fill='x');wizard.root.update();cases=[]
    def settle():
        deadline=time.monotonic()+7
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    def load(kind):form.buttons[kind].invoke();settle()
    def select(index=0):form.list.selection_clear(0,tk.END);form.list.selection_set(index);form.list.event_generate('<<ListboxSelect>>');wizard.root.update()
    def consent():form.note.insert(0,'explicit historical fixture inspection');form.confirm.set(True)
    try:
        load('profiles');assert form.list.size()==2 and 'unbekannt' in form.list.get(1);select()
        assert form.profile_var.get()==account['profile'] and not form.rows
        cases.append('actual_Tk_known_and_unknown_app_profiles_are_distinct_and_selection_requires_fresh_metadata')
        for kind,button in [('tokens','withdraw'),('quarantines','withdraw'),('outputs','purge'),('unassociated-outputs','purge')]:
            load(kind);select();assert form.details.cget('state')=='disabled'
            before=len(calls);form.buttons[button].invoke();settle();assert len(calls)==before
            consent();form.buttons[button].invoke();settle()
            assert len(calls)==before+1 and calls[-1][0]==kind and not form.rows and not form.confirm.get()
            assert 'verworfen' not in wizard.status.cget('text'),wizard.status.cget('text')
            cases.append('actual_Tk_'+kind+'_requires_explicit_snapshot_note_and_consent_then_validates_decision_receipt')
        mode['active']=True;load('outputs');select();consent();before=len(calls);form.buttons['purge'].invoke();settle();assert len(calls)==before
        mode['active']=False;cases.append('actual_Tk_active_original_grant_blocks_local_byte_disposal')
        load('tokens');select();consent();form.profile_var.set('google-chat-'+'0'*64);form.buttons['withdraw'].invoke();settle()
        assert len(calls)==before and not form.rows and not form.confirm.get();form.profile_var.set(account['profile'])
        cases.append('actual_Tk_profile_change_clears_old_snapshot_and_consent_before_any_withdrawal')
        mode['block']=True;entered.clear();release.clear();form.buttons['tokens'].invoke();assert entered.wait(2)
        form.profile_var.set('google-chat-'+'0'*64);release.set();settle();assert not form.rows
        mode['block']=False;form.profile_var.set(account['profile']);cases.append('actual_async_Tk_discards_slow_metadata_after_profile_change')
        mode['private']=True;load('outputs');assert not form.rows and 'must-never-render' not in form.details.get('1.0',tk.END)
        mode['private']=False;cases.append('actual_Tk_closed_metadata_schema_rejects_private_payload_before_rendering')
        load('tokens');select();consent();mode['wrong']=True;form.buttons['withdraw'].invoke();settle()
        assert not form.rows and 'verworfen' in wizard.status.cget('text');cases.append('actual_Tk_rejects_decision_receipt_for_a_different_token')
        wizard.show('google-chat-history');wizard.root.update()
        def labels(widget):
            result=[widget.cget('text')] if isinstance(widget,(tk.Label,tk.Button,tk.Checkbutton)) else []
            return result+[text for child in widget.winfo_children() for text in labels(child)]
        assert 'Zur Gateway-Verwaltung' in labels(wizard.content)
        assert 'Unzugeordnete lokale Ausgaben prüfen' in labels(wizard.content)
        cases.append('actual_Wizard_history_page_constructs_real_recovery_controls_and_return_navigation_without_active_connector')
        Path(sys.argv[2]).write_text(json.dumps({'passed':len(cases),'cases':cases,'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'actual_Tk_component_async_queue_and_read_only_details':True,'privileged_backend_responses_are_explicit_fixtures':True,
            'live_Google_account_installed_GUI_or_public_activation':False},indent=2)+'\n')
        print(json.dumps({'passed':len(cases)}))
    finally:release.set();wizard.root.destroy()


if __name__=='__main__':main()
