# Alerts poll Flightradar24's flight summaries every two minutes

Status: accepted (2026-11-26, RAS-144)

## Context

Hugo asked for push and email alerts when a followed flight takes off and
when it lands. Flightradar24 has no webhooks and no airline schedules: the
only way to notice a take-off or a landing is to ask. Credits are
plentiful (60,000 a month on Explorer) but not unlimited, and the app runs
on Render with no always-on worker.

## Decision

- **A `Follow` is one leg.** Following BA117 follows the next leg of that
  number to take off after the follow was made, or the leg in the air then
  (only its landing is left to tell). The leg is bound by Flightradar24's
  `fr24_id` the first time it shows up, so yesterday's landed BA117 never
  lends today's its landing.
- **A Render cron job runs `watch_flights --commit` every two minutes.** It
  asks `/flight-summary/full` about every due follow, up to 15 flight
  numbers in a call (callsigns in calls of their own). A take-off time
  appearing sends the take-off alert, and one live call fetches the ETA it
  quotes; a landing time appearing sends the landing alert.
- **Checks thin out mid-flight**: every 10 minutes while the ETA is more
  than 30 minutes away, then every run. A follow gives up after 24 hours
  with no take-off, or 20 hours in the air with no landing, and a finished
  follow is deleted a day later.
- **Each alert is sent once.** The follow records when it went, even if a
  channel failed: late or missing on one channel beats repeated on all.
- **Push is Web Push with VAPID** (`pywebpush`), signed with
  `WEBPUSH_PRIVATE_KEY`; without the keys, push is off. A subscription the
  push service calls gone (404, 410) is deleted.
- **The Following list shows progress from the clock** (take-off to ETA),
  not a live position, so opening the app spends no credits.
- **Following is a plain form post, not an outbox write.** A follow
  needs the network to be any use, and a quick lookup at follow time shows
  the route of a flight already in the air.

## Consequences

- An alert arrives within about two to three minutes of Flightradar24
  seeing the event, which is itself a minute or two behind the aircraft.
- Roughly 100 to 300 credits per followed flight, depending on how long it
  waits to take off.
- A cron job boots the app every two minutes; a background worker would be
  faster but costs an always-on service.
- Changing the VAPID keys breaks every browser's subscription: each person
  turns notifications on again.
