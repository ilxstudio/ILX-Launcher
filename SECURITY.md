# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.1.x   | Yes       |
| 1.0.x   | No        |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Email [arivera@riveraeng.com](mailto:arivera@riveraeng.com) with:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any suggested mitigations you have in mind

You will receive a response within 72 hours. If the issue is confirmed, a patch will be
released as quickly as possible and you will be credited in the changelog (unless you prefer
to remain anonymous).

## Scope

The ILX Launcher runs child processes on your local machine and communicates with a local
Ollama server over loopback. It does not make outbound network connections other than to the
configured Ollama host and to python-build-standalone (for the bundled CPython download).

Relevant attack surfaces:
- **Child process execution** — the launcher runs `main.py` from the configured project directory.
  A malicious project directory is considered out of scope (the user explicitly points the launcher at it).
- **Ollama host** — configurable; defaults to localhost. Changing it to a remote host is the user's choice.
- **Bundled CPython download** — fetched over HTTPS from `github.com/indygreg/python-build-standalone`.
  Checksum verification is on the roadmap.
- **Live REPL** — loopback-only (`127.0.0.1:8731`), only active when `ILX_DEV=1` is set by the launcher.
