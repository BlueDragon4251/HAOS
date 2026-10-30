#!/usr/bin/env python3
"""Actual Tk Buzz controls; privileged handoffs are explicit component fixtures."""
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup,buzz_owner_setup as owner
    from haos.initial_setup_gui import Wizard
    from haos.gateway import digest
    from haos.gateway_buzz import credentials
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    value={'private_key':format(1,'064x'),'public_key':'79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798',
        'relay_url':'https://buzz.fixture.invalid','channels':['01234567-89ab-4cde-8012-3456789abcde'],'attachment_origins':[]}
    initial_setup.gateway_configuration=lambda:{'connectors':[{'id':'buzz-main','platform':'buzz'}],'bindings':[],
        'buzz':{'buzz-main':owner.public(value)}}
    saves=[];pairs=[];inspections=[];decisions=[];auths=[];source_decisions=[];cases=[]
    def save(connector,account,private_key,auth_tag,**options):
        saves.append((connector,dict(account),private_key,auth_tag,dict(options)))
        selected={**account,'private_key':value['private_key'] if options['keep_key'] else private_key}
        if auth_tag:selected['auth_tag']=auth_tag
        checked=credentials(selected);value.clear();value.update(checked)
        return {'configured':True}
    owner.save_account=save
    initial_setup.pair_gateway_sender=lambda *args,**kwargs:pairs.append((args,kwargs)) or {'paired':True}
    row={'id':'a'*64,'delivery_id':'b'*64,'name':'result-0.pdf','source_sha256':'c'*64,'state':'uploading',
        'source_bytes':42,'stored_bytes':0,'created_at':1793332800,'current_grant':False,'purge_allowed':True,
        'retry_approvals':0,'metadata_sha256':'d'*64,'private_bytes_returned':False}
    row['snapshot_sha256']=digest(row)
    profile='buzz-'+'f'*64
    source_row={'profile':profile,'event_id':'1'*64,'state':'retained','snapshot_sha256':'2'*64}
    history_row={'profile':profile,'channel':value['channels'][0],'state':'grant-changed','snapshot_sha256':'3'*64}
    def inspect(connector,action='account',**options):
        inspections.append((connector,action))
        if action=='source-profiles':return {'profiles':[profile]}
        if action in {'sources','history'}:
            assert options=={'profile':profile}
            return {action:[source_row if action=='sources' else history_row]}
        if action=='outputs':return {'outputs':[row],'history_truncated':False,'network_requested':False,'private_bytes_returned':False}
        return {'error':'authentication-refused'}
    owner.inspect=inspect
    def decide(connector,item,action,note,**options):
        if options.get('confirmed') is not True or not note.strip():raise PermissionError('fixture explicit inspection required')
        decisions.append((connector,dict(item),action,note,dict(options)))
        return {'id':item['id'],'action':action,'receipt':'e'*64,'network_requested':False,'message_sent':False,
            'tombstones_retained':True,'other_copies_backups_and_WAL_erasure_not_claimed':True}
    owner.recover_upload=decide
    def auth(connector,note,**options):
        if options.get('confirmed') is not True:raise PermissionError('fixture explicit auth check required')
        auths.append((connector,note,dict(options)))
        return {'connector':connector,'authentication_blocks_cleared':1,'network_requested':False,'message_sent':False}
    owner.retry_auth=auth
    def recover_source(connector,item,action,note,**options):
        if options.get('confirmed') is not True or not note.strip():raise PermissionError('explicit source review required')
        source_decisions.append((connector,dict(item),action,note,dict(options)))
        return {'network_requested':False,'message_sent':False}
    owner.recover_source=recover_source
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def field(prefix,cls=tk.Entry):
        label=next(w for w in widgets(wizard.content) if isinstance(w,tk.Label) and w.cget('text').startswith(prefix))
        siblings=label.master.winfo_children();return next(w for w in siblings[siblings.index(label)+1:] if isinstance(w,cls))
    def button(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text').startswith(prefix))
    def box(prefix):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton) and w.cget('text').startswith(prefix))
    def selected(widget):return bool(wizard.root.getboolean(wizard.root.getvar(widget.cget('variable'))))
    def fill(prefix,text):
        entry=field(prefix);entry.delete(0,tk.END);entry.insert(0,text);wizard.root.update();return entry
    def choose(prefix,text):
        menu=field(prefix,tk.OptionMenu);wizard.root.setvar(menu.cget('textvariable'),text);wizard.root.update()
    def settle():
        deadline=time.monotonic()+5
        while wizard.running and time.monotonic()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateways');wizard.root.update();choose('Plattform','buzz')
        key=field('Dedizierter privater Nostr-Schlüssel')
        assert key.winfo_viewable() and not field('Bot-Token').winfo_viewable() and not key.get() and str(key.cget('state'))=='disabled'
        assert field('Bereich ·').get()==owner.public(value)['scope'] and str(field('Bereich ·').cget('state'))=='disabled'
        cases.append('actual_Tk_Buzz_account_fields_replace_generic_token_and_only_public_metadata_returns_without_saved_key_readback')
        box('Gespeicherten privaten Schlüssel').invoke();fill('Dedizierter privater Nostr-Schlüssel',value['private_key'])
        assert key.cget('show')=='•';box('Nur hier neu eingegebene private Werte anzeigen').invoke();assert key.cget('show')==''
        button('Gateway sicher anlegen').invoke();settle()
        assert saves[-1][0]=='buzz-main' and saves[-1][2]==format(1,'064x') and saves[-1][4]=={'keep_key':False,'keep_auth':False}
        assert not key.get() and key.cget('show')=='•'
        cases.append('actual_Tk_save_passes_exact_masked_private_entry_and_canonical_public_account_to_owner_handoff_fixture_then_clears_transient_secret')
        fill('Absender-ID','2'*64);fill('Chat-ID',value['channels'][0]);fill('Thread-ID','a'*64)
        box('Buzz-Bilder und Dokumente').invoke();assert selected(box('Buzz-Bilder und Dokumente'))
        fill('Thread-ID','b'*64);assert not selected(box('Buzz-Bilder und Dokumente'))
        box('Buzz-Bilder und Dokumente').invoke();button('Absender mit ausgewählten Rechten freigeben').invoke();settle()
        assert pairs[-1][0][1:4]==('buzz-main','2'*64,value['channels'][0])
        assert pairs[-1][1]['thread']=='b'*64 and pairs[-1][1]['scope']==owner.public(value)['scope']
        assert pairs[-1][1]['allow_media'] is True and pairs[-1][1]['allow_voice'] is False and pairs[-1][1]['require_mention'] is True
        assert not selected(box('Buzz-Bilder und Dokumente'))
        cases.append('actual_Tk_exact_pubkey_channel_thread_pairing_uses_saved_scope_and_separate_media_flags_then_resets_consent_on_route_change_and_submit')
        button('Gespeichertes Buzz-Konto').invoke();settle();assert inspections[-1]==('buzz-main','account')
        assert 'Relay lehnt die Anmeldung ab' in wizard.status.cget('text')
        button('Lokale Auth-Sperre freigeben').invoke();settle();assert not auths
        box('Nach Prüfung von Relay').invoke();button('Lokale Auth-Sperre freigeben').invoke();settle()
        assert auths[-1][0]=='buzz-main' and auths[-1][2]=={'confirmed':True} and not selected(box('Nach Prüfung von Relay'))
        cases.append('actual_Tk_account_check_shows_finite_auth_error_and_recheck_requires_explicit_confirmation_without_send')
        button('Private Upload-Belege laden').invoke();settle()
        listing=next(w for w in widgets(wizard.content) if isinstance(w,tk.Listbox) and w.size()==1)
        listing.selection_set(0);listing.event_generate('<<ListboxSelect>>');wizard.root.update()
        button('Upload-Nutzdaten nach Freigabeentzug').invoke();settle();assert not decisions
        fill('Nicht geheime Prüfbegründung','fixture inspected withdrawn output bytes')
        box('Genau diesen aktuellen Prüfbeleg').invoke();button('Upload-Nutzdaten nach Freigabeentzug').invoke();settle()
        assert decisions[-1][0:3]==('buzz-main',row,'purge-upload') and decisions[-1][4]=={'confirmed':True}
        assert not selected(box('Genau diesen aktuellen Prüfbeleg')) and not field('Nicht geheime Prüfbegründung').get()
        cases.append('actual_Tk_upload_disposal_freezes_exact_selected_snapshot_and_explicit_note_confirmation_then_clears_review_without_returning_private_payload')
        button('Erhaltene Buzz-Profile anzeigen').invoke();settle()
        listing.selection_set(0);listing.event_generate('<<ListboxSelect>>');wizard.root.update()
        assert field('Speicherprofil').get()==profile and listing.size()==0
        cases.append('actual_Tk_retained_profile_selection_clears_previous_snapshot_and_requires_new_source_inspection')
        for kind,load,action,label,expected in [
            ('sources','Private Original-Belege laden','purge-source','Original-Nutzdaten nach Freigabeentzug',source_row),
            ('history','Verlaufsprüfbelege laden','reset-history','Verlauf für geänderte exakte Freigabe',history_row)]:
            button(load).invoke();settle();listing.selection_set(0);listing.event_generate('<<ListboxSelect>>');wizard.root.update()
            before=len(source_decisions);button(label).invoke();settle();assert len(source_decisions)==before
            fill('Nicht geheime Prüfbegründung','explicit fixture source or history review')
            box('Genau diesen aktuellen Prüfbeleg').invoke();button(label).invoke();settle()
            assert source_decisions[-1][:3]==('buzz-main',expected,action)
            assert source_decisions[-1][4]=={'confirmed':True} and listing.size()==0
            assert not selected(box('Genau diesen aktuellen Prüfbeleg')) and not field('Nicht geheime Prüfbegründung').get()
            cases.append('actual_Tk_'+kind+'_recovery_freezes_exact_snapshot_requires_note_and_confirmation_then_clears_selection')
        choose('Plattform','telegram')
        assert not key.winfo_viewable() and not key.get() and field('Bot-Token').winfo_viewable()
        cases.append('actual_Tk_platform_switch_hides_Buzz_controls_and_clears_transient_private_material')
        Path(sys.argv[2]).write_text(json.dumps({'passed':len(cases),'cases':cases,'actual_Tk':True,
            'screen':[wizard.root.winfo_screenwidth(),wizard.root.winfo_screenheight()],
            'privileged_owner_handoffs_are_fixtures':True,'live_account_delivery_installed_GUI_or_public_acceptance':False},indent=2)+'\n')
        print(json.dumps({'passed':len(cases)}))
    finally:wizard.root.destroy()


if __name__=='__main__':main()
