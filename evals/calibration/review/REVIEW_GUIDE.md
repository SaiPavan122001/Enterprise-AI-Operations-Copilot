# Human review guide

Generated 2026-10-24 by `python -m evals.human_review export`. All human fields are empty.
The files are **blind**: they omit the judge's verdict and every AI label, so record your own judgement.

## 1. Claim labels: `claims_blind.csv` (60 claims from the final run)
For each claim, read only the `evidence` column (the records the answer had) and set `human_label`:
- `supported`: the evidence states it, or it follows directly
- `unsupported`: the evidence does not establish it (it may be plausible, but it is not in the records)
- `contradicted`: the evidence says otherwise
- `indeterminate`: you cannot tell from the evidence shown (excluded from agreement)

## 2. Judge samples: `samples_blind.csv` (100 rows; metrics: answer_correctness, answer_relevancy, context_precision, context_recall, correct_refusal, faithfulness)
Set `human_label` to `1` if the answer deserves to PASS the named metric, otherwise `0`.

## 3. Reference corrections: `reference_corrections_review.csv` (17 items)
v1 references for these questions assert deployment links the data does not support (quarantined links).
Set `decision` = `approve` (use the proposed text) | `edit` (put your text in `edited_reference`) |
`reject` (keep v1), and fill in `reviewer`. Questions are never changed.

## After review
```
python -m evals.human_review validate
python -m evals.human_review merge
python -m evals.claim_calibration agreement --labels human
python -m evals.calibration agreement
python -m evals.human_review build-v1.1
```
`testset_v1.jsonl` stays unchanged. `testset_v1.1.jsonl` contains v1 with only the approved or edited
references replaced.

## Reference corrections for review

### 1. `q-d32d525618` (single_chunk)
**Question:** What was the root cause of the incident related to the 'Employee export timing out' in the employee-service?

