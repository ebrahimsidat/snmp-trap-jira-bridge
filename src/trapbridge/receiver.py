"""SNMP notification receiver (v2c and v3) built on pysnmp's asyncio engine.

Each configured listener gets its own UDP transport and transport domain, so a
trap can be attributed to the listener (and therefore the upstream system)
that received it. Received traps are placed on an ``asyncio.Queue``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import ntfrcv

from trapbridge.config import SnmpConfig
from trapbridge.models import Trap

log = logging.getLogger(__name__)

SNMP_TRAP_OID = "1.3.6.1.6.3.1.1.4.1.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

_AUTH = {
    "sha": config.USM_AUTH_HMAC96_SHA,
    "sha224": config.USM_AUTH_HMAC128_SHA224,
    "sha256": config.USM_AUTH_HMAC192_SHA256,
    "sha384": config.USM_AUTH_HMAC256_SHA384,
    "sha512": config.USM_AUTH_HMAC384_SHA512,
}
_PRIV = {
    "aes128": config.USM_PRIV_CFB128_AES,
    "aes192": config.USM_PRIV_CFB192_AES,
    "aes256": config.USM_PRIV_CFB256_AES,
}


def varbinds_to_trap(listener: str, sender: str, var_binds: Any) -> Trap:
    """Convert pysnmp var-binds to a :class:`Trap` (OIDs and values as strings)."""
    values: dict[str, str] = {}
    trap_oid = ""
    for oid, value in var_binds:
        oid_text = str(oid).lstrip(".")
        if oid_text == SNMP_TRAP_OID:
            trap_oid = str(value.prettyPrint() if hasattr(value, "prettyPrint") else value).lstrip(".")
        elif oid_text != SYS_UPTIME:
            values[oid_text] = value.prettyPrint() if hasattr(value, "prettyPrint") else str(value)
    return Trap(listener=listener, sender=sender, trap_oid=trap_oid or "unknown", varbinds=values)


class TrapReceiver:
    def __init__(self, cfg: SnmpConfig, queue: asyncio.Queue[Trap]) -> None:
        self._cfg = cfg
        self._queue = queue
        self._engine = engine.SnmpEngine()
        self._domains: dict[tuple[int, ...], str] = {}

    def start(self) -> None:
        for index, listener in enumerate(self._cfg.listeners, start=1):
            domain = (*udp.DOMAIN_NAME, index)
            transport = udp.UdpTransport().open_server_mode((listener.host, listener.port))
            config.add_transport(self._engine, domain, transport)
            self._domains[domain] = listener.name
            log.info("listening for traps on udp/%s:%d as '%s'", listener.host, listener.port, listener.name)

        for index, community in enumerate(self._cfg.communities, start=1):
            config.add_v1_system(self._engine, f"community-{index}", community)

        for user in self._cfg.v3_users:
            if user.auth_protocol not in _AUTH or user.priv_protocol not in _PRIV:
                raise ValueError(f"unsupported SNMPv3 protocols for user {user.username}")
            config.add_v3_user(
                self._engine,
                user.username,
                _AUTH[user.auth_protocol],
                user.auth_key,
                _PRIV[user.priv_protocol],
                user.priv_key,
            )

        ntfrcv.NotificationReceiver(self._engine, self._on_notification)

    def _on_notification(
        self,
        snmp_engine: engine.SnmpEngine,
        state_reference: Any,
        context_engine_id: Any,
        context_name: Any,
        var_binds: Any,
        cb_ctx: Any,
    ) -> None:
        domain, address = snmp_engine.message_dispatcher.get_transport_info(state_reference)
        listener = self._domains.get(tuple(domain), "unknown")
        trap = varbinds_to_trap(listener, str(address[0]), var_binds)
        try:
            self._queue.put_nowait(trap)
        except asyncio.QueueFull:
            log.error("trap queue full; dropping trap %s from %s", trap.trap_oid, trap.sender)

    def stop(self) -> None:
        self._engine.close_dispatcher()
