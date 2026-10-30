"""Actual event-loop/SQLite affinity and ended private operation capabilities."""
import asyncio
import sqlite3
import threading
import warnings

import pytest

from haos.gateway_google_chat_file_http import OnLoop


def test_sdk_worker_thread_checks_SQLite_and_owner_authority_on_the_owning_loop_thread():
    async def run():
        guard=OnLoop();thread=threading.get_ident();db=sqlite3.connect(':memory:')
        try:
            def checked():
                assert threading.get_ident()==thread
                return db.execute('SELECT 123').fetchone()[0]
            assert await asyncio.to_thread(guard.call,checked)==123
            assert guard.call(checked)==123
        finally:guard.closed.set();db.close()
    asyncio.run(run())


def test_cancelled_or_closed_file_capability_refuses_both_threads_before_any_SQLite_or_network_callback():
    async def run():
        guard=OnLoop();guard.closed.set()
        def forbidden():pytest.fail('ended capability reached an operation')
        with pytest.raises(PermissionError):guard.call(forbidden)
        with pytest.raises(PermissionError):await asyncio.to_thread(guard.call,forbidden)
    asyncio.run(run())


def test_worker_call_after_actual_event_loop_close_fails_without_leaking_an_unawaited_coroutine():
    async def create():return OnLoop()
    guard=asyncio.run(create())
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter('always')
        with pytest.raises(PermissionError):guard.call(lambda:pytest.fail('closed loop callback ran'))
        assert not seen
