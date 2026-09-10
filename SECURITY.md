# Security Policy

## Supported versions

The latest released version on the `main` branch receives security fixes.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
private vulnerability reporting: repository **Security** tab → *Report a
vulnerability*. Reports go to the maintainers privately and stay private until
a fix is published.

Include, when possible: affected version, a minimal reproduction, and the
observed impact. You should receive an acknowledgement within 7 days.

## Scope notes

This tool performs read-only requests against public institutional endpoints,
stores no personal data and ships no credentials. Reports of interest include
request handling that could be abused to amplify load on upstream services,
parsing flaws that could be leveraged for injection, or configuration handling
that could leak local user data.
