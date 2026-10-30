"""Argument admission before any optional SDK, process or network work."""
import pytest

from haos.gateway_buzz_cli import selection

ACCOUNT={'public_key':'1'*64,'channels':['01234567-89ab-4cde-8012-3456789abcde']}
READ=['messages','get','--channel',ACCOUNT['channels'][0],'--limit','50']


@pytest.mark.parametrize('args',[
    ['messages','send','--channel',ACCOUNT['channels'][0],'--content','-'],
    ['media','get','-o','/tmp/agent-selected','https://elsewhere.invalid/media/a'],
    ['channels','create'],['users','get','--pubkey','2'*64],
    ['users','get','--relay-url','https://elsewhere.invalid'],
    ['channels','get','--channel','11234567-89ab-4cde-8012-3456789abcde'],
    READ+['--limit','200'],READ+['--before','-1'],READ+['--since','01'],
    READ+['--before','1.0'],READ+['--since','١'],READ+['--before',str(2**53)],
    READ+['--since','20','--before','19'],READ+['--kinds','0'],
    ['messages','get','--channel',ACCOUNT['channels'][0]],
])
def test_untrusted_native_queries_cannot_widen_program_protocol_account_channel_or_time_bounds(args):
    with pytest.raises(PermissionError):selection(args,ACCOUNT,set())


def test_private_history_keeps_inclusive_same_second_bounds_and_explicit_peer_identity():
    peer='3'*64
    verb,flags=selection(READ+['--since','7','--before','7'],ACCOUNT,{peer})
    assert verb==('messages','get') and flags['--since']==flags['--before']=='7'
    assert selection(['users','get','--pubkey',peer],ACCOUNT,{peer})[1]=={'--pubkey':peer}
