# Kevin's Job Alerts

Watches for new internship postings at big tech companies and pushes an alert to your phone and email as soon as a listing goes live.

The list of companies is limited and is curated. This is meant to be a instant notifier for high-value targets, not a general scraper. 

Each user configures their own companies, job types, and fit criteria

An LLM classifier screens every listing against your criteria and optionally your resume before notifying you.

Hosted on AWS (Lambda + DynamoDB), with control panel at [jobs.kevinjin.dev](https://jobs.kevinjin.dev).

See [docs/ntfy-setup.md](docs/ntfy-setup.md) to set up notifications, or [docs/agent-skill.md](docs/agent-skill.md) if you want your own agent to manage your config.

If you know me well enough, ask me and I'll add you to the list.
