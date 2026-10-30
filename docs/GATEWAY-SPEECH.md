# Local gateway speech — private core, integration in progress

The bounded local decoder, pinned Hermes transcription engine, isolated worker
and private socket service now connect to LINE's signed audio input and the
mission controller. Owner model/service setup and a separate per-sender
`allow_voice` approval are available in the physical GUI and authenticated
console. Existing text/image/document grants do not approve audio. Video,
outbound media and TTS remain open; fixture success is not external delivery,
LLM inference, installed systemd or HP acceptance.

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
actual gateway/controller peer UIDs before reading a frame. The request consists only of
canonical base64 and a source SHA-256; paths, commands and extra authority
fields are refused. The parent permits one active worker and at most four
pending clients. Worker CPU time, output, wall time, file size, service memory
and task counts are bounded. Disconnects cancel, kill and join a started worker,
including cancellation while subprocess creation is pending.

Socket activation validates the real NSS identity, inherited descriptor,
activation PID and exact socket path plus explicit root-owned configuration.
The image installs the definitions and separate identity but does not enable
the speech socket by default. Owner activation is explicit and does not grant
a sender access. The controller already has the gateway socket group; peer UID
authorization remains mandatory even when filesystem connection is permitted. The physical service profile still requires installed-system acceptance;
a successful disposable descriptor/UID probe is not an installed boot test.

`probe_speech_backend.py` performs real FLAC decoding, AAC/M4A and CAF
encoding/decoding, negative duration/channel/playlist tests and actual local
model recognition. CAF uses the same byte, channel, sample and two-minute
limits and the existing pipe-only protocol allowlist. Its decoded PCM must
match the approved reference exactly, and an overlong valid CAF must fail the
duration check. The separate Speech UID and checked controller Unix RPC also
recognize the actual CAF reference through the pinned engine. This fixes the
previous local rejection of Photon CAF input; native Photon transport through
the complete controller remains a separate acceptance.
The public reference recording is OpenAI Whisper's `tests/jfk.flac` at source
`86098128c0b4f24f0e2aa2994de830614b474227`, SHA-256
`63a4b1e4c1dc655ac70961ffbf518acd249df237e5a0152faae9a4a836949715`.
Runtime build and provider CI require this native probe. A separate fresh,
network-disabled Docker process probe uses real NSS, UIDs, socket activation,
peer credentials, private role canaries and process cancellation; no UID/kernel
check is mocked. Its reference phrase is recognized by the actual pinned
engine, not a substituted transcript. Neither probe establishes live LINE
voice delivery, language-wide accuracy, HP performance or external accounts.


## Owner model/service management

The graphical gateway page links local speech status, model loading/activation
and service deactivation. Console equivalents, as the authenticated owner:

```sh
sudo haos-owner speech status
sudo haos-owner speech enable
sudo haos-owner speech disable
```

Setup checks the actual Python 3.11/native package versions in a subprocess
**demoted to haos-speech**, with no supplementary groups or inherited credentials.
It does not execute the SDK as root. Only the fixed reviewed model can be loaded;
existing mismatched assets or foreign engine settings require owner inspection.
The root-owned publication and engine settings are atomic. Model installation
requires the public download once, then cached verified files are reused.
Service changes require fully inactive worker/control PIDs and a private owner
lock. An administrator mask is not removed automatically. The ordinary owner
setup gate still applies when systemd starts the service.

Status separates installed runtime, verified model, configured activation and
actual unit states. A listening socket is not a LINE delivery or transcription
acceptance. Deactivation stops new processing, archives the configuration and
preserves models and sender grants; sender revocation remains the separate
gateway operation. Root publication tests use actual SDK metadata, public model
bytes and filesystem ownership, with explicitly fixture-controlled service
commands. Actual NSS/UID/socket activation/worker/kill gates run separately
without mocked kernel checks. Neither set replaces an installed systemd test.


## LINE voice mission path and recovery

First configure the local engine, then separately approve one LINE route with
mission-create permission using its graphical voice checkbox or `gateway pair
--allow-voice`. Pairing refuses missing/disabled/unverified local speech setup;
image/document approval is a separate checkbox. Both consents reset on sender,
chat, destination/platform changes, lost create rights and submit. Re-pairing
without the flag withdraws earlier voice permission through a fresh owner epoch.

The actual pinned LINE adapter emits its native voice event after a bounded,
verified fixed-endpoint content fetch. Signed duration metadata is checked before
download; the decoder also limits actual samples. No external content URL is
followed. Grant-bound opaque media IDs and chunk upload retain the original audio
in the private controller ledger. **The original audio is never attached to the
agent.** The controller invokes the isolated local service and appends only the
recognized request text to the normal mission prompt. Voice cannot substitute
for image/document file permission or execute a gateway slash command.

The controller checks the exact current grant, cancellation, stop and deadline
while waiting for STT and again before caching/dispatch. A closed or revoked
caller cancels the local worker. Receipts bind source hash, pinned model,
sample bounds and transcript checksum to the upload ID, persist across ledger
reopen, and cannot be silently overwritten. Damaged receipts refuse dispatch.
A retry before prompt submission can reuse an intact receipt; a started or
uncertain model turn keeps the existing no-replay rules. Explicit terminal media
purge removes original chunks and derived transcripts, retaining audit/tombstones.

`probe_line_voice.py` composes actual signed LINE/native codec/verified HTTPS,
private media relay/controller and actual local STT with a fixture speech
transport and agent terminal. It checks real M4A words, separate/unknown sender
refusal, duration limits, signed replay, invalid-audio refusal and revocation
before prompt. It does not fabricate a transcript or claim LLM inference. The
separate kernel probe exercises the actual checked client under controller UID,
root-activated socket ownership, both allowed UIDs and cancellation/worker join.
These mandatory complementary probes do not replace installed/live acceptance.
