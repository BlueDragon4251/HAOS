"""Read recorded Photon state without credentials, SDK, network or profile lease."""
import math
from pathlib import Path
import re

from .gateway_photon_health import STATES, known_account
from .gateway_photon_journal import readonly, ORIGINAL_COLUMNS


def selector(value):
    if (not isinstance(value, dict) or set(value) != {'connector', 'credential_scope', 'account_scope'}
            or not isinstance(value['connector'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value['connector'])
            or not isinstance(value['credential_scope'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['credential_scope'])
            or not isinstance(value['account_scope'], str) or not re.fullmatch(r'photon:[a-f0-9]{64}', value['account_scope'])):
        raise ValueError('exact saved Photon connector and credential/account fingerprints required')
    return dict(value)


def _time(value):
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 253402300799:
        raise ValueError('finite recorded Photon status time required')
    return value


def checked(value, request=None):
    fields = {'connector', 'credential_scope', 'account_scope', 'status', 'updated_at', 'next_attempt',
        'observed_only', 'live_transport_verified', 'network_requested', 'private_credentials_returned'}
    if (not isinstance(value, dict) or set(value) != fields or not isinstance(value['status'], str)
            or value['status'] not in STATES | {'not-started'} or value['observed_only'] is not True
            or any(value[key] is not False for key in ['live_transport_verified', 'network_requested', 'private_credentials_returned'])):
        raise ValueError('closed recorded Photon status without live verification or credentials required')
    chosen = selector({key: value[key] for key in ['connector', 'credential_scope', 'account_scope']})
    if value['updated_at'] is not None or value['status'] != 'not-started': _time(value['updated_at'])
    _time(value['next_attempt'])
    if request is not None and chosen != selector(request):
        raise ValueError('recorded Photon status belongs to another selected account')
    return dict(value)


def _profile_status(db, parent, params):
    from .gateway_line_profile import _directory
    known = db is not None and known_account(db, params['account_scope'])
    profiles = parent / 'profiles'; profile = profiles / ('photon-' + params['account_scope'].removeprefix('photon:'))
    for directory in [profiles, profile]:
        try: _directory(directory)
        except FileNotFoundError:
            if known: raise ValueError('known Photon original profile is missing; owner inspection required') from None
            return
    try:
        with readonly(profile / 'originals.db') as original:
            original.execute('SELECT ' + ','.join(ORIGINAL_COLUMNS) + ' FROM photon_originals LIMIT 0')
            if db is None: raise ValueError('native status journal is missing beside retained Photon originals')
            if not original.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photon_health_profiles'").fetchone():
                # Legacy profiles have no independent status provenance yet.
                # Their existing journal must still remain intact, not repaired.
                return
            rows = original.execute('SELECT * FROM photon_health_profiles LIMIT 65537').fetchall()
            if len(rows) > 65536: raise ValueError('bounded Photon status provenance required')
            for row in rows:
                if (row['account_scope'] != params['account_scope'] or any(not isinstance(row[key], str)
                        or not re.fullmatch(r'[a-f0-9]{64}', row[key]) for key in ['id', 'credential_scope'])):
                    raise ValueError('Photon retained status provenance is damaged')
                found = db.execute('SELECT account_scope,credential_scope,status,updated_at FROM photon_profile_status WHERE id=?', (row['id'],)).fetchone()
                if (found is None or found['account_scope'] != row['account_scope'] or found['credential_scope'] != row['credential_scope']
                        or found['status'] not in STATES):
                    raise ValueError('known Photon status row is missing or changed; owner inspection required')
                _time(found['updated_at'])
            if rows and not db.execute('SELECT 1 FROM photon_account_budget WHERE account_scope=?', (params['account_scope'],)).fetchone():
                raise ValueError('known Photon account retry budget is missing')
    except FileNotFoundError:
        if known: raise ValueError('known Photon original journal is missing; owner inspection required') from None


def read(path, params, current):
    from .gateway_runtime import require_runtime_identity
    from .gateway_line_profile import _directory
    require_runtime_identity(); params = selector(params); current(); path = Path(path); _directory(path.parent)
    result = {**params, 'status': 'not-started', 'updated_at': None, 'next_attempt': 0,
        'observed_only': True, 'live_transport_verified': False, 'network_requested': False, 'private_credentials_returned': False}
    try:
        with readonly(path) as db:
            expected = {'photon_profile_status', 'photon_account_budget'}
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('photon_profile_status','photon_account_budget')")}
            if tables and tables != expected: raise ValueError('incomplete Photon status journal requires owner inspection')
            if not tables and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('photon_output_intents','photon_native_projection') LIMIT 1").fetchone():
                raise ValueError('Photon status history is missing beside retained native records')
            if tables:
                row = db.execute('SELECT status,updated_at FROM photon_profile_status WHERE connector=? AND credential_scope=? AND account_scope=? ORDER BY updated_at DESC LIMIT 1',
                    (params['connector'], params['credential_scope'], params['account_scope'])).fetchone()
                if row is not None: result.update(status=row[0], updated_at=row[1])
                budget = db.execute('SELECT next_attempt FROM photon_account_budget WHERE account_scope=?', (params['account_scope'],)).fetchone()
                if budget is not None: result['next_attempt'] = _time(budget[0])
                elif row is not None: raise ValueError('Photon account retry budget is missing; owner inspection required')
            _profile_status(db, path.parent, params)
    except FileNotFoundError:
        if path.exists() or path.is_symlink(): raise ValueError('retained Photon journal disappeared during status read') from None
        _profile_status(None, path.parent, params)
    current(); return checked(result, params)
