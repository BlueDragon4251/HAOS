#!/usr/bin/env python3
"""Native accumulator → pinned wire builders; synthetic signed/encrypted data only."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,sys.argv[1])
from types import SimpleNamespace as N
from haos.provider_profiles import register_profiles
from haos.provider_moa_streams import _final_delta
from agent.transports import get_transport
from agent.reasoning_summaries import append_streamed_reasoning_detail
for provider, mode, model, endpoint in [('anthropic','anthropic_messages','claude-sonnet-4-6','https://api.anthropic.com'),('openai','codex_responses','gpt-5','https://api.openai.com/v1')]:
 register_profiles({'version':1,'provider':provider,'endpoint':endpoint,'models':[model],'default_model':model,'api_mode':mode,'requests_per_day':200,'requests_per_minute':30})
 t=get_transport(mode); base='http://127.0.0.1:9120/v1'
 if provider=='anthropic':
  data={'anthropic_content_blocks':[{'type':'thinking','thinking':'fixture','signature':'signed-fixture'},{'type':'tool_use','id':'call_fixture','name':'fixture','input':{'x':1}}]}
 else:
  data={'codex_reasoning_items':[{'id':'rs_fixture','type':'reasoning','summary':[],'encrypted_content':'encrypted-fixture'}]}
 d=_final_delta(N(provider_data=data,tool_calls=None),t,base,model)
 details=[]
 for item in d['reasoning_details']: append_streamed_reasoning_detail(details,item)
 msg={'role':'assistant','content':'','reasoning_details':details,'tool_calls':[{'id':'call_fixture','type':'function','function':{'name':'fixture','arguments':'{"x":1}'}}]}
 messages=[{'role':'user','content':'fixture'},msg,{'role':'tool','tool_call_id':'call_fixture','content':'ok'},{'role':'user','content':'next'}]
 wire=t.build_kwargs(model,messages,base_url=base,provider='custom',max_tokens=64)
 encoded=json.dumps(wire)
 assert ('signed-fixture' if provider=='anthropic' else 'encrypted-fixture') in encoded
 assert 'haos.moa.native_assistant' not in encoded
 if provider=='anthropic':
  assert wire['messages'][1]['content']==data['anthropic_content_blocks']
 else:
  assert any(item.get('encrypted_content')=='encrypted-fixture' for item in wire['input'])
 # A changed owner model or endpoint must never reuse the opaque native replay.
 for changed in ('model','endpoint'):
  changed_model=model+'-other' if changed=='model' else model
  if changed=='endpoint':
   original=t.haos_wire_context
   t.haos_wire_context=lambda _: (original(base)[0],mode,endpoint+'/other')
  negative=t.build_kwargs(changed_model,messages,base_url=base,provider='custom',max_tokens=64)
  assert 'signed-fixture' not in json.dumps(negative) and 'encrypted-fixture' not in json.dumps(negative)
  if changed=='endpoint':
   t.haos_wire_context=original
 # The ordinary chat codec must strip the carrier even on reasoning-capable hosts.
 chat=get_transport('chat_completions').build_kwargs(model,messages,base_url=base,provider='custom',max_tokens=64)
 assert 'haos.moa.native_assistant' not in json.dumps(chat)
 assert messages[1]['reasoning_details']==details
results={'native_accumulator_and_wire_protocols':2,'model_endpoint_negative_checks':4,
 'other_protocol_negative_checks':2,'live_provider_tested':False,
 'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (
  Path(__file__),Path(sys.argv[1])/'haos/provider_moa_streams.py',Path(sys.argv[1])/'haos/provider_profiles.py')}}
Path(sys.argv[2]).write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results))
