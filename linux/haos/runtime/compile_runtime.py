#!/usr/bin/env python3
"""Build checked-hash bytecode before the immutable runtime reaches slow guests."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import stat
import sys
import sysconfig

EXCLUDED={'.git','.venv','__pycache__','tests','test','testdata','fixtures','node_modules'}


def compile_tree(root):
    """No module execution; changed source invalidates its checked-hash cache."""
    root=Path(root);digest=hashlib.sha256();count=total=0
    if root.is_symlink() or not root.is_dir():raise PermissionError('real runtime source directory required')
    for directory,children,names in os.walk(root,followlinks=False):
        children[:]=sorted(name for name in children if name not in EXCLUDED and not (Path(directory)/name).is_symlink())
        for name in sorted(names):
            if not name.endswith('.py'):continue
            path=Path(directory)/name;info=path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode&0o022:raise PermissionError('unmodified regular runtime source required')
            source=path.read_bytes()
            cache=Path(py_compile.compile(str(path),doraise=True,invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH))
            encoded=cache.read_bytes()
            if encoded[:4]!=importlib.util.MAGIC_NUMBER or int.from_bytes(encoded[4:8],'little')!=3 or encoded[8:16]!=importlib.util.source_hash(source):
                raise RuntimeError('compiled runtime is not checked against its actual source')
            cache.chmod(0o644)
            digest.update(str(path.relative_to(root)).encode()+b'\0'+hashlib.sha256(source).digest()+hashlib.sha256(encoded).digest())
            count+=1;total+=len(encoded)
    if not count:raise ValueError('empty runtime bytecode input')
    return {'modules':count,'bytecode_bytes':total,'input_and_bytecode_sha256':digest.hexdigest(),'invalidation':'checked-hash'}


def main():
    if os.geteuid()!=0 or sys.version_info[:2]!=(3,11):raise PermissionError('image build with the pinned Python 3.11 required')
    upstream=Path('/usr/lib/haos/hermes');packages=Path(sysconfig.get_path('purelib')).resolve()
    if not packages.is_relative_to(upstream/'.venv'):raise PermissionError('actual immutable runtime environment required')
    roots={'upstream':upstream,'dependencies':packages,'haos':Path('/usr/lib/haos/haos')}
    result={'schema':1,'python_cache_tag':sys.implementation.cache_tag,
        'upstream_commit':(upstream/'.herald-os-upstream-sha').read_text().strip(),
        'trees':{name:compile_tree(path) for name,path in roots.items()}}
    Path('/usr/lib/haos/runtime-provenance/bytecode.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
