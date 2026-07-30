# Kevin's Job Alerts

Watches for new internship postings at big tech companies and pushes an alert to your phone and email as soon as a listing goes live.

Each user picks their own companies, job types, and fit criteria - an LLM classifier screens every listing against your criteria (and your résumé, if you upload one) before notifying you.

Hosted on AWS (Lambda + DynamoDB), with control panel at [jobs.kevinjin.dev](https://jobs.kevinjin.dev).

See [docs/ntfy-setup.md](docs/ntfy-setup.md) to set up notifications, or [docs/agent-skill.md](docs/agent-skill.md) if you want your own agent to manage your config.

If you know me well enough, ask me and I'll add you to the list.
