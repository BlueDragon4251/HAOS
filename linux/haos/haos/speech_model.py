"""Public, immutable local STT model inputs; no account or executable model code."""
from pathlib import Path

REPOSITORY='Systran/faster-whisper-tiny'
REVISION='d90ca5fe260221311c53c58e660288d3deb8d356'
MODEL_ROOT=Path('/var/lib/haos-speech-models')/('tiny-'+REVISION)
FILES={
    'config.json':(2249,'a73a28cdfe1c43ccc7202fa333d1f89c202477271407ae9a7f19afa52039cac8'),
    'model.bin':(75538270,'dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1'),
    'tokenizer.json':(2203239,'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab'),
    'vocabulary.txt':(459861,'34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913'),
}
