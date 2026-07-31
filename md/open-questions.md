# Open Questions

## Hackathon Demo

- What is the best 2-minute demo story?
- Should the voice call be simulated through transcript text, browser speech APIs, or a real-time voice model?
- Should the dashboard look like a collections ops cockpit or a CRM-style queue?
- Should payment be simulated with a fake checkout page?
- Should SMS sending be a pure mock event or use a real provider in demo mode?

## Business Policy

- What is the demo definition of breach?
- What is the minimum acceptable payment today?
- What installment lengths look good in the demo?
- What discount rule is easy to explain?
- Which offers require a human approval modal?
- What fake payment states should exist?

## Product

- Should the first experience be agent autopilot, human copilot, or both?
- How polished should the call transcript experience be?
- Should borrowers get a self-serve portal?
- Should the agent support multiple languages at launch?
- How should managers configure offer ladders?
- What dashboard widgets make the agent feel valuable?

## Engineering

- Should seed data live in JSON, SQLite, or Postgres?
- Should payment links route to a fake `/pay` page?
- How should call transcripts and SMS events be shown in the UI?
- Which model/runtime will power conversations?
- How much of the agent reasoning should be visible?

## Evaluation

- What is the baseline recovery rate?
- What is the acceptable escalation rate?
- What policy violations should be tested before launch?
- What conversation simulations are needed?
- How will human reviewers rate agent quality?
- What borrower complaints should trigger product changes?
