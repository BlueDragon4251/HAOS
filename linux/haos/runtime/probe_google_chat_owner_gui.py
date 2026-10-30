#!/usr/bin/env python3
"""Real Tk recovery component; privileged backend calls are explicit fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,google_chat_owner_setup as owner
    from haos.initial_setup_gui import Wizard
    from haos.google_chat_owner_gui import RecoveryForm
    from haos.gateway import digest
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    profile='google-chat-'+'a'*64
    def snapshot(value):return {**value,'snapshot_sha256':digest(value)}
    source=snapshot({'id':'b'*64,'connector':'google','message_id':'spaces/room/messages/source','binding_id':'owner','binding_digest':'c'*64,
        'created_at':1793358000,'admitted_receipt':'d'*64,'profile':profile,'source_sha256':'e'*64,'actual_sha256':'e'*64,'stored_bytes':128,
        'proof_sha256':'f'*64,'current_grant':False,'purge_allowed':True,'state':'retained','authentication_reverified':False,'private_bytes_returned':False})
    parts=[{'id':'1'*64,'part':0,'state':'confirmed','receipt':'spaces/room/messages/receipt','body_sha256':'2'*64,'body_bytes':128,'retry_generation':0},
        {'id':'3'*64,'part':1,'state':'writing','receipt':None,'body_sha256':'4'*64,'body_bytes':128,'retry_generation':0}]
    group=snapshot({'id':'5'*64,'connector':'google','binding_id':'owner','binding_digest':'c'*64,'source_id':'spaces/room/messages/source',
        'source_sha256':'e'*64,'context_sha256':'6'*64,'content_sha256':'7'*64,'state':'writing','expected_parts':2,'confirmed_parts':1,'receipt':None,
        'current_account':True,'current_grant':True,'source_projection_available':True,'parts':parts,'private_bytes_returned':False,'recipient_read_verified':False})
    connector={'id':'google'};calls=[];requests=[];mode={'block':False,'private':False};entered=threading.Event();release=threading.Event()
    def inventory(selected,kind,**options):
        requests.append((selected,kind,options))
        if mode['block']:entered.set();assert release.wait(5)
        result={'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
        if kind=='source-profiles':result['profiles']=[profile]
        elif kind=='sources':result.update(profile=profile,sources=[deepcopy(source)])
        else:result['outgoing']=[deepcopy(group)]
        if mode['private']:result['body']='private fixture must not render'
        return result
    def reply(selected,row,part,note,**options):
        assert options=={'confirmed':True,'confirmed_not_delivered':True} and row==group and part==parts[1]['id'] and note.strip()
        calls.append(('retry',selected,deepcopy(row),part,note))
        return {'id':row['id'],'part_id':part,'receipt':'8'*64,'retry_generation':1,'private_retry_approved':True,
            'stable_client_and_request_id_reuse_required':True,'network_requested':False,'message_sent':False}
    def purge(selected,row,note,**options):
        assert options=={'confirmed':True} and row==source and note.strip();calls.append(('purge',selected,deepcopy(row),note))
        return {'id':row['id'],'receipt':'9'*64,'network_requested':False,'message_sent':False,'tombstones_retained':True,
            'other_copies_backups_and_WAL_erasure_not_claimed':True}
    def auth(selected,note,**options):
        assert options=={'confirmed':True} and note.strip();calls.append(('auth',selected,note))
        return {'connector':selected,'authentication_blocks_cleared':1,'receipt':'a'*64,'network_requested':False,'message_sent':False}
    owner.inspect=inventory;owner.approve_reply=reply;owner.purge_source=purge;owner.retry_auth=auth
    wizard=Wizard(tk);cases=[]
    for child in wizard.content.winfo_children():child.destroy()
    form=RecoveryForm(wizard,wizard.content,lambda:connector['id']);form.frame.pack(fill='x');wizard.root.update()
    def settle():
        deadline=time.monotonic()+7
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    def select(index):
        form.list.selection_clear(0,tk.END);form.list.selection_set(index);form.list.event_generate('<<ListboxSelect>>');wizard.root.update()
    def note(value):form.note.delete(0,tk.END);form.note.insert(0,value)
    def load(kind):form.buttons[kind].invoke();settle()
    try:
        load('outgoing');assert form.list.size()==2;select(1)
        assert form.details.cget('state')=='disabled' and parts[1]['id'] in form.details.get('1.0',tk.END)
        assert '"body"' not in form.details.get('1.0',tk.END) and form.frame.winfo_viewable()
        cases.append('actual_Tk_reply_parts_show_payload_free_exact_group_and_part_hashes_with_read_only_details')
        before=len(calls);form.buttons['retry'].invoke();settle();assert len(calls)==before
        note('fixture review');form.confirm.set(True);form.buttons['retry'].invoke();settle();assert len(calls)==before
        form.not_delivered.set(True);select(0);assert not form.confirm.get() and not form.not_delivered.get() and not form.note.get()
        note('confirmed part');form.confirm.set(True);form.not_delivered.set(True);form.buttons['retry'].invoke();settle();assert len(calls)==before
        cases.append('actual_Tk_blocks_missing_confirmations_and_confirmed_sibling_retry_and_row_selection_resets_note_and_both_consents')
        select(1);note('independent non-delivery fixture');form.confirm.set(True);form.not_delivered.set(True);form.buttons['retry'].invoke();settle()
        assert calls[-1][:4]==('retry','google',group,parts[1]['id']) and form.list.size()==0 and not form.confirm.get() and not form.note.get()
        cases.append('actual_Tk_freezes_exact_uncertain_part_snapshot_and_both_consents_for_backend_then_clears_after_audited_decision')
        load('profiles');select(0);assert form.profile_var.get()==profile and form.list.size()==0
        load('sources');assert requests[-1]==('google','sources',{'profile':profile});select(0)
        note('withdrawn source fixture');form.confirm.set(True);form.buttons['purge'].invoke();settle()
        assert calls[-1][:3]==('purge','google',source) and form.list.size()==0
        cases.append('actual_Tk_historical_profile_selection_requires_fresh_source_inspection_and_disposal_freezes_exact_withdrawn_snapshot')
        load('outgoing');select(1);note('old connector');form.confirm.set(True);form.not_delivered.set(True);connector['id']='another'
        before=len(calls);form.buttons['retry'].invoke();settle();assert len(calls)==before
        form.buttons['auth'].invoke();settle();assert len(calls)==before
        cases.append('actual_Tk_connector_switch_invalidates_loaded_reply_selection_and_previous_auth_confirmation_before_any_backend_decision')
        connector['id']='google';form.clear();note('checked account fixture');form.confirm.set(True);form.buttons['auth'].invoke();settle()
        assert calls[-1]==('auth','google','checked account fixture') and not form.confirm.get()
        cases.append('actual_Tk_auth_recheck_uses_explicit_current_connector_confirmation_and_nonsecret_note_without_send_action')
        mode['block']=True;entered.clear();release.clear();form.buttons['outgoing'].invoke()
        assert entered.wait(2);connector['id']='another';release.set();settle();assert form.list.size()==0
        mode['block']=False;connector['id']='google'
        cases.append('actual_async_Tk_discards_slow_inspection_response_after_connector_change_instead_of_reusing_old_snapshots')
        mode['private']=True;load('outgoing');assert form.list.size()==0 and 'verworfen' in wizard.status.cget('text')
        assert 'private fixture must not render' not in form.details.get('1.0',tk.END)
        mode['private']=False
        cases.append('actual_Tk_closed_response_schema_discards_unexpected_payload_fields_before_rendering_details')
        load('outgoing');select(1);note('profile changed');form.confirm.set(True);form.profile_var.set('');wizard.root.update()
        assert form.list.size()==0 and not form.confirm.get() and not form.note.get()
        cases.append('actual_Tk_profile_edits_clear_previously_selected_snapshot_and_Owner_confirmation')
        Path(sys.argv[2]).write_text(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk_Wizard_async_queue_and_recovery_component':True,
            'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'privileged_owner_backend_calls_are_explicit_fixtures':True,'real_UID_backend_tested_separately':True,
            'full_account_GUI_public_activation_live_Google_or_installed_GUI_acceptance':False},indent=2)+'\n')
        print(json.dumps({'passed':len(cases)}))
    finally:release.set();wizard.root.destroy()


if __name__=='__main__':main()
