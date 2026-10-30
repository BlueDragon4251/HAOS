#!/usr/bin/env python3
"""Build exact native Buzz programs from reviewed archive, SDK locks and overlays."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

from prepare_buzz import prepare


def build(output,*,archive=None,offline=False):
    overlay=Path(__file__).resolve().parent;manifest=json.loads((overlay/'buzz-source.json').read_text())
    output=Path(output)
    if output.is_symlink() or output.exists() and any(output.iterdir()):raise ValueError('fresh empty native Buzz output directory required')
    kept=['PATH','RUSTUP_HOME','CARGO_HOME','CARGO_TARGET_DIR','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY',
        'http_proxy','https_proxy','all_proxy','no_proxy','SSL_CERT_FILE','SSL_CERT_DIR','CARGO_HTTP_CAINFO']
    env={key:os.environ[key] for key in kept if key in os.environ};env.update(CARGO_BUILD_JOBS='2',LANG='C.UTF-8')
    def run(args,cwd,timeout=1200):
        result=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
        if result.returncode:raise RuntimeError('pinned native '+args[0]+' step failed (exit '+str(result.returncode)+')')
        return result.stdout.strip()
    rust=run(['rustc','--version'],'/',10);cargo=run(['cargo','--version'],'/',10)
    if not rust.startswith('rustc '+manifest['rust_version']+' ') or not cargo.startswith('cargo '+manifest['rust_version']+' '):
        raise ValueError('exact reviewed native Rust/Cargo toolchain required')
    with tempfile.TemporaryDirectory(prefix='haos-buzz-build-') as directory:
        work=Path(directory);env['HOME']=str(work/'home');(work/'home').mkdir(mode=0o700)
        if 'CARGO_TARGET_DIR' not in env:env['CARGO_TARGET_DIR']=str(work/'target')
        package=work/'source.tar.gz'
        if archive is not None:
            if Path(archive).stat().st_size!=manifest['archive_size']:raise ValueError('exact reviewed Buzz archive size required')
            shutil.copyfile(archive,package)
        else:
            if offline:raise ValueError('offline native build requires the reviewed source archive')
            request=urllib.request.Request(manifest['url'],headers={'User-Agent':'HAOS-pinned-Buzz-builder'})
            with urllib.request.urlopen(request,timeout=60) as response,package.open('wb') as stream:
                size=0
                while block:=response.read(65536):
                    size+=len(block)
                    if size>manifest['archive_size']:raise ValueError('Buzz source archive exceeds exact reviewed size')
                    stream.write(block)
        if package.stat().st_size!=manifest['archive_size'] or hashlib.sha256(package.read_bytes()).hexdigest()!=manifest['archive_sha256']:
            raise ValueError('Buzz source archive differs from exact reviewed pin')
        extracted=work/'source';extracted.mkdir()
        with tarfile.open(package,'r:gz') as source:source.extractall(extracted,filter='data')
        roots=list(extracted.iterdir())
        if len(roots)!=1 or not roots[0].is_dir():raise ValueError('one reviewed official Buzz source root required')
        source=roots[0];prepared=prepare(source,overlay)
        helper=work/'verifier';shutil.copytree(overlay/'buzz-verify',helper)
        if not offline:
            for project in [source,helper]:run(['cargo','fetch','--locked'],project)
        for project,package_name in [(source,'buzz-cli'),(helper,'haos-buzz-verify')]:
            run(['cargo','build','--frozen','--release','-p',package_name],project)
        output.mkdir(mode=0o755,parents=True,exist_ok=True)
        for name in ['buzz','haos-buzz-verify']:
            binary=Path(env['CARGO_TARGET_DIR'])/'release'/name
            if not 0<binary.stat().st_size<=128*1024*1024:raise ValueError('bounded compiled Buzz program required')
            versions=re.findall(r'GLIBC_([0-9]+)\.([0-9]+)',run(['readelf','--version-info',str(binary)],'/'))
            maximum=max((tuple(map(int,version)) for version in versions),default=(0,0))
            if maximum>(2,36):raise ValueError('native Buzz program exceeds reviewed glibc ABI floor')
            shutil.copyfile(binary,output/name);(output/name).chmod(0o755)
            prepared['programs'][name].update(sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                actual_maximum_glibc='.'.join(map(str,maximum)))
        prepared['build']={'rustc':rust,'cargo':cargo,'architecture':platform.machine(),'offline_cargo_build':True}
        prepared['helper_sources_sha256']={name:hashlib.sha256((helper/name).read_bytes()).hexdigest()
            for name in ['Cargo.toml','Cargo.lock','src/main.rs']}
        (output/'source.json').write_text(json.dumps(prepared,indent=2)+'\n');(output/'source.json').chmod(0o644)
        print(json.dumps({'built':True,'source_commit':manifest['commit'],'programs':prepared['programs']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--archive');parser.add_argument('--offline',action='store_true')
    args=parser.parse_args();build(args.output,archive=args.archive,offline=args.offline)
