#!/usr/bin/env python3
"""Actual Tk/async recovery controls; privileged responses are explicit fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import threading
import time


def main():
    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    import tkinter as tk
    from haos import initial_setup, photon_owner_gui as gui, photon_owner_setup as owner
    from haos.gateway import digest
    from haos.initial_setup_gui import Wizard
    initial_setup.account_status = lambda: {'owner': True, 'recovery': True, 'complete': True, 'pending': False}
    initial_setup.normal_user_ready = lambda: True; initial_setup.setup_in_progress = lambda: False
    profile = 'photon-' + 'b' * 64
    def snap(row): return {**row, 'snapshot_sha256': digest(row)}
    row = snap({'id': 'a' * 64, 'connector': 'phone', 'message_id': 'spc-fixture', 'binding_id': 'phone-owner',
        'binding_digest': 'c' * 64, 'created_at': 1793430000, 'admitted_receipt': '', 'profile': profile,
        'source_sha256': 'd' * 64, 'normalized_sha256': '', 'proof_sha256': 'e' * 64, 'actual_sha256': 'd' * 64,
        'stored_bytes': 512, 'current_grant': False, 'purge_allowed': True, 'state': 'retained',
        'authentication_reverified': False, 'private_bytes_returned': False})
    mode = {'active': False, 'private': False, 'slow': False, 'wrong': False, 'foreign': False}
    entered = threading.Event(); release = threading.Event(); calls = []
    def wait():
        if mode['slow']: entered.set(); assert release.wait(5)
    def status(connector):
        wait(); return {'result': {'connector': 'other' if mode['foreign'] else connector, 'credential_scope': 'a' * 64,
            'account_scope': 'photon:' + 'b' * 64, 'status': 'upstream-observed', 'updated_at': 1793430000, 'next_attempt': 0,
            'observed_only': True, 'live_transport_verified': False, 'network_requested': False, 'private_credentials_returned': False},
            'active_authorization_returned': False}
    owner.status = status
    owner.profiles = lambda: {'profiles': [profile], 'history_truncated': False, 'network_requested': False, 'private_bytes_returned': False}
    def sources(selected):
        wait(); item = deepcopy(row)
        if mode['active']: item = snap({**{k: v for k, v in item.items() if k != 'snapshot_sha256'}, 'current_grant': True, 'purge_allowed': False})
        if mode['private']: item['private_payload'] = 'must-never-render'
        return {'profile': selected, 'sources': [item], 'history_truncated': False, 'network_requested': False, 'private_bytes_returned': False}
    owner.sources = sources
    def purge(selected, identity, snapshot, note, *, confirmed):
        assert selected == profile and identity == row['id'] and snapshot == row['snapshot_sha256'] and note.strip() and confirmed is True
        calls.append((selected, identity, snapshot))
        return {'id': 'f' * 64 if mode['wrong'] else identity, 'receipt': '1' * 64, 'network_requested': False,
            'message_sent': False, 'tombstones_retained': True, 'other_copies_backups_and_WAL_erasure_not_claimed': True}
    owner.purge = purge
    wizard = Wizard(tk)
    for child in wizard.content.winfo_children(): child.destroy()
    form = gui.RecoveryForm(wizard, wizard.content); form.frame.pack(fill='x'); wizard.root.update(); cases = []
    def settle():
        deadline = time.monotonic() + 7
        while wizard.running and time.monotonic() < deadline: wizard.root.update(); time.sleep(.01)
        wizard.root.update(); assert not wizard.running
    def load(kind): form.buttons[kind].invoke(); settle()
    def select():
        form.list.selection_set(0); form.list.event_generate('<<ListboxSelect>>'); wizard.root.update()
    def consent(): form.note.insert(0, 'fixture explicit retired-source inspection'); form.confirm.set(True)
    try:
        load('status'); assert 'keine Live-Prüfung' in wizard.status.cget('text') and 'zuletzt beobachtet' in wizard.status.cget('text')
        assert form.details.cget('state') == 'disabled' and not form.details.winfo_manager()
        form.expand.set(True); form.toggle(); wizard.root.update(); assert form.details.winfo_manager() == 'pack'
        form.expand.set(False); form.toggle(); assert not form.details.winfo_manager()
        cases.append('actual_Tk_recorded_status_has_honest_live_limit_and_collapsible_readonly_details')
        load('profiles'); assert form.list.size() == 1; select()
        assert form.profile.get() == profile and not form.rows
        cases.append('actual_Tk_profile_selection_requires_fresh_original_inventory')
        load('sources'); select(); before = len(calls); form.buttons['purge'].invoke(); settle(); assert len(calls) == before
        consent(); form.buttons['purge'].invoke(); settle()
        assert len(calls) == before + 1 and not form.rows and not form.confirm.get() and not form.note.get()
        assert 'keine entfernte Löschung' in wizard.status.cget('text')
        cases.append('actual_Tk_exact_snapshot_note_and_explicit_consent_required_then_cleared_after_disposal')
        mode['active'] = True; load('sources'); select(); consent(); before = len(calls); form.buttons['purge'].invoke(); settle()
        assert len(calls) == before; mode['active'] = False
        cases.append('actual_Tk_active_original_grant_prevents_disposal')
        load('sources'); select(); consent(); form.profile.set('photon-' + 'c' * 64)
        form.buttons['purge'].invoke(); settle(); assert len(calls) == before and not form.rows and not form.confirm.get()
        form.profile.set(profile)
        cases.append('actual_Tk_changed_profile_discards_snapshot_and_consent')
        mode['slow'] = True; entered.clear(); release.clear(); form.buttons['sources'].invoke(); assert entered.wait(2)
        form.connector.set('other'); release.set(); settle(); assert not form.rows
        mode['slow'] = False; form.connector.set('phone')
        cases.append('actual_async_Tk_slow_response_is_discarded_after_selection_change')
        mode['private'] = True; load('sources')
        assert not form.rows and 'must-never-render' not in form.details.get('1.0', tk.END); mode['private'] = False
        cases.append('actual_Tk_private_or_unbounded_metadata_is_rejected_before_rendering')
        mode['foreign'] = True; load('status'); assert not form.rows and not form.details.get('1.0', tk.END).strip(); mode['foreign'] = False
        cases.append('actual_Tk_status_from_another_connector_is_rejected')
        load('sources'); select(); consent(); mode['wrong'] = True; form.buttons['purge'].invoke(); settle()
        assert not form.rows and not form.confirm.get() and 'keine entfernte Löschung' not in wizard.status.cget('text')
        cases.append('actual_Tk_wrong_disposal_receipt_never_reports_success_or_retains_stale_consent')
        assert all(button.winfo_reqwidth() <= form.frame.winfo_width() for button in form.buttons.values())
        wizard.show('photon-recovery'); wizard.root.update()
        def labels(widget):
            current = [widget.cget('text')] if isinstance(widget, (tk.Label, tk.Button, tk.Checkbutton)) else []
            return current + [label for child in widget.winfo_children() for label in labels(child)]
        text = labels(wizard.content)
        assert 'Zur Gateway-Verwaltung' in text and 'Aufgezeichneten Status lesen' in text
        cases.append('actual_Wizard_recovery_page_constructs_real_controls_and_return_navigation_without_public_activation')
        Path(sys.argv[2]).write_text(json.dumps({'passed': len(cases), 'cases': cases,
            'screen': [wizard.root.winfo_screenwidth(), wizard.root.winfo_screenheight()],
            'actual_Tk_async_controls': True, 'privileged_backend_responses_are_explicit_fixtures': True,
            'live_Photon_installed_GUI_or_public_activation': False}, indent=2) + '\n')
        print(json.dumps({'passed': len(cases)}))
    finally: release.set(); wizard.root.destroy()


if __name__ == '__main__': main()
