"""Hold the pinned PTB polling offset until native HAOS admission finishes."""
import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

_CURRENT = ContextVar('haos_telegram_admission', default=None)
_APPLICATIONS = {}


def failed():
    state = _CURRENT.get()
    if state is not None:
        state.failed = True


def admitted():
    state = _CURRENT.get()
    if state is not None:
        state.resolved = True


def accept_native(adapter, original):
    state = _CURRENT.get()
    # Hermes's native text dispatcher marks handoff BEFORE calling its agent
    # dispatcher. HAOS's actual handoff is the synchronous durable inbox write.
    if state is None or state.resolved:
        return original(adapter)


def install(application):
    from telegram import Update
    from telegram.error import NetworkError
    original = type(application)
    if isinstance(application.update_queue, AdmissionQueue):
        return
    if original not in _APPLICATIONS:
        class DurableApplication(original):
            __slots__ = ()
            async def process_error(self, *args, **kwargs):
                failed()
                return await super().process_error(*args, **kwargs)
        _APPLICATIONS[original] = DurableApplication
    application.__class__ = _APPLICATIONS[original]
    queue = AdmissionQueue(application, Update, NetworkError)
    application.update_queue = queue
    application.updater.update_queue = queue


class AdmissionQueue(asyncio.Queue):
    """Actual Updater awaits put before it confirms getUpdates' next offset.

    Dispatch directly through Application.process_update, serially and using its
    native handlers. The ordinary queue remains for PTB's own shutdown sentinel.
    No process-wide SDK patch, alternate Bot client or transport receipt mock.
    """
    def __init__(self, application, update_type, network_error):
        super().__init__()
        self.application, self.update_type, self.network_error = application, update_type, network_error
        self.lock = asyncio.Lock()

    async def put(self, update):
        if not isinstance(update, self.update_type):
            return await super().put(update)
        async with self.lock:
            state = SimpleNamespace(failed=False, resolved=False)
            token = _CURRENT.set(state)
            try:
                await self.application.process_update(update)
                if state.failed:
                    raise self.network_error('HAOS local durable admission unavailable; update remains unconfirmed')
            finally:
                _CURRENT.reset(token)
