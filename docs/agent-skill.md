# job-alerts agent skill

Lets your own agent read and update your job-alerts config, and check your recent activity, on your behalf.

## Auth

Every request needs your personal API key in the `X-Api-Key` header.

**Finding your key**: generate one from Profile -> Agent API key. Shown once at creation - save it somewhere safe, it can't be viewed again, only regenerated (which invalidates the old one).

## Endpoints

`GET /api/config` - your current config: `fit_prompt`, `companies`, `job_types`, `email_to`.

`PUT /api/config` - same shape as GET. Replaces your whole config - send the complete object, not a partial patch.

`GET /api/metrics` - your last-24h stats: invocations, errors, notifications sent, classifier calls, avg tokens, last run time.

`GET /api/logs` - your recent scan log lines (last 24h), each with a timestamp and an `is_failure` flag.

## Example

```bash
curl -H "X-Api-Key: $JOB_ALERTS_API_KEY" https://jobs.kevinjin.dev/api/config
```
