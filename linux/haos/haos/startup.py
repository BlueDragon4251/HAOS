"""Bounded startup diagnosis without arguments, locals, source lines or secrets."""
import json
from pathlib import PurePosixPath
import re
import socket
import sys
import threading
import time


def stack_identity(frame):
    frames=[]
    while frame is not None and len(frames)<12:
        filename=PurePosixPath(frame.f_code.co_filename)
        try: relative=filename.relative_to('/usr/lib/haos')
        except ValueError: relative=None
        name=frame.f_code.co_name
        # Installed code identities only. Never inspect frame locals/globals,
        # source text, arbitrary workspace names or user/plugin stack paths.
        if relative and re.fullmatch(r'[A-Za-z0-9_./-]{1,180}',str(relative)) and '..' not in relative.parts and re.fullmatch(r'[A-Za-z0-9_<>]{1,80}',name):
            frames.append({'module':str(relative),'function':name,'line':frame.f_lineno})
        frame=frame.f_back
    return frames


class StartupDiagnosis:
    def __init__(self,port):
        self.port=port;self.identity=threading.get_ident();self.done=threading.Event()
        self.thread=threading.Thread(target=self.watch,name='haos-startup-diagnosis',daemon=True)

    def mark(self,stage):
        if stage not in {'web-import','gui-registration','cli-import','canonical-cli','returned'}:
            raise ValueError('fixed startup phase required')
        print(json.dumps({'event':'backend.startup','stage':stage}),flush=True)

    def watch(self):
        began=time.monotonic();thresholds=iter((30,90,150));threshold=next(thresholds)
        while not self.done.wait(1):
            try:
                with socket.create_connection(('127.0.0.1',self.port),timeout=0.2):
                    return  # Never collect stacks once mission handling can begin.
            except OSError:pass
            if time.monotonic()-began>=threshold:
                print(json.dumps({'event':'backend.startup-stack','elapsed_seconds':threshold,
                    'frames':stack_identity(sys._current_frames().get(self.identity))}),flush=True)
                threshold=next(thresholds,None)
                if threshold is None:return

    def __enter__(self):
        # A fixture's ephemeral port is reported by upstream after bind. Do not
        # guess its identity or collect post-start stacks through port zero.
        if self.port:self.thread.start()
        return self

    def __exit__(self,*_args):
        self.done.set()
        if self.thread.is_alive():self.thread.join(timeout=1)
