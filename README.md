# Job Monitor for Nigerian Job Sites

Automatically monitors multiple Nigerian job sites for developer/internship roles in Abuja and sends email notifications via Gmail.

## Features

- 🔍 **Monitors 6 major Nigerian job sites:**
  - LinkedIn Jobs
  - Indeed Nigeria
  - Jobberman
  - MyJobMag
  - NgCareers
  - Hot Nigerian Jobs
- 🎯 **Smart filtering** for developer roles, internships, and entry-level positions
- 📧 **Email notifications** via Gmail SMTP
- ⏰ **Runs every 30 minutes** on GitHub Actions (free!)
- 💾 **Deduplication** - only notifies about new jobs
- 🚀 **Zero cost** - runs on GitHub Actions free tier

## Quick Start

### 1. Fork/Clone this Repository

```bash
git clone https://github.com/yourusername/job-monitor.git
cd job-monitor
```

### 2. Set up Gmail App Password

1. Enable 2-Factor Authentication on your Google account
2. Go to [Google App Passwords](https://myaccount.google.com/apppasswords)
3. Create a new app password for "Mail"
4. Copy the 16-character password

### 3. Configure GitHub Secrets

Go to your repository **Settings → Secrets and variables → Actions** and add:

| Secret Name | Value |
|-------------|-------|
| `SENDER_EMAIL` | Your Gmail address (e.g., `you@gmail.com`) |
| `SENDER_PASSWORD` | Your 16-character Gmail App Password |
| `RECIPIENT_EMAIL` | Where to send notifications (can be same as sender) |

### 4. Customize Configuration (Optional)

Edit `config.yaml` to adjust:
- Job keywords to search for
- Job sites to monitor
- Location (default: Abuja, Nigeria)
- Exclude keywords (e.g., "senior", "manager")

### 5. Enable GitHub Actions

Go to **Actions** tab in your repository and enable workflows. The monitor will run automatically every 30 minutes.

### 6. Test It

You can manually trigger a run:
1. Go to **Actions** tab
2. Select "Job Monitor" workflow
3. Click "Run workflow"

## Local Development

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Local Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### Run Once (Test)

```bash
python job_monitor.py --once
```

### Run Continuously (Local)

```bash
python job_monitor.py
```

### Send Test Email

```bash
python job_monitor.py --test-email
```

## Configuration

### Job Keywords (config.yaml)

The monitor searches for these keywords in job titles and descriptions:

```yaml
keywords:
  - "developer"
  - "software engineer"
  - "frontend"
  - "backend"
  - "fullstack"
  - "python"
  - "javascript"
  - "react"
  - "node"
  - "java"
  - "c#"
  - ".net"
  - "internship"
  - "graduate"
  - "entry level"
  - "junior"
  - "trainee"
  - "devops"
  - "data analyst"
  - "data scientist"
  - "mobile developer"
  - "flutter"
  - "kotlin"
  - "swift"
```

### Exclude Keywords

Jobs containing these will be filtered out:

```yaml
exclude_keywords:
  - "senior"
  - "lead"
  - "principal"
  - "architect"
  - "manager"
  - "director"
  - "vp"
  - "head of"
```

### Job Sites

Enable/disable specific sites (currently **LinkedIn only** — others disabled due to blocking/poor results):

```yaml
job_sites:
  linkedin: true
  myjobmag: false
  jobberman: false
  indeed: false
  ngcareers: false
  hotnigerianjobs: false
```

## How It Works

1. **GitHub Actions** triggers the workflow every 30 minutes (via cron)
2. **Python script** scrapes each enabled job site
3. **Filters** jobs by keywords (developer, internship, etc.) and excludes senior roles
4. **Deduplicates** using `seen_jobs.json` (stored as GitHub Actions artifact)
5. **Sends email** via Gmail SMTP with new job listings
6. **Repeats** every 30 minutes

## Customization

### Add More Job Sites

1. Create a new scraper class in `job_monitor.py` (extend `JobSiteScraper`)
2. Add it to `_init_scrapers()` method
3. Add config option in `config.yaml`

### Change Schedule

Edit `.github/workflows/job-monitor.yml`:

```yaml
on:
  schedule:
    # Every hour
    - cron: '0 * * * *'
    # Every 15 minutes
    - cron: '*/15 * * * *'
    # Daily at 9 AM UTC
    - cron: '0 9 * * *'
```

### Change Location

Edit `config.yaml`:

```yaml
job_search:
  location: "Lagos, Nigeria"  # or any other city
```

## Troubleshooting

### No emails received?
- Check GitHub Actions logs for errors
- Verify Gmail App Password is correct
- Check spam folder
- Ensure `RECIPIENT_EMAIL` is set correctly

### Rate limiting?
- The script includes delays between requests
- Reduce `max_jobs_per_site` in config
- Limit number of keywords searched per run

### Jobs not found?
- Check if site structure changed (selectors may need updating)
- Run locally with `--once` to debug
- Check GitHub Actions logs for scraper errors

## Cost

**Free!** GitHub Actions provides:
- 2,000 minutes/month on private repos (unlimited on public)
- This workflow uses ~1-2 minutes per run
- 30 min interval = 48 runs/day = ~100 minutes/day
- Well within free tier for personal use

## Security

- Credentials stored in GitHub Secrets (encrypted)
- No credentials in code or config files
- `.env` file gitignored
- `seen_jobs.json` only stores job URLs, no personal data

## License

MIT License - Feel free to modify and use!

## Contributing

PRs welcome! Ideas:
- Add more Nigerian job sites
- Add Telegram/Discord notifications
- Add job description scraping
- Add salary filtering
- Improve deduplication logic

---

**Built for Nigerian tech graduates seeking opportunities in Abuja** 🇳🇬