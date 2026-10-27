# Local gateway speech — private core, integration in progress

This increment implements the bounded local decoder, actual pinned Hermes
transcription engine, isolated worker and private socket service. **LINE voice
admission, sender approval, owner model activation and its GUI are not connected
yet. Existing public LINE policy continues to refuse audio.** Video, outbound
media and TTS also remain open. No operator workaround or manual authorization
bypass is needed to run the disposable contract probes.

The runtime adds only the pinned upstream `voice` extra to the existing frozen
extras and unchanged hashed security/provider overlay. This supplies
faster-whisper 1.2.1 and its locked native dependencies; it does not update the
Hermes source, MSAL correction or provider catalogue.

The reviewed multilingual tiny model is
`Systran/faster-whisper-tiny@d90ca5fe260221311c53c58e660288d3deb8d356`.
[speech_model.py](../linux/haos/haos/speech_model.py) records exact file sizes and
SHA-256 values; model weights use the upstream LFS digest, other files were
checked against their fixed Git blob identities before recording SHA-256.
Model directories must be immutable to the consumer. Files must be regular,
single-link, correct-owner and unwritable by other identities, then match their
size and checksum. No caller model path, model URL, plugin or command provider
is accepted by the socket. The local engine cannot fall through to a cloud
provider or a lazy installer.

Input is at most 8 MiB, one mono/stereo audio stream, at most 120 seconds of
actual decoded audio. A fixed demuxer/protocol allowlist excludes playlists and
external resources. Decoding produces bounded mono 16 kHz PCM. The native
Hermes local transcriber receives a newly created private WAV file, not a
caller filesystem path. Empty, malformed, oversized, long or unsupported input
fails with bounded diagnostics. Transcripts are at most 16000 characters.

The new `haos-speech` identity is separate from the gateway, provider,
controller and agent. The service has no loaded credentials, network, GPU
access or ambient capabilities. Its root-bound Unix socket admits only the
actual gateway peer UID before reading a frame. The request consists only of
canonical base64 and a source SHA-256; paths, commands and extra authority
fields are refused. The parent permits one active worker and at most four
pending clients. Worker CPU time, output, wall time, file size, service memory
and task counts are bounded. Disconnects cancel, kill and join a started worker,
including cancellation while subprocess creation is pending.

Socket activation validates the real NSS identity, inherited descriptor,
activation PID and exact socket path plus explicit root-owned configuration.
The image installs the definitions and separate identity but does not enable
the speech socket by default. Owner activation remains the next implementation
step. The physical service profile still requires installed-system acceptance;
a successful disposable descriptor/UID probe is not an installed boot test.

`probe_speech_backend.py` performs real FLAC decoding, AAC/M4A encoding/decoding,
negative duration/channel/playlist tests and actual local model recognition.
The public reference recording is OpenAI Whisper's `tests/jfk.flac` at source
`86098128c0b4f24f0e2aa2994de830614b474227`, SHA-256
`63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715`.
Runtime build and provider CI require this native probe. A separate fresh,
network-disabled Docker process probe uses real NSS, UIDs, socket activation,
peer credentials, private role canaries and process cancellation; no UID/kernel
check is mocked. Its reference phrase is recognized by the actual pinned
engine, not a substituted transcript. Neither probe establishes live LINE
voice delivery, language-wide accuracy, HP performance or external accounts.
