"""Preserve socket activation while entering the immutable pinned speech runtime."""
import os


def main():
    executable='/usr/lib/haos/hermes/.venv/bin/python'
    os.execv(executable,[executable,'-s','-m','haos.speech_service'])


if __name__=='__main__':main()
