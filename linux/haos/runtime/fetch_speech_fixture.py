#!/usr/bin/env python3
"""Public immutable assets for real offline STT contract probes; no owner setup."""
import json
from pathlib import Path
import sys

if __name__=='__main__':
    sys.path.insert(0,str(Path(sys.argv[1]).resolve()))
    from haos.speech_download import public_model,fetch
    destination=Path(sys.argv[2]).resolve();destination.mkdir(parents=True,exist_ok=True)
    public_model(destination/'model')
    revision='86098128c0b4f24f0e2aa2994de830614b474227'
    fetch('https://raw.githubusercontent.com/openai/whisper/'+revision+'/tests/jfk.flac',
        destination/'reference.flac',1152693,'63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715')
    print(json.dumps({'public_fixture_ready':True,'model':str(destination/'model'),'audio':str(destination/'reference.flac')}))
