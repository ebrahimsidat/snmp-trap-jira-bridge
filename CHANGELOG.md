# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-25

### Added

- SNMP v2c and v3 trap receiver with multiple attributed listeners
- Rule-based mapping of trap OIDs to severity, summary and host
- Node-level correlation with rate-limited repeat comments and escalation notes
- Clear hold-down to absorb reboot and link flapping
- Jira Service Management client with retries, self-healing field handling and start-up validation
- PagerDuty Events v2 fail-over when Jira is unavailable
- Atomic state persistence across restarts
- Hardened systemd unit, non-root container image and CI pipeline
