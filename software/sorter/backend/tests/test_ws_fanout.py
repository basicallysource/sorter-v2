"""The websocket fan-out: encoded once, latest version wins, slow clients closed."""

import asyncio

import server.shared_state as shared_state


class _Socket:
    """Records what it is sent; a stuck one never finishes a send."""

    client = None

    def __init__(self, stuck: bool = False) -> None:
        self.sent: list[str] = []
        self.stuck = stuck

    async def send_text(self, text: str) -> None:
        if self.stuck:
            await asyncio.Event().wait()
        self.sent.append(text)


def test_a_client_gets_only_the_latest_version_of_each_message() -> None:
    async def run() -> list[str]:
        socket = _Socket()
        client = shared_state.WsClient(socket)
        for n in range(3):
            client.push("runtime_stats", f"stats {n}")
            client.push("known_object:a", f"piece a {n}")
        sender = asyncio.ensure_future(client.send())
        await asyncio.sleep(0.01)
        sender.cancel()
        return socket.sent

    assert asyncio.run(run()) == ["stats 2", "piece a 2"]


def test_a_client_that_takes_nothing_is_closed_and_the_others_carry_on(monkeypatch) -> None:
    monkeypatch.setattr(shared_state, "WS_SLOW_CLIENT_LIMIT_S", 0.05)

    async def run() -> tuple[bool, list[str]]:
        healthy = _Socket()
        clients = [shared_state.WsClient(_Socket(stuck=True)), shared_state.WsClient(healthy)]
        senders = [asyncio.ensure_future(client.send()) for client in clients]
        for client in clients:
            client.push("heartbeat", "ping")
        await asyncio.wait_for(senders[0], 1.0)
        healthy_still_sending = not senders[1].done()
        senders[1].cancel()
        return healthy_still_sending, healthy.sent

    assert asyncio.run(run()) == (True, ["ping"])


def test_broadcast_encodes_an_event_once_for_every_client(monkeypatch) -> None:
    async def run() -> list[str]:
        monkeypatch.setattr(shared_state, "server_loop", asyncio.get_running_loop())
        clients = [shared_state.WsClient(_Socket()) for _ in range(2)]
        monkeypatch.setattr(shared_state, "ws_clients", set(clients))
        shared_state.broadcast({"tag": "sorter_state", "data": {"state": "paused"}})
        await asyncio.sleep(0)
        return [client.pending["sorter_state"] for client in clients]

    first, second = asyncio.run(run())
    assert first is second
    assert first == '{"tag":"sorter_state","data":{"state":"paused"}}'
