"""Private read-only official CLI boundary; no agent-selected program or verbs."""
import asyncio
import json
import os
import signal

from .gateway_buzz import HEX,credentials,scope
from .gateway_buzz_crypto import command,wire


class QueryFailed(RuntimeError):
    def __init__(self,category):
        self.category=category
        super().__init__('Buzz query failed: '+category)


def selection(args,value,peers):
    """Closed native read grammar. Never forward unknown/duplicate CLI flags."""
    if (not isinstance(args,list) or not 2<=len(args)<=14
            or any(not isinstance(part,str) or len(part)>256 for part in args)):
        raise PermissionError('bounded fixed Buzz query required')
    verb=tuple(args[:2]);options=args[2:]
    allowed={('users','get'):{'--pubkey'},('channels','list'):set(),('dms','list'):set(),
        ('channels','get'):{'--channel'},('channels','members'):{'--channel'},
        ('messages','get'):{'--channel','--limit','--since','--before'}}
    if verb not in allowed or len(options)%2:raise PermissionError('read-only reviewed Buzz CLI operation required')
    flags={}
    for name,part in zip(options[::2],options[1::2]):
        if name not in allowed[verb] or name in flags:raise PermissionError('unknown or repeated Buzz query flag')
        flags[name]=part
    if '--channel' in allowed[verb] and flags.get('--channel') not in value['channels']:
        raise PermissionError('explicit owner-selected Buzz channel required')
    if '--pubkey' in flags and flags['--pubkey'] not in peers|{value['public_key']}:
        raise PermissionError('independently approved Buzz peer required for profile lookup')
    if verb==('messages','get') and '--limit' not in flags:raise PermissionError('bounded Buzz history limit required')
    for name in ['--limit','--since','--before']:
        if name in flags and (not flags[name].isascii() or not flags[name].isdecimal()
                or str(int(flags[name]))!=flags[name] or not 1<=int(flags[name])<=(200 if name=='--limit' else 2**53-1)):
            raise PermissionError('canonical finite Buzz query bound required')
    if '--since' in flags and '--before' in flags and int(flags['--since'])>int(flags['--before']):
        raise PermissionError('ordered Buzz history interval required')
    return verb,flags


