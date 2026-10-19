"""Disabled-by-default mTLS observation; fixed GET routes and private captures."""
import asyncio
from collections import deque
import json
import re
import ssl
import time

from .remote_policy import certificate_identity,mission_id
from .remote_control import REPLY_LIMIT

HTML=b'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>HAOS observation</title><link rel="stylesheet" href="/viewer.css"><h1>Hermes workspace</h1><p id="status">Authenticating device...</p><label>Shared mission <select id="missions"></select></label><p id="mission"></p><section id="applications"></section><h2>Actual mission events</h2><pre id="events"></pre><script src="/viewer.js"></script></html>'''
CSS=b'body{background:#091426;color:#dae7ff;font:16px system-ui;margin:1em;max-width:1100px}select{max-width:95%;padding:.5em}section{display:flex;flex-wrap:wrap;gap:1em}article{max-width:100%;border:1px solid #446;padding:.5em}img{max-width:100%;max-height:65vh;pointer-events:none}pre{white-space:pre-wrap;overflow-wrap:anywhere}p{overflow-wrap:anywhere}'
JS='''"use strict";
const status=document.getElementById("status"), select=document.getElementById("missions"), activity=document.getElementById("applications"), events=document.getElementById("events");
let cursor=0, selected="", generation=0, history=[], frames=[];
async function read(path){const r=await fetch(path,{cache:"no-store",credentials:"same-origin"});if(!r.ok)throw Error("Observation unavailable or device access expired");return await r.json();}
function clear(){activity.replaceChildren();frames=[];}
function capture(data){clear();for(const app of data.applications||[]){const card=document.createElement("article"),caption=document.createElement("p");caption.textContent=app.program+" / "+app.instance+" — last verified capture";card.append(caption);const at=app.capture_at*1000;if(data.mission_active && Number.isFinite(at) && Date.now()-at>=0 && Date.now()-at<15000 && typeof app.jpeg==="string" && app.jpeg.length<=1398104 && /^[A-Za-z0-9+/]+={0,2}$/.test(app.jpeg) && app.jpeg.startsWith("/9j/")){const img=document.createElement("img");img.alt="Actual private application capture";img.draggable=false;img.src="data:image/jpeg;base64,"+app.jpeg;card.append(img);frames.push({img,at});}else{const unavailable=document.createElement("p");unavailable.textContent="No recent shared capture";card.append(unavailable);}activity.append(card);}}
select.onchange=()=>{selected=select.value;cursor=0;history=[];events.textContent="";generation++;clear();};
setInterval(()=>{for(const frame of frames)if(Date.now()-frame.at>=15000){frame.img.removeAttribute("src");frame.img.remove();}},1000);
async function poll(){const epoch=generation;try{if(!selected){const missions=await read("/api/missions");select.replaceChildren();for(const m of missions){const option=document.createElement("option");option.value=m.id;option.textContent=m.id+" / "+m.state;select.append(option);}selected=select.value;if(!selected){status.textContent="No shared mission available";return;}}const mid=selected, info=await read("/api/mission/"+encodeURIComponent(mid));if(epoch!==generation)return;document.getElementById("mission").textContent=info.state+(info.goal?" — "+info.goal:"");const rows=await read("/api/events/"+encodeURIComponent(mid)+"?after="+cursor);if(epoch!==generation)return;for(const row of rows){cursor=Math.max(cursor,row.seq);history.push(JSON.stringify(row).slice(0,65536));}history=history.slice(-100);events.textContent=history.join("\\n");try{const apps=await read("/api/applications/"+encodeURIComponent(mid));if(epoch===generation)capture(apps);}catch(_){clear();}status.textContent="Authenticated observation; last poll "+new Date().toLocaleTimeString();}catch(e){clear();status.textContent=e.message;}finally{setTimeout(poll,2000);}}
poll();'''.encode('utf-8')


def route(target):
    if target=='/api/missions':return 'missions.list',{}
    match=re.fullmatch(r'/api/(mission|events|applications)/([a-f0-9-]{36})(?:\?after=([0-9]{1,19}))?',target)
    if not match:raise PermissionError('fixed read-only route required')
    kind,mid,after=match.groups();mission_id(mid)
    if kind=='events':
        if after is None or int(after)>=2**63:raise ValueError('bounded event cursor required')
        return 'missions.events',{'id':mid,'after':int(after)}
    if after is not None:raise PermissionError('unexpected remote query denied')
    return ('missions.get' if kind=='mission' else 'applications.snapshot'),{'id':mid}


