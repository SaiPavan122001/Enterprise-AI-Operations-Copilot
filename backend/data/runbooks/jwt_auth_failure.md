# Authentication Failure Runbook

Symptoms:
- Users unable to login
- 401 Unauthorized

Checks:
1. Verify JWT secret
2. Verify token expiry
3. Check OAuth provider

Resolution:
Rotate JWT keys and restart auth-service.
