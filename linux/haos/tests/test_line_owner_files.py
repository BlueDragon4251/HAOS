import os

import pytest

from haos import initial_setup


@pytest.mark.parametrize('attack',['world-readable','symlink','hardlink','oversized','empty','directory'])
def test_owner_pem_reader_rejects_unsafe_real_files_before_optional_crypto(tmp_path,monkeypatch,attack):
    # Ordinary-user descriptor cases; actual root/foreign UID cases run separately.
    monkeypatch.setattr(initial_setup,'require_root',lambda:None)
    monkeypatch.setattr(initial_setup,'owners',lambda:[{'uid':os.geteuid()}])
    path=tmp_path/'private.pem';path.write_text('not-used-as-valid-PEM');path.chmod(0o600)
    if attack=='world-readable':path.chmod(0o644)
    elif attack=='symlink':
        link=tmp_path/'link.pem';link.symlink_to(path);path=link
    elif attack=='hardlink':os.link(path,tmp_path/'second-link')
    elif attack=='oversized':path.write_bytes(b'x'*16385)
    elif attack=='empty':path.write_bytes(b'')
    elif attack=='directory':path.unlink();path.mkdir(mode=0o700)
    with pytest.raises((PermissionError,OSError)):
        initial_setup.read_line_tls_file(str(path),'certificate')


def test_line_pem_import_requires_physical_seat_before_opening_file(monkeypatch):
    from haos import initial_setup_gui
    monkeypatch.setattr(initial_setup,'require_root',lambda:None)
    monkeypatch.setattr(initial_setup_gui,'session_allowed',lambda:False)
    with pytest.raises(PermissionError,match='trusted local setup seat'):
        initial_setup.import_line_tls_file('/nonexistent/private.pem','certificate')


def test_line_pem_reader_rejects_unknown_kind_before_opening_file(monkeypatch):
    monkeypatch.setattr(initial_setup,'require_root',lambda:None)
    with pytest.raises(ValueError,match='certificate or private_key'):
        initial_setup.read_line_tls_file('/nonexistent/private.pem','plugin')
