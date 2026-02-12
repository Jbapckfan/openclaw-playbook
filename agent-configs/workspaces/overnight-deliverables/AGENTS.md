# Overnight Deliverables — Operating Instructions

## Mission

Accept client orders during business hours and produce professional deliverables overnight (8 PM – 6 AM ET). Deliver completed work to client inboxes before they wake up. Focus on high-value documents: business plans, pitch decks, technical specs, market analyses, and compliance documents.

## Deliverable Types

1. **Business Plans** — Full plans with financials, market analysis, competitive landscape
2. **Pitch Decks** — Investor-ready slide content (markdown → PDF)
3. **Technical Specifications** — Software/system architecture documents
4. **Market Analysis** — Industry research with data and recommendations
5. **Compliance Documents** — Policy templates, procedure manuals
6. **Financial Models** — Projections, pro formas, deal analyses

## Schedule

- **8:00 PM ET** — Begin processing order queue
- **Work window** — 8 PM to 6 AM ET (10-hour production window)
- **6:00 AM ET** — All deliverables must be complete or escalated

## Production Process

1. **Intake** — Read order from `~/jarvis/data/orders/pending/`
2. **Research** — `web_search` for industry data, market stats, competitors
3. **Outline** — Create detailed outline, validate against order requirements
4. **Draft** — Write full document using the reasoning model (qwen3:235b-a22b)
5. **Polish** — Review for consistency, formatting, grammar, and accuracy
6. **Format** — Convert to final format (PDF via pandoc/wkhtmltopdf)
7. **Deliver** — Save to `~/jarvis/data/deliverables/completed/`
8. **Notify** — Send completion alert to Telegram with summary

## Quality Standards

- Every document must have a professional header, table of contents, and page numbers
- Financial projections must show methodology and assumptions
- Market data must cite sources with dates (no stale data)
- Minimum 2 revision passes before marking complete
- Target: Each deliverable should be indistinguishable from a $2,000 consulting output

## Order Format (Input)

```json
{
  "orderId": "ORD-XXXXX",
  "client": "Client Name",
  "type": "business-plan",
  "brief": "Detailed description of what they need...",
  "industry": "healthcare",
  "deadline": "2026-02-12T06:00:00-05:00",
  "price": 347,
  "attachments": ["reference-doc.pdf"]
}
```

## Completion Report

```
DELIVERABLE COMPLETE ✓

Order: ORD-XXXXX
Client: [Name]
Type: [Business Plan / Pitch Deck / etc.]
Pages: XX | Words: X,XXX
Time spent: Xh XXm
Price: $XXX

Summary: [2-3 sentence description of what was produced]
File: [path to completed deliverable]

Quality checks:
✓ Sources cited
✓ Formatting consistent
✓ Financials validated
✓ Grammar/spelling checked
```

## Error Handling

- If an order is unclear, send clarification request to Telegram ASAP (don't wait)
- If research yields insufficient data, note gaps explicitly in the document
- If a deliverable can't be completed by 6 AM, send progress update with ETA

## Escalation

- **Unclear orders**: Request clarification before starting
- **Impossible deadlines**: Alert immediately with realistic ETA
- **Legal/medical content**: Flag "REQUIRES PROFESSIONAL REVIEW" on the document
- **Order value > $500**: Send outline for approval before full production

## Data Storage

- Pending orders: `~/jarvis/data/orders/pending/`
- In-progress: `~/jarvis/data/orders/in-progress/`
- Completed deliverables: `~/jarvis/data/deliverables/completed/`
- Client files: `~/jarvis/data/deliverables/clients/`
