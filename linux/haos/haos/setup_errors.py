"""Safe, actionable diagnostics for the local privileged first-run wizard.

Exception objects may contain passwords, API keys, private endpoints or shell
arguments. Never show arbitrary str(exception), stderr, traceback or repr.
Only explicit constant failure stages, known validation errors and numeric OS
codes are allowed onto the screen. Nothing is written to a log or state file.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess


@dataclass(frozen=True)
class SetupProblem:
    title: str
    code: str
    details: str


class SetupStageError(RuntimeError):
    """A bounded failure phase; the original exception remains private."""

    def __init__(self, stage: str, cause: Exception):
        super().__init__(stage)
        self.stage = stage
        self.cause = cause


STAGES = {
    "OWNER_STOP": ("HAOS-OWNER-STOP", "HAOS-Dienste konnten vor der Kontoerstellung nicht angehalten werden."),
    "OWNER_QUIESCE": ("HAOS-OWNER-QUIESCE", "HAOS-Dienste sind noch aktiv oder ihr Zustand konnte nicht überprüft werden."),
    "OWNER_PENDING": ("HAOS-OWNER-STATE", "Der geschützte Einrichtungszustand konnte nicht vorbereitet werden."),
    "OWNER_ENROLL": ("HAOS-OWNER-ENROLL", "Das Administrator-Konto konnte nicht sicher erstellt werden."),
    "OWNER_VERIFY": ("HAOS-OWNER-VERIFY", "Das neu angelegte Administrator-Konto konnte nicht verifiziert werden."),
    "OWNER_CODES": ("HAOS-OWNER-RECOVERY", "Die Wiederherstellungscodes konnten nicht erzeugt werden."),
    "OWNER_AUDIT": ("HAOS-OWNER-AUDIT", "Der geschützte Abschluss der Kontoerstellung ist fehlgeschlagen."),
}

# These messages are fixed strings emitted by audited HAOS code. No field
# from a user, a provider, a subprocess, or an exception repr is interpolated.
VALIDATION = {
    "Administrator passwords do not match":
        ("HAOS-PASSWORD-MISMATCH", "Die beiden Administrator-Passwörter stimmen nicht überein."),
    "use a strong 20–256 character password without the account name or control characters":
        ("HAOS-PASSWORD-QUALITY", "Das Passwort erfüllt die HAOS-Mindestanforderungen nicht (20–256 Zeichen, ohne Kontonamen)."),
    "owner username must be a simple lowercase account name":
        ("HAOS-OWNER-NAME", "Der Kontoname darf nur Kleinbuchstaben, Zahlen, _ und - enthalten."),
    "enrollment requires a new account; existing accounts are never repurposed":
        ("HAOS-OWNER-EXISTS", "Dieser Unix-Benutzername existiert bereits. Bestehende Konten bleiben geschützt."),
    "existing owners must never be overwritten during migration":
        ("HAOS-OWNER-ENROLLED", "Es ist bereits ein Administrator registriert. Bitte den bestehenden Account verwenden."),
    "initial owner onboarding has already completed":
        ("HAOS-OWNER-ENROLLED", "Die Ersteinrichtung dieses Administrators wurde bereits durchgeführt."),
    "owner must be separate from observer and service accounts":
        ("HAOS-OWNER-RESERVED", "Dieser Benutzername ist für einen HAOS-Systemdienst reserviert."),
    "exactly one configured observer is required":
        ("HAOS-OBSERVER-STATE", "Das technische HAOS-Benutzerkonto ist nicht korrekt vorbereitet."),
    "a prior graphical setup must be resolved first":
        ("HAOS-SETUP-PENDING", "Ein unterbrochener Einrichtungsversuch muss erst sicher fortgesetzt werden."),
    "multiple enrolled owners need a separate migration review":
        ("HAOS-MULTI-OWNER", "Mehrere registrierte Administratoren erfordern eine gesonderte Prüfung."),
    "a normal user display name must be chosen first":
        ("HAOS-PROFILE-NAME", "Bitte zuerst einen Anzeigenamen für das normale Benutzerprofil festlegen."),
}

# The enrolment helper raises these exact templates without subprocess output.
_PROGRAM = re.compile(
    r"owner enrollment command (failed|unavailable): "
    r"(/usr/bin/(?:pwscore|passwd|chpasswd|visudo)|"
    r"/usr/sbin/(?:useradd|usermod))\Z"
)

_SAFE_TYPES = (ValueError, PermissionError, RuntimeError, OSError,
               subprocess.CalledProcessError, subprocess.TimeoutExpired)


def describe_error(error: Exception, *, area: str = "setup") -> SetupProblem:
    """Convert privileged failures into a local-only, non-secret error report."""
    stage = error.stage if isinstance(error, SetupStageError) else None
    cause = error.cause if isinstance(error, SetupStageError) else error
    code, summary = STAGES.get(stage, ("HAOS-SETUP-FAILED", "Die HAOS-Einrichtung konnte nicht abgeschlossen werden."))
    notes = [f"Bereich: {area if area in {'security', 'user', 'region', 'provider', 'updates', 'gateways', 'finish'} else 'setup'}",
             f"Fehlercode: {code}"]

    # Don't interpolate arbitrary exception text. Fixed messages only.
    if type(cause) in (ValueError, PermissionError, RuntimeError):
        known = VALIDATION.get(str(cause))
        if known:
            validation_code, summary = known
            notes.append(f"Ursache: {validation_code}")

    if type(cause) is RuntimeError:
        match = _PROGRAM.fullmatch(str(cause))
        if match:
            program = match.group(2).rsplit("/", 1)[-1]
            summary = f"HAOS-Systemprogramm '{program}' konnte nicht erfolgreich ausgeführt werden."
            notes.append(f"Systemprogramm: {program}")
            notes.append("Prüfung: Rückgabefehler" if match.group(1) == "failed"
                         else "Prüfung: Programm nicht verfügbar oder Zeitlimit überschritten")

    if type(cause) is subprocess.CalledProcessError and type(cause.returncode) is int:
        # Exact safe fixed command from create_initial_owner; never echo argv
        # from other subprocesses (they can include provider credentials).
        if cause.cmd == ["/usr/bin/systemctl", "stop", "haos-gateway.service",
                         "haos-controller.service", "haos-hermes.service"]:
            summary = "Die benötigten HAOS-Dienste konnten vor der Administrator-Einrichtung nicht angehalten werden."
            code = "HAOS-OWNER-STOP"
            notes[1] = f"Fehlercode: {code}"
            notes.append("Systemschritt: Dienst-Stopp vor dem Anlegen des Kontos")
        notes.append(f"Systemprozess-Rückgabecode: {cause.returncode}")
    if type(cause) is subprocess.TimeoutExpired and type(cause.timeout) in (int, float):
        notes.append(f"Zeitüberschreitung nach {cause.timeout:g} Sekunden")
    if type(cause) is OSError and type(cause.errno) is int:
        notes.append(f"Betriebssystem-Fehlernummer: {cause.errno}")

    kind = type(cause).__name__ if type(cause) in _SAFE_TYPES else "InternalError"
    notes.append(f"Fehlerklasse: {kind}")
    notes.append("Keine Passwörter, Wiederherstellungscodes, Tokens oder Roh-Tracebacks werden angezeigt.")
    return SetupProblem(summary, code, "\n".join(notes))
