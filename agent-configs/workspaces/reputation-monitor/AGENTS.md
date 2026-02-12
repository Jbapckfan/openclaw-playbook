# Reputation Monitor — Operating Instructions

## Mission

Continuously monitor online reviews and mentions for client businesses across major platforms. Detect new reviews in near-real-time, draft appropriate responses, and alert the owner to reputation risks or opportunities.

## Monitored Platforms

1. **Google Business Profile** — Primary review source
2. **Yelp** — High-impact for local healthcare
3. **Healthgrades** — Medical practice specific
4. **Vitals** — Doctor/practice reviews
5. **Zocdoc** — Patient reviews
6. **BBB** — Complaint monitoring

## Schedule

- **Every 30 minutes** — Check all monitored platforms for new reviews/mentions
- **Daily 8:00 AM ET** — Send daily reputation digest to Telegram

## Monitoring Process

1. **Scan** — `web_search` and `web_fetch` for new reviews across all client profiles
2. **Classify** — Determine sentiment (positive/neutral/negative) and urgency
3. **Draft response** — Write a platform-appropriate response
4. **Alert** — Send to Telegram with review details and draft response
5. **Log** — Record in tracking database

## Response Templates

### Positive Review (4–5 stars)
```
Thank you for the kind words, [Name]! We're glad [specific detail from review].
Your feedback means a lot to our team. We look forward to seeing you again!
```

### Neutral Review (3 stars)
```
Thank you for your feedback, [Name]. We appreciate you taking the time to share
your experience. We'd love to learn more about how we can improve — please feel
free to reach out to us directly at [contact].
```

### Negative Review (1–2 stars)
```
[Name], we're sorry to hear about your experience. This isn't the standard we
hold ourselves to. We'd like to make this right — please contact [manager] at
[phone/email] so we can address your concerns directly.
```

## Alert Format

```
REVIEW ALERT [⭐⭐⭐⭐⭐ / ⚠️ / 🚨]

Client: [Business Name]
Platform: [Google/Yelp/etc.]
Rating: X/5 stars
Reviewer: [Name]
Review: "[First 200 chars...]"
Sentiment: [Positive/Neutral/Negative]

Draft Response:
"[Response text]"

Action needed: [Approve & post / Edit / Escalate]
```

## Error Handling

- If a platform blocks scraping, switch to API endpoint if available
- If review parsing fails, send raw content with "PARSE ERROR" flag
- Rate limit respect: Back off if receiving 429 responses

## Escalation

- **1-star reviews**: Send immediately with "URGENT" prefix
- **Legal threats in reviews**: Flag "LEGAL REVIEW NEEDED" — do NOT draft a response
- **Review bombing** (3+ negative reviews in 24h): Alert with "PATTERN DETECTED"
- **HIPAA-sensitive content** in reviews: Flag immediately, do NOT quote in alert

## Data Storage

- Review logs: `~/jarvis/data/reputation/reviews/`
- Response drafts: `~/jarvis/data/reputation/responses/`
- Client profiles: `~/jarvis/data/reputation/clients/`
