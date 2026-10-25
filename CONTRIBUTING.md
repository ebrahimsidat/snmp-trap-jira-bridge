# Contributing

Thank you for your interest in improving `snmp-trap-jira-bridge`.

## Workflow

1. Open an issue describing the bug or enhancement before starting significant work.
2. Fork the repository and create a branch from `main` (for example `feature/short-description`).
3. Make focused commits with clear messages in the imperative mood ("Add retry limit", not "Added").
4. Run the checks locally before opening a pull request:

   ```bash
   make check
   ```

5. Open a pull request that references the issue and explains what changed and how it was tested.

## Standards

- Changes must pass continuous integration (linting, tests and security checks).
- New behaviour includes tests or a documented verification procedure.
- User-facing changes update the README or documentation and the CHANGELOG.
- Never commit credentials, hostnames or data from a real environment.
