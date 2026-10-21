#!/usr/bin/python3 -I
"""Fixed root-seat entry; never a command shell or agent endpoint."""
import sys
sys.path.insert(0, "/usr/lib/haos")
from haos.initial_setup_gui import session_allowed
from haos.provider_setup import auth_helper

if not session_allowed() or len(sys.argv) not in {3, 4}:
    raise SystemExit("Trusted physical setup seat required")
status = 0
try:
    auth_helper(sys.argv[1], sys.argv[2], region=sys.argv[3] if len(sys.argv) == 4 else "global")
except Exception:
    print("Anmeldung nicht abgeschlossen. Konto, Netzwerk und Provider-Voraussetzungen prüfen.")
    status = 1
input("Enter drücken, um zur Einrichtung zurückzukehren … ")
raise SystemExit(status)
