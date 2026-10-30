"""Bounded local speech decoding using the actual pinned Hermes STT engine.

No provider credential, plugin/command provider, caller path or remote model URL
is accepted. Public service/LINE admission is implemented separately.
"""
import hashlib
from io import BytesIO
import os
from pathlib import Path
import stat
import tempfile
import wave

from .speech_model import FILES,MODEL_ROOT,REVISION

MAX_AUDIO_BYTES=8*1024*1024
MAX_SECONDS=120
MAX_SAMPLES=16000*MAX_SECONDS
MAX_TRANSCRIPT=16000


class SpeechRefused(ValueError):
    pass


def verify_model(root=MODEL_ROOT,*,owner_uid=0):
    root=Path(root)
    for directory in [root.parent,root]:
        info=directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=owner_uid or info.st_mode&0o022:
            raise PermissionError('local speech model directory must be immutable to its consumer')
    for name,(size,expected) in FILES.items():
        fd=os.open(root/name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:
            info=os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=owner_uid or info.st_mode&0o022
                    or info.st_nlink!=1 or info.st_size!=size):
                raise PermissionError('reviewed local speech model file required')
            checksum=hashlib.sha256();remaining=size
            while remaining:
                data=os.read(fd,min(1024*1024,remaining))
                if not data:raise SpeechRefused('local speech model is incomplete')
                checksum.update(data);remaining-=len(data)
            if os.read(fd,1) or checksum.hexdigest()!=expected:raise SpeechRefused('local speech model checksum mismatch')
        finally:os.close(fd)
    return root


def decode(data):
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_AUDIO_BYTES:
        raise SpeechRefused('bounded nonempty audio bytes required')
    try:import av
    except ImportError:raise SpeechRefused('pinned local audio decoder unavailable') from None
    result=BytesIO();samples=0
    try:
        with av.open(BytesIO(data),options={'protocol_whitelist':'pipe',
                'format_whitelist':'wav,flac,mp3,mov,ogg,aac,amr,caf'}) as source:
            if len(source.streams.audio)!=1 or source.streams.video:
                raise SpeechRefused('one audio stream without video required')
            resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
            with wave.open(result,'wb') as target:
                target.setnchannels(1);target.setsampwidth(2);target.setframerate(16000)
                def append(frames):
                    nonlocal samples
                    for frame in frames:
                        samples+=frame.samples
                        if samples>MAX_SAMPLES:raise SpeechRefused('voice exceeds the two-minute duration limit')
                        pcm=frame.to_ndarray().tobytes()
                        if len(pcm)!=frame.samples*2:raise SpeechRefused('decoded voice sample shape invalid')
                        target.writeframesraw(pcm)
                for frame in source.decode(audio=0):
                    if len(frame.layout.channels)>2 or not 8000<=frame.sample_rate<=192000:
                        raise SpeechRefused('bounded mono/stereo audio rate required')
                    append(resampler.resample(frame))
                append(resampler.resample(None))
        if not samples:raise SpeechRefused('audio contains no decoded samples')
        return result.getvalue(),samples
    except SpeechRefused:raise
    except Exception:raise SpeechRefused('audio cannot be decoded as bounded voice') from None


def transcribe(data,*,model_root=MODEL_ROOT,model_owner_uid=0):
    if not isinstance(data,bytes) or not 1<=len(data)<=MAX_AUDIO_BYTES:
        raise SpeechRefused('bounded nonempty audio bytes required')
    root=verify_model(model_root,owner_uid=model_owner_uid)
    # Validate installed local dependencies before the native function can reach
    # its upstream lazy-install path. No command/cloud fallback is invoked.
    import importlib.metadata
    try:
        if importlib.metadata.version('faster-whisper')!='1.2.1':raise SpeechRefused('pinned local speech runtime unavailable')
        import faster_whisper  # Fail before upstream can attempt lazy installation.
        if not callable(faster_whisper.WhisperModel):raise SpeechRefused('pinned local speech engine unavailable')
    except ImportError:raise SpeechRefused('pinned local speech runtime unavailable') from None
    pcm,samples=decode(data)
    from tools import transcription_tools
    if transcription_tools._HAS_FASTER_WHISPER is not True:
        raise SpeechRefused('installed local speech runtime cannot be loaded')
    _transcribe_local=transcription_tools._transcribe_local
    with tempfile.TemporaryDirectory(prefix='haos-local-voice-') as directory:
        path=Path(directory)/'input.wav';path.write_bytes(pcm);path.chmod(0o600)
        result=_transcribe_local(str(path),str(root))
    text=result.get('transcript') if isinstance(result,dict) and result.get('success') is True and result.get('provider')=='local' else None
    if not isinstance(text,str) or not 1<=len(text.strip())<=MAX_TRANSCRIPT or '\x00' in text:
        raise SpeechRefused('local transcription unavailable or no usable speech recognized')
    return {'transcript':text.strip(),'source_sha256':hashlib.sha256(data).hexdigest(),
        'samples':samples,'sample_rate':16000,'model_revision':REVISION,'provider':'local'}
