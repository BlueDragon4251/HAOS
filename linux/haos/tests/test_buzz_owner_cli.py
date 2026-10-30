"""Actual CLI grammar preserves the top-level owner dispatch action."""
import argparse
import sys

import pytest

from haos import owner


class Parsed(Exception):
    def __init__(self,namespace):self.namespace=namespace


@pytest.mark.parametrize('command,field,value',[
    (['buzz-recover-upload','buzz-main','retry-upload','--id','a'*64,'--snapshot-sha256','b'*64,'--note','fixture inspection'],
        'upload_action','retry-upload'),
    (['a2a-recover','a2a-main','purge-task-outputs','--profile','a2a-'+'a'*64,'--peer-journal','peer-'+'b'*64,
        '--task-id','task-'+'c'*16,'--snapshot-sha256','d'*64,'--note','fixture inspection'],
        'recovery_action','purge-task-outputs'),
    (['buzz-account','buzz-main'],'gateway_action','buzz-account')])
def test_nested_recovery_action_never_overwrites_gateway_owner_dispatch(monkeypatch,command,field,value):
    actual=argparse.ArgumentParser.parse_args
    def parse(parser,*args,**kwargs):
        # Parse the real product grammar, then stop before privileged work.
        raise Parsed(actual(parser,*args,**kwargs))
    monkeypatch.setattr(argparse.ArgumentParser,'parse_args',parse)
    monkeypatch.setattr(sys,'argv',['haos-owner','gateway',*command])
    with pytest.raises(Parsed) as result:owner.main()
    assert result.value.namespace.action=='gateway'
    assert getattr(result.value.namespace,field)==value
