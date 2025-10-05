import types
import pytest

from agents.protocol import acl_handler
from agents.protocol.acl_messages import AclMessage

class DummyBehaviour:
    def __init__(self, seq=None):
        # seq: lista wartości zwracanych przez receive; tu same None (idle)
        self._seq = list(seq or [])
        self._killed = False
        self.acl_handler_timeout = 0.001  # szybkie ticky
        self.acl_max_idle_ticks = 3       # po 3 pustych cyklach zabij

    async def receive(self, timeout=None):
        if self._seq:
            return self._seq.pop(0)
        return None

    async def kill(self):
        self._killed = True

def test_idle_guard_kills_after_n_ticks(asyncio_event_loop):
    beh = DummyBehaviour(seq=[None, None, None, None])  # 4 puste ticky

    @acl_handler
    async def on_msg(self, acl: AclMessage, raw_msg):
        # nie powinno wejść (bo nie ma wiadomości)
        assert False, "should not be called"

    # odpalamy wrapper parę razy; po 3-cim powinno zabić behaviour
    for _ in range(4):
        asyncio_event_loop.run_until_complete(on_msg(beh))

    assert beh._killed is True, "behaviour should be killed after idle ticks"
