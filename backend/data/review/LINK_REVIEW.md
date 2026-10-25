# Quarantined deployment links - human review

Generated 2026-10-24 by `python -m scripts.link_review export` from
`backend/data/data_quality_review.json`. **8 links need a reviewer decision.** No replacement
is suggested: the data contain nothing that identifies the correct deployment (see each entry).

How to review:
1. For each incident below, find the source that establishes its deployment (or that it had none).
2. Fill in `link_decisions.csv`: `decision` = `replace` | `none` | `keep_quarantined`;
   `new_deployment_id` for `replace`; `reviewer` and `source` for `replace` and `none`.
3. `python -m scripts.link_review check` validates the file and prints the changes.
4. `python -m scripts.link_review apply --apply` applies the valid decisions (original copied to
   `backend/data/versions/`), then re-run `python -m scripts.seed`.

`none` is applied only when the reviewer confirms it - an empty decision is never treated as `none`.

### INC-008 - SSO authentication failure (auth-service)

- Recorded root cause: OAuth provider certificate expired
- Current link: **DEP-108** on **payroll-service** ("Blue-green deployment", 2026-05-09T10:24:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-108 on payroll-service, not auth-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-102, DEP-109, DEP-116) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on auth-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-102 | 2026-05-03T10:06:00 | JWT authentication upgrade | already referenced by INC-002 |
  | DEP-109 | 2026-05-10T10:27:00 | Connection pool tuning | already referenced by INC-009 |
  | DEP-116 | 2026-05-17T10:48:00 | Search index refresh | already referenced by INC-016 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-008; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-009 - Duplicate payroll records (payroll-service)

- Recorded root cause: Batch job executed twice
- Current link: **DEP-109** on **auth-service** ("Connection pool tuning", 2026-05-10T10:27:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-109 on auth-service, not payroll-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-101, DEP-108, DEP-115) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on payroll-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-101 | 2026-05-02T10:03:00 | Database schema migration | already referenced by INC-001 |
  | DEP-108 | 2026-05-09T10:24:00 | Blue-green deployment | already referenced by INC-008 |
  | DEP-115 | 2026-05-16T10:45:00 | Ingress configuration change | already referenced by INC-015 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-009; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-010 - SMS notifications not sent (notification-service)

- Recorded root cause: Third-party SMS API outage
- Current link: **DEP-110** on **leave-service** ("API version upgrade", 2026-05-11T10:30:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-110 on leave-service, not notification-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-104, DEP-111, DEP-118) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on notification-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-104 | 2026-05-05T10:12:00 | SMTP provider update | already referenced by INC-004 |
  | DEP-111 | 2026-05-12T10:33:00 | Database schema migration | already referenced by INC-011 |
  | DEP-118 | 2026-05-19T10:54:00 | Blue-green deployment | already referenced by INC-018 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-010; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-011 - Leave approval workflow stuck (leave-service)

- Recorded root cause: Message queue backlog
- Current link: **DEP-111** on **notification-service** ("Database schema migration", 2026-05-12T10:33:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-111 on notification-service, not leave-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-103, DEP-110, DEP-117) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on leave-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-103 | 2026-05-04T10:09:00 | Cache optimization | already referenced by INC-003 |
  | DEP-110 | 2026-05-11T10:30:00 | API version upgrade | already referenced by INC-010 |
  | DEP-117 | 2026-05-18T10:51:00 | ETL pipeline enhancement | already referenced by INC-017 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-011; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-017 - Email queue growth (notification-service)

- Recorded root cause: Worker pod crash loop
- Current link: **DEP-117** on **leave-service** ("ETL pipeline enhancement", 2026-05-18T10:51:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-117 on leave-service, not notification-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-104, DEP-111, DEP-118) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on notification-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-104 | 2026-05-05T10:12:00 | SMTP provider update | already referenced by INC-004 |
  | DEP-111 | 2026-05-12T10:33:00 | Database schema migration | already referenced by INC-011 |
  | DEP-118 | 2026-05-19T10:54:00 | Blue-green deployment | already referenced by INC-018 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-017; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-018 - Service unavailable during deployment (gateway-service)

- Recorded root cause: Blue-green switch failure
- Current link: **DEP-118** on **notification-service** ("Blue-green deployment", 2026-05-19T10:54:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-118 on notification-service, not gateway-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-105, DEP-112, DEP-119) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on gateway-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-105 | 2026-05-06T10:15:00 | Ingress configuration change | already referenced by INC-005 |
  | DEP-112 | 2026-05-13T10:36:00 | JWT authentication upgrade | already referenced by INC-012 |
  | DEP-119 | 2026-05-20T10:57:00 | Connection pool tuning | already referenced by INC-019 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-018; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-019 - Employee export timing out (employee-service)

- Recorded root cause: Large unoptimized query
- Current link: **DEP-119** on **gateway-service** ("Connection pool tuning", 2026-05-20T10:57:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-119 on gateway-service, not employee-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-106, DEP-113, DEP-120) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on employee-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-106 | 2026-05-07T10:18:00 | Search index refresh | already referenced by INC-006 |
  | DEP-113 | 2026-05-14T10:39:00 | Cache optimization | already referenced by INC-013 |
  | DEP-120 | 2026-05-21T10:00:00 | API version upgrade | already referenced by INC-020 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-019; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)

### INC-020 - Scheduled reports not generated (reporting-service)

- Recorded root cause: Cron job configuration error
- Current link: **DEP-120** on **employee-service** ("API version upgrade", 2026-05-21T10:00:00) - a different service, and no documented dependency.
- Why quarantined: deployments.json records DEP-120 on employee-service, not reporting-service. No log line, document or other record names the deployment for this incident (logs contain no DEP-/INC- identifiers). Same-service deployments exist (DEP-107, DEP-114) but each is already referenced by another incident, and nothing ties them to this one, so no replacement was chosen.
- Deployments on reporting-service (for the reviewer; none is proposed):

  | deployment | time | change | currently |
  |---|---|---|---|
  | DEP-107 | 2026-05-08T10:21:00 | ETL pipeline enhancement | already referenced by INC-007 |
  | DEP-114 | 2026-05-15T10:42:00 | SMTP provider update | already referenced by INC-014 |

- What would settle it: a change ticket, release note, postmortem or deploy log naming the deployment for INC-020; or the owner's confirmation that no deployment is involved.
- Decision: _pending_ (fill in `link_decisions.csv`)