| | Reference |
|---|---|
| v1 (current) | The root cause of the 'Employee export timing out' incident in the employee-service was a large unoptimized query. This incident was recorded under deployment DEP-119. |
| proposed v1.1 | INC-019 (employee-service, "Employee export timing out") records the root cause: Large unoptimized query. Its referenced deployment DEP-119 belongs to gateway-service ('Connection pool tuning'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-019 quarantined (deployments.json records DEP-119 on gateway-service, not employee-service. No log line, document or other record names the deployment for this incident (logs co...)

### 2. `q-9323308a46` (single_chunk)
**Question:** What deployment is associated with the issue of timing out during employee exports due to a large unoptimized query?

| | Reference |
|---|---|
| v1 (current) | The problem of timing out during employee exports is associated with deployment DEP-119, which had a root cause of a large unoptimized query. |
| proposed v1.1 | INC-019 (employee-service, "Employee export timing out") records the root cause: Large unoptimized query. Its referenced deployment DEP-119 belongs to gateway-service ('Connection pool tuning'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-019 quarantined (deployments.json records DEP-119 on gateway-service, not employee-service. No log line, document or other record names the deployment for this incident (logs co...)

### 3. `q-5c08dac859` (single_chunk)
**Question:** What was the root cause of the 'Service unavailable during deployment' incident for the gateway-service?

| | Reference |
|---|---|
| v1 (current) | The root cause of the 'Service unavailable during deployment' incident for the gateway-service was a blue-green switch failure during deployment DEP-118. |
| proposed v1.1 | INC-018 (gateway-service, "Service unavailable during deployment") records the root cause: Blue-green switch failure. Its referenced deployment DEP-118 belongs to notification-service ('Blue-green deployment'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-018 quarantined (deployments.json records DEP-118 on notification-service, not gateway-service. No log line, document or other record names the deployment for this incident (log...)

### 4. `q-360f06057d` (single_chunk)
**Question:** What deployment caused the gateway service to be unavailable due to a blue-green switch failure?

| | Reference |
|---|---|
| v1 (current) | The deployment associated with this problem is DEP-118, which experienced a blue-green switch failure leading to the service being unavailable. |
| proposed v1.1 | INC-018 (gateway-service, "Service unavailable during deployment") records the root cause: Blue-green switch failure. Its referenced deployment DEP-118 belongs to notification-service ('Blue-green deployment'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-018 quarantined (deployments.json records DEP-118 on notification-service, not gateway-service. No log line, document or other record names the deployment for this incident (log...)

### 5. `q-60c0f4e1ec` (single_chunk)
**Question:** What was the root cause of the incident [INC-020] regarding the reporting-service where scheduled reports were not generated?

| | Reference |
|---|---|
| v1 (current) | The root cause of the incident [INC-020] for the reporting-service was a cron job configuration error. This incident was associated with deployment DEP-120. |
| proposed v1.1 | INC-020 (reporting-service, "Scheduled reports not generated") records the root cause: Cron job configuration error. Its referenced deployment DEP-120 belongs to employee-service ('API version upgrade'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-020 quarantined (deployments.json records DEP-120 on employee-service, not reporting-service. No log line, document or other record names the deployment for this incident (logs ...)

### 6. `q-f1e9c9c226` (single_chunk)
**Question:** What configuration issue related to a scheduled task caused the reporting service to fail in generating reports, and what deployment is linked to this incident?

| | Reference |
|---|---|
| v1 (current) | The problem was caused by a cron job configuration error, and it is associated with deployment DEP-120. |
| proposed v1.1 | INC-020 (reporting-service, "Scheduled reports not generated") records the root cause: Cron job configuration error. Its referenced deployment DEP-120 belongs to employee-service ('API version upgrade'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-020 quarantined (deployments.json records DEP-120 on employee-service, not reporting-service. No log line, document or other record names the deployment for this incident (logs ...)

### 7. `q-ef38eb71de` (single_chunk)
**Question:** What was the root cause of the SSO authentication failure incident for the auth-service in incident record INC-008?

| | Reference |
|---|---|
| v1 (current) | The root cause of the SSO authentication failure incident for the auth-service was that the OAuth provider certificate expired. This incident was associated with deployment DEP-108. |
| proposed v1.1 | INC-008 (auth-service, "SSO authentication failure") records the root cause: OAuth provider certificate expired. Its referenced deployment DEP-108 belongs to payroll-service ('Blue-green deployment'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-008 quarantined (deployments.json records DEP-108 on payroll-service, not auth-service. No log line, document or other record names the deployment for this incident (logs contai...)

### 8. `q-b34255c7a3` (single_chunk)
**Question:** What was the critical issue related to the SSO authentication for the auth-service and what was the root cause of this problem?

| | Reference |
|---|---|
| v1 (current) | The critical issue with the SSO authentication for the auth-service was caused by an expired OAuth provider certificate. This incident is associated with deployment DEP-108. |
| proposed v1.1 | INC-008 (auth-service, "SSO authentication failure") records the root cause: OAuth provider certificate expired. Its referenced deployment DEP-108 belongs to payroll-service ('Blue-green deployment'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-008 quarantined (deployments.json records DEP-108 on payroll-service, not auth-service. No log line, document or other record names the deployment for this incident (logs contai...)

### 9. `q-90220e1ffd` (single_chunk)
**Question:** Why was the leave approval workflow stuck in the leave-service?

| | Reference |
|---|---|
| v1 (current) | The leave approval workflow was stuck due to a message queue backlog, as indicated in incident record INC-011. This incident was associated with deployment DEP-111. |
| proposed v1.1 | INC-011 (leave-service, "Leave approval workflow stuck") records the root cause: Message queue backlog. Its referenced deployment DEP-111 belongs to notification-service ('Database schema migration'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-011 quarantined (deployments.json records DEP-111 on notification-service, not leave-service. No log line, document or other record names the deployment for this incident (logs ...)

### 10. `q-d3dbd9edd3` (single_chunk)
**Question:** What was the root cause of the 'Leave approval workflow stuck' incident in the leave-service?

| | Reference |
|---|---|
| v1 (current) | The root cause of the 'Leave approval workflow stuck' incident in the leave-service was a message queue backlog. This incident was associated with deployment DEP-111. |
| proposed v1.1 | INC-011 (leave-service, "Leave approval workflow stuck") records the root cause: Message queue backlog. Its referenced deployment DEP-111 belongs to notification-service ('Database schema migration'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-011 quarantined (deployments.json records DEP-111 on notification-service, not leave-service. No log line, document or other record names the deployment for this incident (logs ...)

### 11. `q-8a0003f3a1` (single_chunk)
**Question:** What recent deployment is linked to the issue where the leave approval process was interrupted due to a backlog in the message queue?

| | Reference |
|---|---|
| v1 (current) | The problem is associated with deployment DEP-111, which caused a backlog in the message queue, leading to the leave approval workflow being stuck. |
| proposed v1.1 | INC-011 (leave-service, "Leave approval workflow stuck") records the root cause: Message queue backlog. Its referenced deployment DEP-111 belongs to notification-service ('Database schema migration'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-011 quarantined (deployments.json records DEP-111 on notification-service, not leave-service. No log line, document or other record names the deployment for this incident (logs ...)

### 12. `q-9f9dd0cd36` (single_chunk)
**Question:** Why is the email queue growing excessively, causing high severity issues in the notification service?

| | Reference |
|---|---|
| v1 (current) | The email queue growth was caused by a crash loop of the worker pod, as noted in incident record INC-017 related to deployment DEP-117. |
| proposed v1.1 | INC-017 (notification-service, "Email queue growth") records the root cause: Worker pod crash loop. Its referenced deployment DEP-117 belongs to leave-service ('ETL pipeline enhancement'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-017 quarantined (deployments.json records DEP-117 on leave-service, not notification-service. No log line, document or other record names the deployment for this incident (logs ...)

### 13. `q-22e80fcd08` (single_chunk)
**Question:** What deployment is linked to the issue of the email queue growing due to a worker pod experiencing a crash loop?

| | Reference |
|---|---|
| v1 (current) | The problem of email queue growth is associated with deployment DEP-117, and the root cause of the issue was identified as a worker pod crash loop. |
| proposed v1.1 | INC-017 (notification-service, "Email queue growth") records the root cause: Worker pod crash loop. Its referenced deployment DEP-117 belongs to leave-service ('ETL pipeline enhancement'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-017 quarantined (deployments.json records DEP-117 on leave-service, not notification-service. No log line, document or other record names the deployment for this incident (logs ...)

### 14. `q-ea9e3e8646` (single_chunk)
**Question:** What deployment is associated with the issue of SMS notifications not being sent due to a third-party SMS API outage?

| | Reference |
|---|---|
| v1 (current) | The incident is associated with deployment DEP-110, and the root cause of the problem was a third-party SMS API outage. |
| proposed v1.1 | INC-010 (notification-service, "SMS notifications not sent") records the root cause: Third-party SMS API outage. Its referenced deployment DEP-110 belongs to leave-service ('API version upgrade'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-010 quarantined (deployments.json records DEP-110 on leave-service, not notification-service. No log line, document or other record names the deployment for this incident (logs ...)

### 15. `q-e047c68e67` (single_chunk)
**Question:** What was the root cause of the 'Duplicate payroll records' incident for the payroll-service?

| | Reference |
|---|---|
| v1 (current) | The root cause of the 'Duplicate payroll records' incident for the payroll-service was that the batch job executed twice during deployment DEP-109. |
| proposed v1.1 | INC-009 (payroll-service, "Duplicate payroll records") records the root cause: Batch job executed twice. Its referenced deployment DEP-109 belongs to auth-service ('Connection pool tuning'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-009 quarantined (deployments.json records DEP-109 on auth-service, not payroll-service. No log line, document or other record names the deployment for this incident (logs contai...)

### 16. `q-3d0b7a7b60` (single_chunk)
**Question:** What deployment is linked to the issue of duplicate payroll records in the payroll service, and what caused this problem?

| | Reference |
|---|---|
| v1 (current) | The issue of duplicate payroll records was caused by the batch job executing twice, and it is associated with deployment DEP-109. |
| proposed v1.1 | INC-009 (payroll-service, "Duplicate payroll records") records the root cause: Batch job executed twice. Its referenced deployment DEP-109 belongs to auth-service ('Connection pool tuning'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-009 quarantined (deployments.json records DEP-109 on auth-service, not payroll-service. No log line, document or other record names the deployment for this incident (logs contai...)

### 17. `q-60a32c2381` (multi_chunk)
**Question:** What were the root causes of service unavailability during the deployment of the gateway-service and the incorrect dashboard metrics in the reporting-service, and how might these issues be related to their respective deployments?

| | Reference |
|---|---|
| v1 (current) | The root cause of the service unavailability during the deployment of the gateway-service was a blue-green switch failure, while the incorrect dashboard metrics in the reporting-service were due to an ETL job failure. Both incidents occurred during their respective deployments, DEP-118 for the gateway-service and DEP-114 for the reporting-service, highlighting the potential impact of deployment processes on service reliability. |
| proposed v1.1 | INC-014 (reporting-service, "Dashboard metrics incorrect") records the root cause: ETL job failure. INC-018 (gateway-service, "Service unavailable during deployment") records the root cause: Blue-green switch failure. Its referenced deployment DEP-118 belongs to notification-service ('Blue-green deployment'), so no deployment can be verified for this incident. |

Evidence: data_quality_review.json: INC-018 quarantined (deployments.json records DEP-118 on notification-service, not gateway-service. No log line, document or other record names the deployment for this incident (log...)
