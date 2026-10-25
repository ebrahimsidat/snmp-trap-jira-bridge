# Roadmap

## Released

- **1.0** — SNMP v2c/v3 receiver, rule mapping, node-level correlation, clear hold-down,
  Jira Service Management integration, self-healing requests, start-up validation,
  PagerDuty fail-over, state persistence, hardened systemd unit and container image

## Planned

| Version | Item | Value |
|---|---|---|
| 1.1 | Prometheus `/metrics` endpoint (traps received, actions, Jira latency, errors) | Observability of the bridge itself |
| 1.1 | Hot reload of rules on `SIGHUP` | Rule changes without dropping traps |
| 1.2 | Automated remediation hooks: run an Ansible playbook on selected rules and attach the result to the ticket | Faster restoration and richer evidence for Level 2 support |
| 1.2 | Maintenance windows (suppress ticketing for listed hosts and time ranges) | Fewer tickets during planned work |
| 1.3 | Additional back-ends: ServiceNow incident API, generic webhook | Reuse in non-Jira environments |
| 1.3 | MIB-aware rendering of varbind names | More readable ticket descriptions |

Suggestions are welcome through the issue tracker.