class Reader:
    def __init__(self,connector,value,current,redactor):
        from .gateway_runtime import require_runtime_identity,prepare_runtime_home
        require_runtime_identity()
        self.value=credentials(value);self.connector=connector;self.current=current;self.redactor=redactor
        from plugins.platforms.buzz.nostr_auth import public_key_hex
        if public_key_hex(self.value['private_key'])!=self.value['public_key']:
            raise PermissionError('native private Buzz identity differs from expected owner public key')
        self.home=prepare_runtime_home();self.lock=asyncio.Lock();self.authentication_refused=False

    def peers(self):
        policy=self.current()
        if self.connector not in policy.connectors or policy.connectors[self.connector]['platform']!='buzz':
            raise PermissionError('current owner Buzz connector required')
        return {row['sender'] for row in policy.bindings.values() if row['connector']==self.connector
            and row['scope']==scope(self.value) and row['chat'] in self.value['channels']}

    async def run(self,args,*,input_text=None,before_id=None):
        from .gateway_runtime import require_runtime_identity
        require_runtime_identity()
        if input_text is not None:raise PermissionError('read-only Buzz CLI cannot publish content or consume files')
        verb,flags=selection(args,self.value,self.peers())
        if before_id is not None and (verb!=('messages','get') or '--before' not in flags
                or not isinstance(before_id,str) or not HEX.fullmatch(before_id)):
            raise PermissionError('exact composite Buzz history cursor and timestamp required')
        if self.authentication_refused:raise QueryFailed('authentication_refused')
        async with self.lock:
            self.peers()
            if self.authentication_refused:raise QueryFailed('authentication_refused')
            native_args=args+['--kinds','9,45001,45003'] if verb==('messages','get') else args
            out,err,code=await self._execute(native_args,before_id)
            self.peers()
            if code:
                if code==3:self.authentication_refused=True
                # Relay bodies and native stderr never reach logs, Hermes mention
                # fallback matching, or a caller. Read failure is never empty history.
                category='authentication_refused' if code==3 else 'query_unavailable'
                if code==2:
                    try:failure=json.loads(err)
                    except (ValueError,RecursionError):failure=None
                    # The native formatter constructs this status prefix; the
                    # untrusted relay body after it never controls retry verbs.
                    if (isinstance(failure,dict) and failure.get('error')=='relay_error'
                            and isinstance(failure.get('message'),str) and failure['message'].startswith('relay error 429:')):
                        category='rate_limited'
                raise QueryFailed(category)
            from .gateway_line_ingress import _object
            from .gateway_dingtalk_admission import finite
            try:result=json.loads(out,object_pairs_hook=_object,parse_constant=finite)
            except (ValueError,RecursionError):raise QueryFailed('invalid_response') from None
            if self.redactor.text(json.dumps(result,ensure_ascii=False))!=json.dumps(result,ensure_ascii=False):
                raise QueryFailed('private_reflection')
            if verb==('messages','get'):
                if not isinstance(result,list) or len(result)>int(flags['--limit']):raise QueryFailed('invalid_response')
                for event in result:
                    wire(json.dumps(event,separators=(',',':'),ensure_ascii=False).encode())
                    channels=[tag[1] for tag in event['tags'] if tag[0]=='h' and len(tag)>=2]
                    if (channels!=[flags['--channel']] or event['kind'] not in {9,45001,45003}
                            or '--since' in flags and event['created_at']<int(flags['--since'])
                            or '--before' in flags and event['created_at']>int(flags['--before'])
                            or before_id is not None and event['created_at']==int(flags['--before']) and event['id']>=before_id):
                        raise QueryFailed('invalid_response')
                if len({event['id'] for event in result})!=len(result):raise QueryFailed('invalid_response')
                # Signature and independent admission are checked by durable custody
                # before any native dispatch/cursor. This is only a typed query result.
            elif verb==('channels','get'):
                if not isinstance(result,dict) or result.get('channel_id')!=flags['--channel']:raise QueryFailed('invalid_response')
            else:
                if not isinstance(result,list) or len(result)>4096 or any(not isinstance(row,dict) for row in result):raise QueryFailed('invalid_response')
                if verb in {('channels','list'),('dms','list')}:
                    key='dm_id' if verb[0]=='dms' else 'channel_id'
                    result=[row for row in result if row.get(key) in self.value['channels']]
                elif verb==('users','get'):
                    expected=flags.get('--pubkey',self.value['public_key'])
                    if len(result)!=1 or result[0].get('pubkey')!=expected:raise QueryFailed('identity_mismatch')
            return 0,json.dumps(result,separators=(',',':'),ensure_ascii=False),''

    async def _execute(self,args,before_id):
        env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','HOME':str(self.home),'BUZZ_RELAY_URL':self.value['relay_url'],
            'BUZZ_PRIVATE_KEY':self.value['private_key'],'BUZZ_OUTPUT_FORMAT':'json','BUZZ_TIMEOUT_SECS':'10',
            'BUZZ_CONNECT_TIMEOUT_SECS':'5','SSL_CERT_FILE':'/etc/ssl/certs/ca-certificates.crt','TOKIO_WORKER_THREADS':'2'}
        if self.value.get('auth_tag'):env['BUZZ_AUTH_TAG']=self.value['auth_tag']
        if before_id is not None:env['HAOS_BUZZ_BEFORE_ID']=before_id
        process=None;tasks=[]
        async def collect(stream,limit):
            data=bytearray()
            while block:=await stream.read(8192):
                if len(data)+len(block)>limit:raise QueryFailed('response_limit')
                data.extend(block)
            return bytes(data)
        async def revoked():
            while True:
                self.peers();await asyncio.sleep(.1)
        spawn=asyncio.create_task(asyncio.create_subprocess_exec(command('buzz'),*args,stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,cwd=str(self.home),start_new_session=True,limit=16384))
        try:
            async with asyncio.timeout(35):
                process=await asyncio.shield(spawn)
                tasks=[asyncio.create_task(collect(process.stdout,8*1024*1024)),asyncio.create_task(collect(process.stderr,65536)),
                    asyncio.create_task(process.wait()),asyncio.create_task(revoked())]
                # gather propagates watcher/collector failure immediately; finally
                # kills the entire process group, including descendants.
                joined=asyncio.gather(*tasks[:3]);tasks.append(joined)
                done,_=await asyncio.wait([joined,tasks[3]],return_when=asyncio.FIRST_COMPLETED)
                if tasks[3] in done:tasks[3].result()
                return await joined
        except TimeoutError:raise QueryFailed('query_timeout') from None
        finally:
            if process is None:
                try:process=await asyncio.shield(spawn)
                except Exception:pass
            if process is not None:
                # Kill descendants even if the original process already exited.
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                await process.wait()
            for task in tasks:
                if not task.done():task.cancel()
            if tasks:await asyncio.gather(*tasks,return_exceptions=True)
