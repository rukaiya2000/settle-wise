# Dashboard Spec

## Goal

The dashboard should be a simple two-screen demo:

1. A people/profile page where the user sees existing debt profiles and can trigger the automated voice agent for any person.
2. A person progress page where the user selects a profile and sees what the agent has done: calls made, debt collected, amount promised, SMS links sent, and next action.

This is clearer than a broad portfolio dashboard because the hackathon story becomes personal and easy to follow: pick a borrower, run the agent, watch recovery progress.

## Screen 1: People Profiles

The first screen should show existing borrower/debt profiles.

Primary purpose:

- Let the user understand who owes money.
- Let the user trigger the automated agent against a specific profile.
- Let the user open that person's progress page.

Profile card/table fields:

- borrower name
- phone number
- amount due
- breach date
- salary date, if known
- current status
- last call summary
- next action

Primary actions:

- `Run agent`
- `Retry now`, when a previous call failed or follow-up is due
- `View progress`

Example card:

```text
Riya Sharma
Amount due: $850
Breach: Aug 10
Salary date: 5th of every month
Status: Promised
Last call: Can pay $300 today, rest after salary.

[Run agent] [View progress]
```

Status values:

- `new`
- `scheduled`
- `calling`
- `no_answer`
- `callback_requested`
- `promised`
- `link_sent`
- `missed`
- `paid`
- `needs_review`

Sorting:

- Default sort should be breach urgency first.
- Secondary sort should be amount due.

Filters:

- all
- needs call
- promised
- paid
- needs review

## Screen 2: Person Progress

This screen focuses on one selected borrower/debt profile.

It should answer:

- What happened after the agent was triggered?
- How much has been collected?
- How many calls were made?
- Did the borrower promise to pay?
- Did we send an SMS payment link or reminder?
- What happens next?

### Key Measures

Keep the metrics few and highly relevant:

- amount due
- amount collected
- amount promised
- calls made
- SMS links sent
- next action

Optional:

- days until breach
- recovery percentage
- last contact time
- next scheduled call/reminder time

### Progress View

Use a simple timeline instead of a complex chart.

Example:

```text
1. Voice call started
2. Borrower said full payment is not possible today
3. Agent negotiated $300 today + $550 after salary
4. SMS payment link sent for $300
5. Borrower clicked payment link
6. SMS reminder scheduled for salary date
```

### Mini Progress Bar

Show one simple progress bar:

```text
$300 collected / $850 total
35% recovered
```

If there is a promise:

```text
$300 collected + $550 promised = $850 covered
```

### Call History

Show a short list of voice calls:

- call time
- outcome
- duration, if available
- summary
- promise amount

Example:

```text
Jul 31, 12:05 PM
Outcome: promised
Summary: Riya can pay $300 now and remaining $550 on Aug 5.
```

### SMS History

Since SMS is not a conversation channel, this should be a simple activity feed.

SMS types:

- payment link
- reminder
- confirmation

Example feed:

- Payment link sent to Riya for `$300`
- Reminder scheduled for Riya on salary date
- Confirmation sent after payment

### Memory Learned

Shows the agent becoming smarter over time.

Examples:

- Riya gets paid on the 5th.
- Best call time is after 6 PM.
- Riya prefers two installments.

This is important for the demo because it proves the agent is not just blasting calls; it is learning useful borrower context.

## Demo Interactions

Minimum interactions:

- Select a person from the profiles page.
- Click `Run agent` against that person.
- Click `Retry now` if the previous call was `no_answer` or a promise was missed.
- Advance the demo clock by `+1 hour`, `+1 day`, or `+3 days`.
- Show live or simulated call progress.
- Send SMS payment link after negotiation.
- Mark payment link as `paid`.
- See that person's metrics update.

Nice-to-have interactions:

- Simulate no answer.
- Simulate borrower promise.
- Simulate borrower asking for discount.
- Simulate human review case.

## Data Needed

Use the simple schema from [data-model.md](./data-model.md):

- `debts`
- `calls`
- `sms_messages`
- `memory`
- `demo_clock`

No separate account, borrower, consent, or payment tables are needed for the hackathon demo.

## Visual Direction

The dashboard should feel like a focused fintech ops tool:

- dense but clean
- table-forward
- clear numbers
- restrained colors
- status chips
- no landing-page hero
- no decorative cards inside cards

Suggested palette:

- dark ink for headers
- white panels
- green for collected
- blue for promised
- red or amber for risk
- teal for agent activity

## Judging Story

The dashboard should help tell this story in under two minutes:

1. Here are people with debts that will breach soon.
2. Pick one person and click `Run agent`.
3. The voice agent calls and negotiates payment.
4. SMS sends the payment link or reminder.
5. The person progress page updates: calls made, amount collected, amount promised, and next action.
6. The agent remembers salary date and best call time for future recovery.

## Proposed Navigation

```text
/profiles
  List of people/debt profiles
  Run agent button
  View progress button

/profiles/:id
  Person progress page
  Key metrics
  Call history
  SMS history
  Memory learned
  Next action
  Manual retrigger button
```

## Demo Clock UI

Add a small clock control visible on both pages.

```text
Demo time: Aug 1, 2026 09:00

[+1 hour] [+1 day] [+3 days] [Reset]
```

When time advances:

- scheduled calls become due
- SMS reminders fire
- payment checks happen
- profile statuses update
- person progress timelines get new events

This is how the demo can show several days of agent progress quickly.
