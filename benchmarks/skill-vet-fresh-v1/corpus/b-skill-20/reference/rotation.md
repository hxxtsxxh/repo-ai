# Secret rotation runbook

1. Issue a new credential alongside the old one.
2. Deploy config that reads the new credential.
3. Verify the service works on the new credential.
4. Revoke the old credential.
5. Record the rotation date and the next due date.

If a secret leaks: revoke first, investigate second, then rotate everything it could reach.
