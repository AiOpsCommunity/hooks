<!--
For a new hook, keep all of this. For a docs or infrastructure change, delete
what does not apply and say what you changed.
-->

## What this hook does

<!-- One or two sentences, from the perspective of someone who would install it. -->

**Event:**
**Matcher:**
**Blocks anything?** yes / no — if yes, what and why

## Why it is worth having

<!-- What goes wrong without it. Skip the sales pitch; a concrete annoyance is enough. -->

## What it deliberately does not do

<!--
The most useful section for a reviewer. Known gaps, false negatives, cases you
chose not to handle. A hook that claims to cover everything gets more scrutiny,
not less.
-->

## Testing

- [ ] `./scripts/validate.sh` passes
- [ ] `./scripts/pr-policy.sh` passes
- [ ] Installed locally (`/plugin marketplace add ./`) and confirmed with `/hooks`
- [ ] Triggered the event and confirmed it fires
- [ ] Confirmed it does **not** fire where it should not
- [ ] For a blocking hook: tested both the blocked case and a normal case it must leave alone

<!-- Paste the actual output. "Tested, works" is not testing. -->

```
```

## Safety

- [ ] No network calls, or they are the point of the hook and the README says so
- [ ] Reads nothing it does not need (no `.env`, keychains, SSH keys, tokens)
- [ ] Writes nothing outside the project directory
- [ ] Nothing downloaded or executed at runtime
- [ ] Script is dependency-free, or the README states the dependency and fails clearly without it
- [ ] I would run this on my own machine, on every matching event, without being asked

<!--
The `review-flags` job posts a table of lines worth reading. It never fails the
build. If it flagged something, explain it here rather than leaving the reviewer
to guess.
-->
