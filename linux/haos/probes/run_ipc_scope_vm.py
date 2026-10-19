"""Actual production scope probe; only the marked diskless VM's UID-1000 child.

The companion PID-1 init creates both host/named listeners before dropping UID.
Do not execute this probe as host provisioning. No model or installed HAOS proof.
"""
import sys,os,socket,json,errno,hashlib,stat
marker=os.lstat('/haos-disposable-ipc-marker')
assert stat.S_ISREG(marker.st_mode) and marker.st_uid==0 and marker.st_nlink==1 and stat.S_IMODE(marker.st_mode)==0o400
assert os.getuid()==1000
sys.path.insert(0,'/modules')
from ipc_scope import restrict_abstract_sockets
assert os.getuid()==1000
host=b'\0haos-scope-fixture-host'
before=socket.socket(socket.AF_UNIX);before.connect(host);before.close()
abi=restrict_abstract_sockets()
after=socket.socket(socket.AF_UNIX)
try:
    after.connect(host)
except OSError as error:
    assert error.errno==errno.EPERM
else: raise AssertionError('host abstract connection accepted after scope')
finally: after.close()
named=socket.socket(socket.AF_UNIX);named.connect('/tmp/haos-named.sock');named.close()
owned=socket.socket(socket.AF_UNIX);owned.bind(b'\0haos-python-domain-owned');owned.listen(4)
pid=os.fork()
if pid==0:
    fd=socket.socket(socket.AF_UNIX);fd.connect(b'\0haos-python-domain-owned');fd.close();os._exit(0)
assert os.waitpid(pid,0)==(pid,0)
owned.close()
print('HAOS_SCOPE_PYTHON_RECEIPT='+json.dumps({'actual_product_module':True,'module_sha256':hashlib.sha256(open('/modules/ipc_scope.py','rb').read()).hexdigest(),'abi':abi,'uid':os.getuid(),'host_abstract_allowed_before_scope':True,'host_abstract_denied_after_scope':True,'filesystem_controller_socket_allowed':True,'descendant_same_domain_abstract_allowed':True}),flush=True)
