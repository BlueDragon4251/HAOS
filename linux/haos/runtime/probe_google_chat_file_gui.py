#!/usr/bin/env python3
"""Actual Tk file recovery controls; privileged backend responses are fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time
import uuid


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,google_chat_owner_setup as owner
    from haos.initial_setup_gui import Wizard
    from haos.google_chat_owner_gui import FileRecoveryForm
    from haos.gateway import digest
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    def snapshot(value):return {**value,'snapshot_sha256':digest(value)}
    def file(identity,upload=False):
        return snapshot({'id':identity,'client_id':'client-'+identity[:56],'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'haos-google-file:'+identity)),
            'upload_state':'uploading' if upload else 'uploaded','state':'prepared' if upload else 'writing','receipt':'','created_at':1793430000,
            'owner_retry_generation':0,'upload_retry_generation':0,'connector':'google','account_scope':'google-chat:'+'f'*64,'binding_id':'owner',
            'binding_digest':'c'*64,'subject':'users/123','chat':'spaces/room','thread':'spaces/room/threads/thread1','delivery_id':'d'*64,
            'source_id':'spaces/room/messages/source','file_id':'e'*64,'file_sha256':'1'*64,'filename':'result-0.pdf','mime':'application/pdf',
            'proof_sha256':'2'*64,'caption_sha256':'3'*64,'caption_bytes':0,'upload_ref_sha256':'4'*64,'current_grant':True,'current_account':True,
            'source_projection_available':True,'output_available':True,'upload_retry_allowed':upload,'file_retry_allowed':not upload,
            'private_bytes_returned':False,'recipient_read_verified':False})
    write=file('a'*64);upload=file('b'*64,True)
    output=snapshot({'id':'e'*64,'delivery_id':'d'*64,'binding_id':'owner','binding_digest':'c'*64,'filename':'result-0.pdf','mime':'application/pdf',
        'size':128,'created_at':1793430000,'expected_sha256':'1'*64,'actual_sha256':'1'*64,'stored_bytes':128,'state':'retained','current_grant':False,
        'purge_allowed':True,'private_bytes_returned':False,'remote_deletion_verified':False,'other_copies_backups_and_WAL_erasure_not_claimed':True})
    connector={'id':'google'};mode={'blocked':False,'private':False,'wrong-id':False};entered=threading.Event();release=threading.Event();calls=[]
    def inspect(selected,kind):
        if mode['blocked']:entered.set();assert release.wait(5)
        result={kind:deepcopy([write,upload] if kind=='files' else [output]),'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
        if mode['private']:result[kind][0]['attachment_ref']='private-must-never-render'
        return result
    def retry(selected,row,action,note,**options):
        assert selected=='google' and note.strip() and options=={'confirmed':True,'confirmed_not_delivered':action=='retry-file'}
        assert row==(write if action=='retry-file' else upload);calls.append((action,selected,deepcopy(row)))
        return {'id':('0'*64 if mode['wrong-id'] else row['id']),'action':action,'generation':1,'receipt':'5'*64,'approval_recorded':True,
            'network_requested':False,'message_sent':False,'same_source_user_file_and_stable_ids_required':True,'late_acceptance_check_before_create_required':action=='retry-file'}
    def purge(selected,row,note,**options):
        assert selected=='google' and row==output and note.strip() and options=={'confirmed':True};calls.append(('purge',selected,deepcopy(row)))
        return {'id':row['id'],'receipt':'6'*64,'network_requested':False,'message_sent':False,'tombstones_retained':True,
            'remote_deletion_verified':False,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    owner.inspect=inspect;owner.file_retry=retry;owner.output_purge=purge
    wizard=Wizard(tk)
    for child in wizard.content.winfo_children():child.destroy()
    form=FileRecoveryForm(wizard,wizard.content,lambda:connector['id']);form.frame.pack(fill='x');wizard.root.update();cases=[]
    def settle():
        deadline=time.monotonic()+7
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    def load(kind):form.buttons[kind].invoke();settle()
    def select(index):form.list.selection_clear(0,tk.END);form.list.selection_set(index);form.list.event_generate('<<ListboxSelect>>');wizard.root.update()
    def consent():form.note.insert(0,'explicit independent fixture review');form.confirm.set(True)
    try:
        load('files');assert form.list.size()==2;select(0)
        assert form.details.cget('state')=='disabled' and write['id'] in form.details.get('1.0',tk.END) and not form.confirm.get()
        before=len(calls);form.buttons['retry'].invoke();settle();assert len(calls)==before
        consent();form.buttons['retry'].invoke();settle();assert len(calls)==before
        form.not_delivered.set(True);form.buttons['retry'].invoke();settle()
        assert calls[-1]==('retry-file','google',write) and not form.rows and not form.confirm.get()
        cases.append('actual_Tk_read_only_metadata_requires_current_snapshot_note_explicit_consent_and_independent_non_delivery_before_freezing_exact_file_retry_for_Root_backend')
        load('files');select(0);consent();form.not_delivered.set(True);select(1)
        assert not form.confirm.get() and not form.not_delivered.get() and not form.note.get()
        consent();form.buttons['upload'].invoke();settle();assert calls[-1]==('retry-upload','google',upload)
        cases.append('actual_Tk_row_change_clears_both_consents_and_upload_retry_freezes_only_eligible_pre_publication_upload_snapshot')
        load('files');select(0);consent();before=len(calls);form.buttons['upload'].invoke();settle();assert len(calls)==before
        select(1);consent();form.not_delivered.set(True);form.buttons['retry'].invoke();settle();assert len(calls)==before
        cases.append('actual_Tk_refuses_cross_phase_upload_and_create_permissions_even_with_user_confirmation')
        load('outputs');select(0);consent();form.buttons['purge'].invoke();settle()
        assert calls[-1]==('purge','google',output) and 'keine entfernte' in wizard.status.cget('text')
        cases.append('actual_Tk_local_output_disposal_requires_exact_withdrawn_snapshot_and_never_claims_remote_deletion')
        load('files');select(0);consent();form.not_delivered.set(True);connector['id']='another';before=len(calls)
        form.buttons['retry'].invoke();settle();assert len(calls)==before;connector['id']='google';form.clear()
        mode['blocked']=True;entered.clear();release.clear();form.buttons['files'].invoke();assert entered.wait(2);connector['id']='another';release.set();settle()
        assert not form.rows;connector['id']='google';mode['blocked']=False
        cases.append('actual_async_Tk_refuses_changed_connector_consent_and_discards_delayed_old_account_inventory')
        mode['private']=True;load('files');assert not form.rows and 'verworfen' in wizard.status.cget('text')
        assert 'private-must-never-render' not in form.details.get('1.0',tk.END);mode['private']=False
        cases.append('actual_Tk_closed_schema_discards_private_upload_reference_before_rendering_details')
        load('files');select(0);consent();form.not_delivered.set(True);mode['wrong-id']=True;form.buttons['retry'].invoke();settle()
        assert not form.rows and 'verworfen' in wizard.status.cget('text')
        cases.append('actual_Tk_rejects_well_shaped_decision_receipt_for_a_different_selected_file_identity')
        Path(sys.argv[2]).write_text(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk_file_recovery_component':True,
            'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],'privileged_Root_backend_responses_are_explicit_fixtures':True,
            'live_Google_account_installed_GUI_public_activation_or_real_delivery':False},indent=2)+'\n')
        print(json.dumps({'passed':len(cases)}))
    finally:release.set();wizard.root.destroy()


if __name__=='__main__':main()
