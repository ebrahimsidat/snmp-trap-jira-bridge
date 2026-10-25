# Operations runbook

## Service management

```bash
sudo systemctl status trapbridge
sudo journalctl -u trapbridge -f             # follow logs
sudo journalctl -u trapbridge --since "1 hour ago" -o cat | jq .   # JSON logs
```

## Validating a configuration change

```bash
sudo -u trapbridge /opt/trapbridge/venv/bin/trapbridge --config /etc/trapbridge/config.yaml --check
sudo systemctl restart trapbridge
```

The unit also runs `--check` before every start, so an invalid configuration prevents start-up
instead of producing a running service that cannot ticket.

## Testing a rule end to end

```bash
# v2c
snmptrap -v 2c -c "$COMMUNITY" <host>:1162 '' 1.3.6.1.6.3.1.1.5.3 1.3.6.1.2.1.2.2.1.1 i 3

# v3 (authPriv)
snmptrap -v 3 -l authPriv -u trapbridge -a SHA-256 -A "$AUTH" -x AES -X "$PRIV" \
  <host>:1162 '' 1.3.6.1.6.3.1.1.5.3
```

Expected log sequence: `opened <ISSUE-KEY> for <listener>:<host>`.

## Common situations

| Symptom | Likely cause | Action |
|---|---|---|
| `no rule for trap ...; ignored` | Trap OID not covered by a rule | Add a rule, or confirm the trap should be ignored |
| `startup validation: field ... is not on request type` | Jira request type changed | Update `jira.extra_fields` / `severity_field`, or the request type |
| `jira rejected fields [...]; retrying without them` | Field value invalid for the request type | Correct `severity_values`; tickets are still being created |
| `jira create failed for ...` followed by `pagerduty trigger sent for ...` | Jira unreachable | On-call has been paged; tickets are created automatically when Jira recovers |
| `no pager configured; alert ... was not delivered` | Jira down and PagerDuty not configured | Configure the `pagerduty` section |
| `trap queue full` | Sustained trap storm beyond processing capacity | Investigate the source; consider rate-limiting at the network element |

## State file

Open incidents and ticket mappings are stored in `/var/lib/trapbridge/state.json` and written atomically
after every change. Deleting the file while the service is stopped resets correlation; existing tickets
are not affected but will no longer receive updates.
