#!/usr/bin/env python3
"""Actual Tk OAuth component; Root/backend responses are explicit local fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlencode


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,google_chat_owner_setup as owner
    from haos.initial_setup_gui import Wizard
    from haos.google_chat_owner_gui import OAuthForm
    from haos.gateway import digest
    from haos.gateway_google_chat_oauth import SCOPES,REDIRECT_URI
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    public={'installed':{'client_id':'123456789-fixture.apps.googleusercontent.com','project_id':'haos-fixture','auth_uri':'https://accounts.google.com/o/oauth2/auth',
        'token_uri':'https://oauth2.googleapis.com/token','auth_provider_x509_cert_url':'https://www.googleapis.com/oauth2/v1/certs','redirect_uris':['http://localhost']}}
    client=deepcopy(public);client['installed']['client_secret']='private-OAuth-GUI-fixture'
    params={'response_type':'code','client_id':public['installed']['client_id'],'redirect_uri':REDIRECT_URI,'scope':' '.join(SCOPES),'state':'a'*43,'nonce':'b'*43,
        'access_type':'offline','prompt':'consent','include_granted_scopes':'false','code_challenge':'c'*43,'code_challenge_method':'S256'}
    session={'id':'d'*64,'authorization_url':'https://accounts.google.com/o/oauth2/auth?'+urlencode(params),'subject':'users/123','expires_at':1793450000,
        'network_requested':False,'message_sent':False,'private_verifier_or_credentials_returned':False}
    token={'id':'e'*64,'account_scope':'google-chat:'+'f'*64,'subject':'users/123','client_sha256':'1'*64,'status':'active','updated_at':1793400000,'generation':2,
        'public_client':public,'transport_status':'ready','next_attempt':0,'scopes':list(SCOPES),'scope_upgrade_required':False,'current_file_grants':1,'private_credentials_returned':False}
    token['snapshot_sha256']=digest(token)
    capsule={'id':'2'*64,'pending_id':'3'*64,'account_scope':token['account_scope'],'subject_expected':'users/123','client_sha256':'1'*64,'tokens_sha256':'4'*64,
        'state':'rejected','created_at':1793400000,'origin':'enrollment','public_client':public,'stored_bytes':128,'has_refresh_token':True,'actual_user_verified':False,
        'api_use_authorized':False,'remote_revocation_verified':False,'private_credentials_returned':False}
    capsule['snapshot_sha256']=digest(capsule)
    calls=[];connector={'id':'google'};mode={'block':False,'private':False,'unconfirmed':False};entered=threading.Event();release=threading.Event()
    def begin(selected,binding,configuration,note,**options):
        assert selected=='google' and binding=='owner' and configuration==client and note.strip() and options=={'confirmed':True}
        calls.append(('begin',selected,binding));return deepcopy(session)
    def finish(selected,chosen,returned,**options):
        assert selected=='google' and chosen==session and returned.startswith(REDIRECT_URI+'/?code=') and options=={'confirmed':True}
        calls.append(('finish',selected))
        return {'id':chosen['id'],'subject':chosen['subject'],'status':'active','generation':1,'receipt':'5'*64,'network_requested':True,'message_sent':False,'private_credentials_returned':False}
    def inspect(selected,kind):
        calls.append(('inspect',selected,kind))
        if mode['block']:entered.set();assert release.wait(5)
        result={kind:deepcopy([token] if kind=='tokens' else [capsule] if kind=='quarantines' else []),'history_truncated':False,
            'network_requested':False,'private_bytes_returned' if kind=='sessions' else 'private_credentials_returned':False}
        if mode['private']:result['access_token']='private-must-never-render'
        return result
    def withdrawal(selected,row,note,**options):
        assert options=={'confirmed':True} and selected=='google' and row in [token,capsule] and note.strip()
        kind='revoke' if row==token else 'dispose';calls.append((kind,selected,deepcopy(row)))
        result={'id':row['id'],'receipt':'6'*64,'remote_status':'uncertain' if mode['unconfirmed'] else 'confirmed',
            'remote_revocation_verified':not mode['unconfirmed'],'network_requested':True,'message_sent':False,'retry_after':0,'private_credentials_returned':False}
        result['locally_revoked' if kind=='revoke' else 'api_use_authorized']=kind=='revoke';return result
    owner.oauth_begin=begin;owner.oauth_finish=finish;owner.oauth_inspect=inspect;owner.oauth_revoke=withdrawal;owner.oauth_dispose=withdrawal
    wizard=Wizard(tk)
    for child in wizard.content.winfo_children():child.destroy()
    form=OAuthForm(wizard,wizard.content,lambda:connector['id']);form.frame.pack(fill='x');wizard.root.update();cases=[]
    def settle():
        deadline=time.monotonic()+7
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    def authorize():form.note.insert(0,'explicit nonsecret GUI review');form.confirm.set(True)
    def start():
        form.binding_var.set('owner');form.configuration.insert(0,json.dumps(client));authorize();form.buttons['begin'].invoke();settle()
    def select():form.list.selection_set(0);form.list.event_generate('<<ListboxSelect>>');wizard.root.update()
    try:
        assert form.configuration.cget('show') and form.callback.cget('show') and form.authorization.cget('state')=='disabled'
        form.buttons['begin'].invoke();settle();assert not calls
        start();assert calls==[('begin','google','owner')] and form.session==session and not form.configuration.get() and not form.confirm.get()
        url=form.authorization.get('1.0',tk.END);assert session['authorization_url'] in url and client['installed']['client_secret'] not in url
        cases.append('actual_Tk_masks_client_and_callback_requires_current_confirmation_and_displays_only_checked_PKCE_authorization_URL_after_private_client_input_is_cleared')
        before=len(calls);form.callback.insert(0,REDIRECT_URI+'/?code=fixture-code&state='+'a'*43);form.buttons['finish'].invoke();settle();assert len(calls)==before
        authorize();form.buttons['finish'].invoke();settle();assert calls[-1]==('finish','google') and not form.callback.get() and form.session is None
        assert 'bestätigt' in wizard.status.cget('text') and 'fixture-code' not in form.details.get('1.0',tk.END)
        cases.append('actual_Tk_submits_full_hidden_callback_only_after_explicit_consent_clears_code_and_session_before_async_handoff_and_renders_only_verified_receipt_status')
        start();form.callback.insert(0,'old-callback');form.binding_var.set('different');assert form.session is None and not form.callback.get()
        start();form.configuration.insert(0,'changed');assert form.session is None and not form.authorization.get('1.0',tk.END).strip()
        cases.append('actual_Tk_binding_and_client_edits_invalidate_prior_authorization_callback_and_consent')
        form.configuration.delete(0,tk.END);form.buttons['tokens'].invoke();settle();select()
        assert form.details.cget('state')=='disabled' and token['id'] in form.details.get('1.0',tk.END) and not form.confirm.get()
        before=len(calls);form.buttons['revoke'].invoke();settle();assert len(calls)==before
        authorize();form.buttons['revoke'].invoke();settle();assert calls[-1]==('revoke','google',token) and not form.rows and 'bestätigt' in wizard.status.cget('text')
        cases.append('actual_Tk_payload_free_token_status_selects_exact_generation_snapshot_requires_new_consent_and_renders_remote_confirmation_only_for_confirmed_Google_receipt')
        form.buttons['tokens'].invoke();settle();select();authorize();mode['unconfirmed']=True;form.buttons['revoke'].invoke();settle()
        assert 'nicht bestätigt' in wizard.status.cget('text');mode['unconfirmed']=False
        form.buttons['quarantines'].invoke();settle();select();authorize();form.buttons['dispose'].invoke();settle();assert calls[-1]==('dispose','google',capsule)
        cases.append('actual_Tk_distinguishes_local_block_from_uncertain_remote_revocation_and_disposes_only_explicitly_selected_nonactive_credential_capsule')
        form.buttons['tokens'].invoke();settle();select();authorize();connector['id']='changed';before=len(calls);form.buttons['revoke'].invoke();settle();assert len(calls)==before
        connector['id']='google';form.invalidate();mode['block']=True;entered.clear();release.clear();form.buttons['tokens'].invoke();assert entered.wait(2)
        connector['id']='changed';release.set();settle();assert not form.rows;connector['id']='google';mode['block']=False
        cases.append('actual_Tk_refuses_old_connector_confirmation_and_discards_late_async_status_after_connector_change')
        mode['private']=True;form.buttons['tokens'].invoke();settle();assert not form.rows and 'verworfen' in wizard.status.cget('text')
        assert 'private-must-never-render' not in form.details.get('1.0',tk.END)
        cases.append('actual_Tk_rejects_extra_private_response_fields_before_rendering_and_requires_fresh_inspection')
        Path(sys.argv[2]).write_text(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk_Wizard_async_OAuth_component':True,
            'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],'Root_OAuth_backend_calls_are_explicit_fixtures':True,
            'live_Google_account_installed_GUI_and_public_activation':False},indent=2)+'\n')
        print(json.dumps({'passed':len(cases)}))
    finally:release.set();wizard.root.destroy()


if __name__=='__main__':main()
