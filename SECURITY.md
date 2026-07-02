# Security Policy

## Supported Versions

ProteinClaw is V1.0. Security fixes are applied to the current `main` branch.

## Reporting a Vulnerability

Report vulnerabilities privately through GitHub Security Advisories for this
repository. Do not open a public issue for a suspected vulnerability.

Include:

- Affected version or commit.
- Steps to reproduce.
- Impact and affected surfaces.
- Any relevant logs, inputs, or generated artifacts with secrets removed.

The maintainer will acknowledge valid reports as quickly as practical, triage
severity, and coordinate a fix before public disclosure.

## Scope

Security-sensitive areas include MCP tool execution, filesystem access, Docker
container invocation, generated artifacts, dependency handling, and plugin
metadata. Scientific model quality issues are not security vulnerabilities
unless they create a security, privacy, or integrity risk.
