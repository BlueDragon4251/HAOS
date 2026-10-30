from types import SimpleNamespace

import pytest

from haos.owner import stopped


@pytest.mark.parametrize("state,pid,load", [
    ("active", "123", "loaded"), ("activating", "123", "loaded"),
    ("deactivating", "123", "loaded"), ("failed", "0", "loaded"),
    ("inactive", "123", "loaded"), ("inactive", "0", "not-found"),
])
def test_owner_does_not_treat_nonactive_transition_as_stopped(monkeypatch, state, pid, load):
    monkeypatch.setattr("haos.owner.subprocess.run", lambda *a, **k: SimpleNamespace(
        stdout=f"LoadState={load}\nActiveState={state}\nMainPID={pid}\nControlPID=0\n"))
    with pytest.raises(PermissionError, match="stop"):
        stopped()


def test_owner_requires_no_control_process_and_checks_both_units(monkeypatch):
    seen = []
    def show(args, **kwargs):
        seen.append(args[-1])
        return SimpleNamespace(stdout="LoadState=loaded\nActiveState=inactive\nMainPID=0\nControlPID=0\n")
    monkeypatch.setattr("haos.owner.subprocess.run", show)
    stopped()
    assert seen == ["haos-controller.service", "haos-hermes.service"]
    monkeypatch.setattr("haos.owner.subprocess.run", lambda *a, **k: SimpleNamespace(
        stdout="LoadState=loaded\nActiveState=inactive\nMainPID=0\nControlPID=123\n"))
    with pytest.raises(PermissionError):
        stopped()


def test_media_cli_requires_stopped_services_before_opening_ledger(monkeypatch):
    from haos import owner
    monkeypatch.setattr('sys.argv',['haos-owner','media','purge','--id','a'*64,'--note','inspected','--confirm-inspected'])
    monkeypatch.setattr(owner.os,'geteuid',lambda:0)
    def refuse():raise PermissionError('execution still running')
    monkeypatch.setattr(owner,'stopped',refuse)
    def forbidden(*args,**kwargs):raise AssertionError('opened ledger before stopped gate')
    monkeypatch.setattr(owner,'MissionStore',forbidden)
    with pytest.raises(PermissionError,match='still running'):owner.main()


def test_media_cli_nonroot_rejected_before_quiescence_or_ledger(monkeypatch):
    from haos import owner
    monkeypatch.setattr('sys.argv',['haos-owner','media','list'])
    monkeypatch.setattr(owner.os,'geteuid',lambda:65534)
    def forbidden(*args,**kwargs):raise AssertionError('nonowner reached ledger or service gate')
    monkeypatch.setattr(owner,'stopped',forbidden);monkeypatch.setattr(owner,'MissionStore',forbidden)
    with pytest.raises(PermissionError,match='authenticate'):owner.main()


def test_media_cli_inspect_and_explicit_purge_use_real_private_ledger(monkeypatch,tmp_path,capsys):
    import base64,json
    from haos import owner
    from haos.gateway import GatewayEngine,GatewayPolicy
    from haos.gateway_media import describe
    from haos.store import MissionStore
    config={'version':1,'connectors':[{'id':'line','platform':'line'}],'bindings':[{
        'id':'owner','connector':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,
        'thread':'','identity':'personal','capabilities':['create','read'],'allow_media':True,'generation':'b'*64,'since':1}]}
    event={'platform':'line','sender':'U'+'a'*32,'chat':'U'+'a'*32,'scope':'U'+'d'*32,'thread':'',
        'message_id':'c'*64,'is_bot':False,'text':'Inspect the attached document.'}
    path=tmp_path/'missions.db';store=MissionStore(path);engine=GatewayEngine(store);policy=GatewayPolicy(config)
    payload=b'payload retained until deliberate owner action'
    upload=engine.media.begin(policy,{'connector':'line','envelope':event,'descriptor':describe(payload,'document')})
    engine.media.chunk(policy,{'id':upload['id'],'offset':0,'data':base64.b64encode(payload).decode()});store.close()
    monkeypatch.setattr(owner.os,'geteuid',lambda:0);monkeypatch.setattr(owner,'stopped',lambda:None)
    from haos import gateway_setup
    from haos.gateway_media import GatewayMedia
    def private_helper(args,public_policy):
        assert public_policy=={'version':1,'connectors':[],'bindings':[]}
        ledger=MissionStore(path)
        try:
            media=GatewayMedia(ledger)
            if args.gateway_action=='media-list':return media.inventory()
            result=media.purge(args.ids,'owner:1000',args.note,confirmed=args.confirmed)
            owner.audit('gateway.media.purged',{'ids':result['ids']})
            return result
        finally:ledger.close()
    monkeypatch.setattr(gateway_setup,'owner_delivery',private_helper)
    audit=[];monkeypatch.setattr(owner,'audit',lambda kind,details:audit.append((kind,details)))
    monkeypatch.setattr('sys.argv',['haos-owner','media','list']);owner.main()
    assert json.loads(capsys.readouterr().out)['stored_bytes']==len(payload)
    monkeypatch.setattr('sys.argv',['haos-owner','media','purge','--id',upload['id'],'--note','Inspected staged upload'])
    with pytest.raises(PermissionError):owner.main()
    assert not audit
    monkeypatch.setattr('sys.argv',['haos-owner','media','purge','--id',upload['id'],'--note','Inspected staged upload','--confirm-inspected'])
    owner.main();result=json.loads(capsys.readouterr().out)
    assert result['removed_payload_bytes']==len(payload) and len(audit)==1
    store=MissionStore(path)
    try:
        assert store.db.execute('SELECT state FROM gateway_media_uploads').fetchone()[0]=='purged'
        assert store.db.execute('SELECT COUNT(*) FROM gateway_media_chunks').fetchone()[0]==0
    finally:store.close()
