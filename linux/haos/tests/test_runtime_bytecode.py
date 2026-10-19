import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

spec=importlib.util.spec_from_file_location('haos_compile_runtime',Path(__file__).parents[1]/'runtime/compile_runtime.py')
compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)


def test_actual_checked_hash_cache_import_and_changed_source_invalidation(tmp_path):
    module=tmp_path/'haos_fixture.py';module.write_text('value = "original"\n');module.chmod(0o644)
    ignored=tmp_path/'tests';ignored.mkdir();(ignored/'invalid_fixture.py').write_text('intentional invalid syntax !')
    report=compiler.compile_tree(tmp_path)
    assert report['modules']==1 and report['invalidation']=='checked-hash'
    assert not (ignored/'__pycache__').exists()
    command=[sys.executable,'-I','-B','-c','import sys;sys.path.insert(0,sys.argv[1]);import haos_fixture;print(haos_fixture.value)',str(tmp_path)]
    assert subprocess.check_output(command,text=True).strip()=='original'
    # Same size and mtime must not make stale bytecode execute updated code.
    info=module.stat();module.write_text('value = "modified"\n')
    __import__('os').utime(module,ns=(info.st_atime_ns,info.st_mtime_ns))
    assert subprocess.check_output(command,text=True).strip()=='modified'
    assert compiler.compile_tree(tmp_path)['input_and_bytecode_sha256']!=report['input_and_bytecode_sha256']


def test_bytecode_input_symlinks_public_writes_empty_and_syntax_errors_fail(tmp_path):
    root=tmp_path/'root';root.mkdir();source=root/'fixture.py';source.write_text('value=1\n');source.chmod(0o666)
    with pytest.raises(PermissionError):compiler.compile_tree(root)
    source.chmod(0o644);source.unlink();source.symlink_to(__file__)
    with pytest.raises(PermissionError):compiler.compile_tree(root)
    alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True)
    with pytest.raises(PermissionError):compiler.compile_tree(alias)
    source.unlink()
    with pytest.raises(ValueError):compiler.compile_tree(root)
    source.write_text('invalid syntax !\n')
    with pytest.raises(__import__('py_compile').PyCompileError):compiler.compile_tree(root)
