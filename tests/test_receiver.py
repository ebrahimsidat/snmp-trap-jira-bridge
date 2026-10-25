"""End-to-end test: send a real SNMPv2c trap over UDP and receive it."""

from __future__ import annotations

import asyncio
import socket

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    NotificationType,
    ObjectIdentity,
    ObjectType,
    OctetString,
    SnmpEngine,
    UdpTransportTarget,
    send_notification,
)

from trapbridge.config import ListenerConfig, SnmpConfig
from trapbridge.models import Trap
from trapbridge.receiver import TrapReceiver


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def test_receives_v2c_trap_end_to_end() -> None:
    port = free_udp_port()
    queue: asyncio.Queue[Trap] = asyncio.Queue()
    receiver = TrapReceiver(
        SnmpConfig(listeners=(ListenerConfig("lab", "127.0.0.1", port),), communities=("testcomm",)),
        queue,
    )
    receiver.start()
    sender = SnmpEngine()
    try:
        error_indication, *_ = await send_notification(
            sender,
            CommunityData("testcomm"),
            await UdpTransportTarget.create(("127.0.0.1", port)),
            ContextData(),
            "trap",
            NotificationType(ObjectIdentity("1.3.6.1.6.3.1.1.5.3")).add_varbinds(
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.5.0"), OctetString("router-9"))
            ),
        )
        assert error_indication is None
        trap = await asyncio.wait_for(queue.get(), timeout=5)
    finally:
        sender.close_dispatcher()
        receiver.stop()

    assert trap.listener == "lab"
    assert trap.sender == "127.0.0.1"
    assert trap.trap_oid == "1.3.6.1.6.3.1.1.5.3"
    assert trap.varbinds["1.3.6.1.2.1.1.5.0"] == "router-9"
