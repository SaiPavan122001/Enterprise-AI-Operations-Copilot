# Payroll Failure Runbook

Symptoms:
- Payroll generation fails
- Missing salary records

Checks:
1. Verify schema migration
2. Check payroll database logs
3. Validate salary_amount column

Resolution:
Rollback migration and re-run payroll job.
