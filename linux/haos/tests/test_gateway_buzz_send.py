"""No command, path, broadcast or unrelated recipient in private reply grammar."""
import pytest

from haos.gateway_buzz_send_process import target

ACCOUNT={'channels':['01234567-89ab-4cde-8012-3456789abcde']}


def reply():return {'channel':ACCOUNT['channels'][0],'anchor':'a'*64,'thread':'b'*64,'content':'Local reply',
    'kind':9,'allowed_mentions':['c'*64],'explicit_mentions':[]}


@pytest.mark.parametrize('change',[{'channel':'11234567-89ab-4cde-8012-3456789abcde'},
    {'anchor':'../source'},{'thread':'*'},{'kind':45001},{'kind':True},{'content':''},{'content':'x'*32001},
    {'content':'a\0b'},{'files':['/etc/owner-key']},{'broadcast':True},
    {'explicit_mentions':['d'*64]},{'explicit_mentions':['c'*64,'c'*64]},{'allowed_mentions':['c'*64]*3}])
def test_reply_cannot_select_other_channels_files_commands_implicit_broadcasts_or_unapproved_notifications(change):
    with pytest.raises(PermissionError):target(ACCOUNT,{**reply(),**change})


def test_forum_reply_uses_one_native_comment_and_explicit_parent_without_shell_or_stdin_path():
    args=target(ACCOUNT,{**reply(),'kind':45003,'explicit_mentions':['c'*64]})
    assert args==['messages','send','--channel',ACCOUNT['channels'][0],'--content','-','--reply-to','a'*64,
        '--kind','45003','--mention','c'*64]
