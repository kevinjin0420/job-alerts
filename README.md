# notify-actions

Watches for new internship postings and pushes an alert to your phone (via [ntfy](https://ntfy.sh)) and email, the moment one goes live. Runs entirely on GitHub Actions on a 15-minute cron - nothing runs on your machine.

## How it works

- `watch.py` runs on a schedule via `.github/workflows/watch.yml`.
- It pulls listings from one or more **sources** (see below), normalizes them into a common `Listing` shape, and diffs against `seen.json` (committed back to this repo after each run) so you're only ever notified once per posting.
- The first run seeds `seen.json` with everything currently live, silently, so you don't get blasted with the existing backlog.
- New posting -> ntfy push (role, location, apply link) + email with the same.
- If one source fails (a site changes its layout, a network blip), the run logs it and keeps going with the rest - a single broken source never blocks the others.

## Sources (extensibility)

Sources live in `sources/` and all implement the same tiny interface (`sources/base.py`):

```python
class Source(Protocol):
    name: str
    def fetch(self) -> list[Listing]: ...
```

Which sources run is controlled by the `ENABLED_SOURCES` repo variable - a comma-separated list of specs:

| Spec | What it does |
| --- | --- |
| `community` | Reads the crowd-sourced [vanshb03/Summer2027-Internships](https://github.com/vanshb03/Summer2027-Internships) list, filtered to `COMPANIES`. Default. |
| `greenhouse:<CompanyName>:<board_token>` | Queries that company's public Greenhouse job board API **directly** - no scraping. |
| `apple` | Parses the JSON Apple's careers site embeds in its page HTML (Apple has no public jobs API). Best-effort - see caveats below. |

Example: `ENABLED_SOURCES=community,greenhouse:SpaceX:spacex,greenhouse:Stripe:stripe,apple` runs all four in parallel each tick.

### Finding a company's Greenhouse board token

Greenhouse-hosted companies expose `https://boards-api.greenhouse.io/v1/boards/<token>/jobs` as plain JSON - no auth, no scraping. The token is usually the company's boards.greenhouse.io slug, e.g. SpaceX is `spacex` (`boards.greenhouse.io/spacex`). Test one with:

```bash
curl -s https://boards-api.greenhouse.io/v1/boards/<token>/jobs | head -c 300
```

If it returns real JSON, you can add that company with a one-line config change - no code required. This covers a large share of tech companies (Stripe, Airbnb, Databricks, Robinhood, Anduril, and many more).

### Adding a company that isn't on Greenhouse

Some companies run their own careers site (Lever, Workday, a custom SPA, etc). To add one:

1. Create `sources/<company>.py` with a class exposing `name: str` and `fetch(self) -> list[Listing]`.
2. Register its spec prefix in `sources/__init__.py::build_sources`.
3. Add it to `ENABLED_SOURCES`.

`sources/apple.py` and `sources/greenhouse.py` are both good templates - Apple shows how to scrape an SSR JSON blob out of HTML when there's no API; Greenhouse shows the simple direct-API case.

### Google and Tesla specifically

You asked about these - here's what direct research turned up, so you know exactly what you're working with if you want to build it yourself:

- **Google**: careers.google.com renders its results entirely client-side via JavaScript. I could not find a public, directly-callable JSON endpoint for it (probed a few plausible API paths; they 404 against a real backend, meaning an endpoint exists, but I don't have its real shape). Getting this reliably would need headless-browser rendering (e.g. Playwright) inside the Action, which is heavier than a 15-minute cron job really wants to run, but is architecturally just another `Source` if you want to add it.
- **Tesla**: tesla.com/careers is behind Akamai bot-protection and returns a 403 to plain HTTP requests (no scriptable HTML at all, let alone JSON). Same story - would need real browser automation to get past the bot check, and even then it may be fragile/against ToS-adjacent territory, so I didn't wire it up.
- Both are legitimate extension points; the `community` source (crowd-sourced list) is what actually surfaces Google/Tesla internships today, just with the community's usual lag.

## ntfy: how it actually works

ntfy is a pub/sub push service. A "topic" is just a path segment on `ntfy.sh` - there's no account, no registration. Anyone who knows the topic name can:
- **subscribe** to it (via the app, a browser, or `curl -s ntfy.sh/<topic>/json`) and receive every message published to it, and
- **publish** to it (a plain `POST` to `ntfy.sh/<topic>`).

**There is no built-in privacy on the free public instance** - the topic name is the only thing standing between your notifications and anyone else. That's why setup uses a long, random, unguessable string (`google-intern-alerts-x7f2q9`), not something like `my-alerts`. If someone guesses or leaks your topic, they can both read your alerts and spam fake ones into your phone. For real access control you'd self-host ntfy with auth, or pay to reserve a topic on ntfy.sh - for a personal alert feed, a random topic is the normal, accepted tradeoff.

## Setup

1. **Create the repo secrets and variables.** In this repo's Settings -> Secrets and variables -> Actions:
   - Secrets: `NTFY_TOPIC` (a random, hard-to-guess string), `EMAIL_TO`, `SMTP_USER` (your Gmail address), `SMTP_PASS` (a [Gmail App Password](https://myaccount.google.com/apppasswords) - requires 2FA on the account).
   - Variables (optional, have defaults): `COMPANIES` (default `Google`, used by the `community` source), `ENABLED_SOURCES` (default `community`).

2. **Install ntfy on your phone** ([iOS](https://apps.apple.com/us/app/ntfy/id1625396347) / [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy)) and subscribe to the same topic you put in `NTFY_TOPIC`.

3. **Seed the first run.** Go to Actions -> "Watch Google Internships" -> Run workflow. This creates `seen.json` from whatever's currently live without notifying you.

4. From then on, the workflow runs automatically every ~15 minutes.

## Caveats

- The `community` source rides on the crowd-sourced repo catching a posting first - usually minutes, not always instant. Keep that repo's Discord notifications on as a backstop.
- GitHub's cron schedule is best-effort and can slip a few minutes under load; it is not guaranteed to fire exactly every 15 minutes.
- Direct-scrape sources (`apple`, and any you add) are inherently more fragile than the community list or a real API - a site redesign can silently break them. They fail in isolation (logged, run continues) rather than taking down the whole watcher.
