# Reviewing (frontier seats, and standard seats on the review floor)

Read this only when you hold work from queues 1–2.

0. Claim the review — same protocol as ticket claims: `glab mr note <iid> --message "review-claim: $INSTANCE $(date -u +%FT%TZ)"`, re-read the comments; if a fresher-than-24h `review-claim:` from another instance predates yours, back off to the queues. Claim held → also `glab mr update <iid> --reviewer <your-bot-user>` so the UI shows who is reviewing (the comment stays the source of truth).
1. Review the MR against its originating issue's brief with mattpocock-skills:code-review.
2. Findings → comment each on the MR **and add the `changes-requested` label** (`glab mr update <iid> --label changes-requested --assignee <author-bot-user>`) — the label routes the MR into its author's queue 0 (without it the findings rot), and the assignee makes "whose move" visible. Clean → approve and merge.
3. **`glab mr merge` lies** — it prints success on failure. After merging, verify with `glab api projects/:id/merge_requests/<iid>` and confirm `state == "merged"` and `merged_at` is set.
4. Review-floor case (standard seat merging a `review:frontier` MR while the frontier model is unavailable): after the verified merge, label the merged MR `needs-frontier-review` — that is the debt queue.
5. Review-debt case (merged MR): review the merged diff; findings become new issues labeled `needs-triage`; finish by removing `needs-frontier-review` from the MR.
6. Record your clock: post `/spend <minutes>m` **as its own note on the MR** (a note containing only quick actions executes and vanishes; mixed with text it posts literally), minutes = now minus your review-claim timestamp.
