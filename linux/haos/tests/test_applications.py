import os
from pathlib import Path

import pytest

from haos.applications import ApplicationRegistry, validate_application, unique_object


def manifest():
    return {'id': 'mission-editor', 'class': 'editor', 'executable': '/usr/bin/editor',
            'sha256': 'a' * 64, 'argv': ['--working-directory=/workspace'], 'memory_mib': 512, 'runtime_seconds': 300}


@pytest.mark.parametrize('field,value', [
    ('id', '../owner'), ('id', 'Owner'), ('class', 'root'), ('executable', '/bin/editor'),
    ('executable', '/usr/bin/../bin/editor'), ('executable', '/usr//bin/editor'), ('executable', '/usr/bin/editor\n'),
    ('sha256', 'latest'), ('sha256', 'a' * 63), ('argv', 'command'), ('argv', ['value\0']),
    ('argv', ['a' * 1025]), ('argv', ['argument'] * 33), ('memory_mib', True), ('memory_mib', 127),
    ('memory_mib', 4097), ('runtime_seconds', True), ('runtime_seconds', 0), ('runtime_seconds', 3601),
])
def test_application_manifest_cannot_supply_unknown_identity_or_unbounded_execution(field, value):
    with pytest.raises((ValueError, PermissionError)):
        validate_application(manifest() | {field: value})


@pytest.mark.parametrize('field', ['environment', 'sudo', 'capabilities', 'volumes', 'wayland_socket', 'owner_credentials'])
def test_classification_does_not_grant_system_capabilities(field):
    with pytest.raises(ValueError):
        validate_application(manifest() | {field: 'not-authorized'})


def test_manifest_is_copied_and_duplicate_json_keys_are_denied():
    source = manifest(); parsed = validate_application(source)
    source['argv'].append('later change')
    assert parsed['argv'] == ['--working-directory=/workspace']
    with pytest.raises(ValueError):
        unique_object([('applications', []), ('applications', [manifest()])])


@pytest.mark.skipif(os.geteuid() == 0, reason='negative actual unprivileged owner authority')
def test_agent_or_observer_cannot_open_a_registry_even_with_a_custom_path(tmp_path):
    with pytest.raises(PermissionError, match='authenticated owner'):
        ApplicationRegistry(tmp_path / 'applications.json')
    assert not list(Path(tmp_path).iterdir())
