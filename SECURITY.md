# Security policy

## Supported versions

Security fixes are applied to the latest release of `snmp-trap-jira-bridge`.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Report them privately through
GitHub's [private vulnerability reporting](https://github.com/ebrahimsidat/snmp-trap-jira-bridge/security/advisories/new).

Include a description of the issue, steps to reproduce, and the potential impact. You can expect an
acknowledgement within five business days and a remediation plan once the report has been assessed.

## Secure development practices

- Every change runs automated linting and security scanning in continuous integration
- Dependencies are monitored by Dependabot and updated through reviewed pull requests
- Secrets are never committed; examples use placeholders and environment variables
