# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take the security of LLM Observability Proxy seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via email at [xiang49999@gmail.com](mailto:xiang49999@gmail.com) or create a private vulnerability report using GitHub's [Private Vulnerability Reporting](https://github.com/Xiang3999/llm-observability-proxy/security/advisories) feature.

### What to Include

Please include the following information in your report:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact of the vulnerability
- Any suggested fixes (if applicable)

### Response Time

We will acknowledge receipt of your report within **48 hours** and will send you a more detailed response within **5 business days** indicating the next steps in handling your report.

### Disclosure Policy

- We will confirm the vulnerability and determine its impact
- We will develop a fix and release a patched version
- We will publicly disclose the vulnerability after users have had reasonable time to update
- We will credit the reporter (unless they wish to remain anonymous)

## Security Best Practices

When deploying LLM Observability Proxy in production:

1. **Change default credentials**: Always set a strong `MASTER_API_KEY`
2. **Use HTTPS**: Deploy behind a reverse proxy with TLS termination
3. **Secure your database**: Use PostgreSQL with proper authentication in production
4. **Rotate API keys**: Regularly rotate proxy keys and provider keys
5. **Monitor logs**: Enable logging and monitor for suspicious activity
6. **Limit network access**: Only expose necessary ports and use firewalls
7. **Keep dependencies updated**: Regularly update the project and its dependencies

## Known Limitations

- The semantic caching feature uses in-memory storage by default
- SQLite is intended for development use only; use PostgreSQL for production
- The web dashboard should not be exposed to untrusted networks without additional authentication
