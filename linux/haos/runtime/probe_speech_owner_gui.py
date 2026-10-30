#!/usr/bin/env python3
"""Actual Tk speech owner actions; OS publication/worker authority proved separately."""
import copy
import json
from pathlib import Path
import sys
import time


def main():
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status=lambda:{'owner':True,'recovery':True,'complete':True,'pending':False}
    initial_setup.normal_user_ready=lambda:True;initial_setup.setup_in_progress=lambda:False
    initial_setup.provider_state=lambda:{'routes':[],'default':None,'fallbacks':{}}
    states={'enabled':False,'runtime_ready':False,'model_ready':False,'model':'tiny','services':{
        'haos-speech.socket':{'LoadState':'loaded','ActiveState':'inactive'},
        'haos-speech.service':{'LoadState':'loaded','ActiveState':'inactive'}}}
    changes=[];cases=[]
    initial_setup.gateway_speech_status=lambda:copy.deepcopy(states)
    def configure(value):
        assert type(value) is bool;changes.append(value)
        states['enabled']=value;states['model_ready']=True
        states['services']['haos-speech.socket']['ActiveState']='active' if value else 'inactive'
        return copy.deepcopy(states)
    initial_setup.configure_gateway_speech=configure
    wizard=Wizard(tk)
    def widgets(parent):
        for child in parent.winfo_children():yield child;yield from widgets(child)
    def button(text):return next(w for w in widgets(wizard.content) if isinstance(w,tk.Button) and w.cget('text')==text)
    def settle():
        deadline=time.time()+5
        while wizard.running and time.time()<deadline:wizard.root.update();time.sleep(.01)
        wizard.root.update();assert not wizard.running
    try:
        wizard.show('gateway-speech');wizard.root.update()
        activate=button('Modell laden und lokalen Dienst aktivieren')
        assert str(activate.cget('state'))=='disabled'
        button('Spracherkennungsstatus prüfen').invoke();settle()
        assert str(activate.cget('state'))=='disabled' and not changes
        cases.append('actual_tk_missing_pinned_runtime_prevents_activation_without_backend_mutation')
        states['runtime_ready']=True
        button('Spracherkennungsstatus prüfen').invoke();settle()
        assert str(activate.cget('state'))=='normal'
        activate.invoke();settle();assert changes==[True]
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert '75 MiB' in labels and 'Modell vollständig geprüft' in labels and 'haos-speech.socket: active' in labels
        assert 'getrennte Freigabe' in labels and 'separater Absenderfreigabe' in labels
        cases.append('actual_tk_explicit_model_download_activation_reaches_owner_backend_and_preserves_separate_sender_approval')
        button('Spracherkennungsdienst stoppen und deaktivieren').invoke();settle()
        assert changes==[True,False] and states['model_ready'] is True
        labels=' '.join(w.cget('text') for w in widgets(wizard.content) if isinstance(w,tk.Label))
        assert 'Modell vollständig geprüft' in labels and 'Lokaler Dienst nicht aktiviert' in labels
        assert 'ersetzt diesen Rechteentzug nicht' in labels
        cases.append('actual_tk_deactivation_keeps_model_and_explains_sender_grant_revocation_is_separate')
        assert str(button('Spracherkennungsdienst stoppen und deaktivieren').cget('state'))=='disabled'
    finally:wizard.root.destroy()
    result={'passed':len(cases),'cases':cases,'actual_tk':True,'backend_handoff_only_os_authority_is_separate':True,
        'line_voice_or_installed_acceptance':False}
    if len(sys.argv)>2:Path(sys.argv[2]).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
