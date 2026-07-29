# job-alerts agent skill

Lets your own agent read and update your job-alerts config, and check your
recent activity, on your behalf. Describes the multi-user API - it becomes
usable once per-user accounts and API keys ship (see main repo history for
status); nothing here works against the single-tenant setup.

## Auth

Every request needs your personal API key in the `X-Api-Key` header.

**Finding your key**: once the dashboard's API key feature ships, generate
one from Settings -> API Keys. It's shown once at creation - save it
somewhere safe, it can't be viewed again, only regenerated (which
invalidates the old one).

## Endpoints

`GET /api/config` - your current config: `fit_prompt`, `classifier_model`,
`companies`, `enabled_sources`, `email_to`.

`PUT /api/config` - same shape as GET. Replaces your whole config - send
the complete object, not a partial patch.

`GET /api/metrics` - your last-24h stats: invocations, errors, notifications
sent, classifier calls, avg tokens, last run time.

`GET /api/logs` - your recent scan log lines (last 24h), each with a
timestamp and an `is_failure` flag.

## Example

```bash
curl -H "X-Api-Key: $JOB_ALERTS_API_KEY" https://jobs.kevinjin.dev/api/config
```
