"""Correlated IRCv3 server echo acceptance; never a recipient delivery receipt."""
import asyncio
from dataclasses import dataclass
from datetime import datetime,timezone
import re
import time

from .gateway_irc_transport import Rejected

DELIVERY_CAPS=frozenset({'echo-message','labeled-response','batch'})
_LABEL=re.compile(r'haos_[0-9a-f]{48}\Z')
_ID=re.compile(r'[A-Za-z0-9_-]{1,128}\Z')


@dataclass
class Ticket:
    label: str
    chat: str
    text: str
    authority: object
    future: asyncio.Future
    started_at: float
    batch: str | None=None
    receipt: str | None=None


class Witness:
    def __init__(self,boundary,current):
        if not callable(current):raise TypeError('current independent outbox authority required')
        self.boundary=boundary;self.current=current;self.pending={};self.batches={}
        if getattr(boundary,'_witness',None) is not None:raise PermissionError('IRC witness already installed')
        boundary._witness=self

    def register(self,label,chat,text,authority):
        if (not isinstance(label,str) or not _LABEL.fullmatch(label) or label in self.pending or len(self.pending)>=16
                or chat!=self.boundary.value['channel'] or not isinstance(text,str) or not text
                or len(text.encode())>510 or any(c in text for c in '\r\n\0')):
            raise PermissionError('exact bounded IRC echo intent required')
        self.boundary.current()
        if not self.boundary.confirmed or not DELIVERY_CAPS<=self.boundary.capabilities:
            raise PermissionError('IRC has no current verified echo/labeled/batch subscription')
        ticket=Ticket(label,chat,text,authority,asyncio.get_running_loop().create_future(),time.time())
        self.current(ticket);self.pending[label]=ticket;return ticket

    def release(self,ticket):
        self.pending.pop(ticket.label,None)
        if ticket.batch is not None:self.batches.pop(ticket.batch,None)
        if not ticket.future.done():ticket.future.cancel()
        elif not ticket.future.cancelled():ticket.future.exception()

    def reject(self,ticket):
        if not ticket.future.done():ticket.future.set_exception(Rejected('IRC correlated server acceptance unavailable'))

    def observe(self,raw):
        msg=self.boundary.parse(raw);tags=msg['tags'];params=msg['params'];command=msg['command']
        label=tags.get('label');batch=tags.get('batch')
        if label is not None and batch is not None:
            ticket=self.pending.get(label)
            if ticket:self.reject(ticket)
            return False
        if command=='BATCH':
            if not params or not isinstance(params[0],str) or len(params[0])<2:return False
            sign,reference=params[0][0],params[0][1:]
            if sign=='+':
                ticket=self.pending.get(label)
                if ticket is None:return False
                try:
                    self.current(ticket)
                    if (not msg['prefix'] or any(c in msg['prefix'] for c in '!@')
                            or params!=['+'+reference,'labeled-response'] or not _ID.fullmatch(reference)
                            or reference in self.batches or ticket.batch is not None or ticket.receipt is not None):
                        raise Rejected('invalid IRC labeled-response batch')
                    ticket.batch=reference;self.batches[reference]=ticket.label
                except Exception:self.reject(ticket)
                return True
            if sign=='-' and reference in self.batches:
                ticket=self.pending.get(self.batches[reference])
                if ticket is None:return False
                try:
                    self.current(ticket)
                    if (not msg['prefix'] or any(c in msg['prefix'] for c in '!@')
                            or params!=['-'+reference] or label is not None or ticket.receipt is None):
                        raise Rejected('IRC batch has no complete matching echo')
                    if not ticket.future.done():ticket.future.set_result(ticket.receipt)
                except Exception:self.reject(ticket)
                return True
            return False
        if batch is not None:label=self.batches.get(batch)
        ticket=self.pending.get(label)
        if ticket is None:return False
        try:
            self.current(ticket)
            if command!='PRIVMSG':
                # ACK by itself confirms processing, not message publication.
                raise Rejected('IRC labeled response has no matching server echo')
            if (ticket.receipt is not None or params!=[ticket.chat,ticket.text]
                    or msg['prefix'].split('!',1)[0]!=self.boundary.value['nickname']
                    or not re.fullmatch(r'[^\s!@:]+![^\s!@:]+@[^\s!@:]+',msg['prefix'])
                    or not isinstance(tags.get('msgid'),str) or not _ID.fullmatch(tags['msgid'])
                    or not isinstance(tags.get('account'),str)
                    or not (tags['account']=='*' or re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}',tags['account']))
                    or self.boundary.value.get('sasl_username') and tags['account']!=self.boundary.value['sasl_username']
                    or batch is not None and ticket.batch!=batch
                    or batch is None and ticket.batch is not None):
                raise Rejected('IRC echo changed sender, route, content or identity')
            original=datetime.fromisoformat(tags.get('time',''))
            if (original.tzinfo is None or original.utcoffset() is None
                    or original.timestamp()<ticket.started_at-300 or original.timestamp()>time.time()+300):
                raise Rejected('IRC echo has no bounded original server time')
            ticket.receipt=tags['msgid']
            if ticket.batch is None and not ticket.future.done():ticket.future.set_result(ticket.receipt)
        except Exception:self.reject(ticket)
        # Let global throttle/auth controls close or defer the connection too.
        return command not in {'263','439','464','465','900','901','902','904','905','906','907'}

    def disconnected(self):
        for ticket in list(self.pending.values()):self.reject(ticket)

    def close(self):
        for ticket in list(self.pending.values()):self.reject(ticket);self.release(ticket)
