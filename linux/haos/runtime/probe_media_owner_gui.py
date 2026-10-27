#!/usr/bin/env python3
"""Actual Tk media controls with a real disposable ledger; authority tested separately."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup
    from haos.gateway import GatewayEngine,GatewayPolicy
    from haos.gateway_media import describe
    from haos.store import MissionStore
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True
    initial_setup.setup_in_progress=lambda:False
    cases=[]
    with tempfile.TemporaryDirectory(prefix='haos-media-gui-') as directory:
        path=Path(directory)/'missions.db';store=MissionStore(path);engine=GatewayEngine(store)
        policy=GatewayPolicy({'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
            'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,
            'thread':'','identity':'personal','capabilities':['create','read'],'allow_media':True,'generation':'b'*64,'since':1}]})
        event={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
            'message_id':'c'*64,'is_bot':False,'text':'Inspect retained document'}
        payload=b'private retained GUI document';upload=engine.media.begin(policy,{'connector':'line','envelope':event,'descriptor':describe(payload,'document')})
        engine.media.chunk(policy,{'id':upload['id'],'offset':0,'data':base64.b64encode(payload).decode()});store.close()
        calls=[]
        def inventory():
            ledger=MissionStore(path)
            try:return GatewayEngine(ledger).media.inventory()
            finally:ledger.close()
        def purge(identity,note,confirmed=False):
            calls.append((identity,note,confirmed))
            ledger=MissionStore(path)
            try:return GatewayEngine(ledger).media.purge([identity],'owner:1000',note,confirmed=confirmed)
            finally:ledger.close()
        initial_setup.gateway_media_inventory=inventory;initial_setup.purge_gateway_media=purge
        wizard=Wizard(tk)
        def widgets(parent):
            for child in parent.winfo_children():yield child;yield from widgets(child)
        def button(text):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text')==text)
        def settle():
            end=time.time()+5
            while wizard.running and time.time()<end:wizard.root.update();time.sleep(.01)
            wizard.root.update();assert not wizard.running
        try:
            wizard.show('gateway-media');wizard.root.update()
            button('Dienste stoppen und Medien prüfen').invoke();settle()
            labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
            assert 'Gespeichert: '+str(len(payload))+' Byte' in labels and 'Bereinigung zulässig' in labels
            assert payload.decode() not in labels
            cases.append('actual_tk_inspection_shows_private_ledger_usage_without_payload')
            field=next(w for w in widgets(wizard.content) if isinstance(w,tk.Entry));field.insert(0,'Inspected staged document')
            check=next(w for w in widgets(wizard.content) if isinstance(w,tk.Checkbutton))
            assert not wizard.root.getvar(check.cget('variable'))
            button('Ausgewählte Medien bereinigen').invoke();settle()
            assert calls[-1][2] is False and inventory()['stored_bytes']==len(payload)
            cases.append('actual_tk_default_unchecked_purge_refuses_without_deleting_bytes')
            check.invoke()
            menu=next(w for w in widgets(wizard.content) if isinstance(w,tk.OptionMenu))
            wizard.root.setvar(menu.cget('textvariable'),upload['id'])
            assert not wizard.root.getvar(check.cget('variable'))
            cases.append('actual_tk_selection_change_clears_pending_deletion_confirmation')
            check.invoke();button('Ausgewählte Medien bereinigen').invoke();settle()
            assert calls[-1]==(upload['id'],'Inspected staged document',True)
            assert inventory()['stored_bytes']==0 and inventory()['uploads'][0]['state']=='purged'
            button('Dienste stoppen und Medien prüfen').invoke();settle()
            before=len(calls);button('Ausgewählte Medien bereinigen').invoke();settle();assert len(calls)==before
            cases.append('actual_tk_explicit_purge_keeps_tombstone_and_blocks_already_purged_selection')
        finally:wizard.root.destroy()
    result={'passed':len(cases),'cases':cases,'actual_tk_and_sqlite':True,
        'service_and_root_authority_are_separate_tests':True,'installed_or_live_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