class RateBudget:
    def __init__(self):self.samples={}
    def reserve(self,identity,policy,size=0,*,request=False):
        now=time.monotonic();samples=self.samples.setdefault(identity,deque())
        while samples and samples[0][0]<=now-60:samples.popleft()
        if (sum(v[1] for v in samples)+int(request)>policy.value['requests_per_minute']
                or sum(v[2] for v in samples)+size>policy.value['bytes_per_minute']):
            raise OverflowError('remote observation rate budget exceeded')
        samples.append((now,int(request),size))
        # Only authenticated owner-paired devices reach this map. Expired grants
        # cannot retain unbounded per-identity state after pairing changes.
        for old in list(self.samples):
            if old not in policy.devices:self.samples.pop(old,None)


def tls_context(cert,key,ca):
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_3
    context.load_cert_chain(cert,key)
    context.load_verify_locations(cafile=ca)
    context.verify_mode=ssl.CERT_REQUIRED
    context.options|=ssl.OP_NO_COMPRESSION
    return context


class Viewer:
    def __init__(self,policy,request):
        self.policy=policy;self.request=request;self.budget=RateBudget();self.connections=0

    async def client(self,reader,writer):
        self.connections+=1
        try:
            if self.connections>32:raise OverflowError('remote connection budget exceeded')
            tls=writer.get_extra_info('ssl_object')
            if tls is None:raise PermissionError('authenticated encrypted transport required')
            identity=certificate_identity(tls.getpeercert(binary_form=True))
            policy=self.policy();policy.authorize(identity)
            self.budget.reserve(identity,policy,request=True)
            raw=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),3)
            if len(raw)>8192:raise ValueError('remote headers budget exceeded')
            lines=raw.decode('ascii').split('\r\n');match=re.fullmatch(r'GET (/[!-~]{0,250}) HTTP/1\.[01]',lines[0])
            if not match:raise PermissionError('read-only GET required')
            headers={}
            for line in lines[1:-2]:
                key,separator,value=line.partition(':');key=key.lower()
                if not separator or not re.fullmatch('[a-z0-9-]{1,64}',key) or key in headers or '\t' in value:
                    raise PermissionError('unambiguous fixed HTTP headers required')
                headers[key]=value.strip()
            host=headers.get('host','')
            if (not re.fullmatch(r'[A-Za-z0-9.\[\]:-]{1,253}',host) or headers.get('content-length','0')!='0'
                    or 'transfer-encoding' in headers or headers.get('sec-fetch-site')=='cross-site'
                    or headers.get('origin','https://'+host)!='https://'+host):
                raise PermissionError('cross-origin or body-bearing remote request denied')
            target=match[1]
            assets={'/':(HTML,'text/html; charset=utf-8'),'/viewer.js':(JS,'text/javascript; charset=utf-8'),'/viewer.css':(CSS,'text/css; charset=utf-8')}
            if target in assets:body,mime=assets[target]
            else:
                method,params=route(target)
                if 'id' in params:policy.authorize(identity,params['id'])
                value=await self.request({'method':method,'device':identity,'params':params})
                body=json.dumps(value,ensure_ascii=False).encode();mime='application/json; charset=utf-8'
            if len(body)>REPLY_LIMIT:raise ValueError('remote response exceeds size limit')
            # Revocation/expiry is enforced on established TLS connections too,
            # independently of certificate validity and controller authorization.
            current=self.policy();current.authorize(identity)
            if target not in assets and 'id' in params:current.authorize(identity,params['id'])
            self.budget.reserve(identity,current,len(body))
            await self.respond(writer,200,body,mime)
        except OverflowError:
            await self.respond(writer,429,b'Observation budget exceeded','text/plain')
        except Exception:
            await self.respond(writer,403,b'Observation unavailable or denied','text/plain')
        finally:
            self.connections-=1;writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),1)
            except Exception:pass

    async def respond(self,writer,status,body,mime):
        header=(f'HTTP/1.1 {status} Response\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\n'
            'Connection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n'
            'Strict-Transport-Security: max-age=31536000\r\n'
            "Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'\r\n\r\n").encode()
        try:
            writer.write(header+body);await asyncio.wait_for(writer.drain(),3)
        except Exception:pass
