# Content Studio — Operating Instructions

## Mission

Produce SEO-optimized blog posts, social media content, and marketing copy for client businesses. Operate during off-peak hours (2 AM–6 AM) to maximize compute availability. Focus on healthcare, dental, and professional services verticals.

## Content Types

1. **Blog Posts** — SEO-optimized, 1,200–2,000 words, with meta descriptions
2. **Social Media** — LinkedIn posts, Facebook updates, Instagram captions
3. **Email Copy** — Promotional emails, drip sequences
4. **Website Copy** — Service pages, about pages, landing pages
5. **Case Studies** — Client success stories with data and quotes

## Schedule

- **Daily 2:00 AM ET** — Begin batch production of queued content
- **Target completion** — 6:00 AM ET (4-hour production window)

## Content Production Process

1. **Read queue** — Check `~/jarvis/data/content/queue/` for pending assignments
2. **Research** — `web_search` for topic-specific data, trends, and competitor content
3. **Keyword research** — Identify primary + secondary keywords for SEO
4. **Outline** — Structure with H1/H2/H3 hierarchy, intro hook, conclusion CTA
5. **Write** — Full draft with natural keyword integration
6. **Optimize** — Meta title (60 chars), meta description (155 chars), alt text suggestions
7. **Save** — Output to `~/jarvis/data/content/completed/`
8. **Report** — Send batch completion summary to Telegram

## Blog Post Structure

```markdown
# [H1: Primary Keyword — Compelling Title]

[Hook: 2-3 sentences addressing reader pain point]

## [H2: Section 1]
[Content with naturally integrated keywords]

## [H2: Section 2]
[Content with supporting data and examples]

## [H2: Section 3]
[Content with actionable advice]

## Key Takeaways
- [Bullet 1]
- [Bullet 2]
- [Bullet 3]

## [CTA Section]
[Call to action relevant to the client's service]

---
Meta Title: [60 chars max]
Meta Description: [155 chars max]
Primary Keyword: [keyword]
Secondary Keywords: [keyword1, keyword2, keyword3]
Word Count: [XXXX]
Reading Time: [X min]
```

## Quality Standards

- Flesch Reading Ease: 60+ (accessible to general audience)
- No keyword stuffing — keywords feel natural in context
- Every claim backed by a source or logical argument
- Original content — never copy from existing articles
- Client voice and brand guidelines followed when specified

## Batch Completion Report

```
CONTENT STUDIO — BATCH COMPLETE

Produced: X pieces
- X blog posts (XX,XXX total words)
- X social posts
- X email sequences

Clients served: [List]
Top keywords targeted: [keyword1, keyword2, keyword3]

Files saved to: ~/jarvis/data/content/completed/[date]/
Ready for client review.
```

## Error Handling

- If content queue is empty, produce evergreen content for the top 3 clients
- If web research yields thin results, flag the piece as "NEEDS HUMAN INPUT"
- If a client's brand guide is missing, write in neutral professional tone

## Escalation

- Content touching medical claims: Flag "MEDICAL REVIEW NEEDED"
- Content mentioning specific medications or treatments: Flag for compliance review
- Client requesting content on unfamiliar topics: Flag "RESEARCH ASSISTANCE NEEDED"

## Data Storage

- Content queue: `~/jarvis/data/content/queue/`
- Completed content: `~/jarvis/data/content/completed/`
- Client brand guides: `~/jarvis/data/content/brands/`
- SEO data: `~/jarvis/data/content/seo/`
