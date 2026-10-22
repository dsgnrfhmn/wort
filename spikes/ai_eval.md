# AI model test (run by the maintainer, before enabling D0r)

Goal: decide whether `claude-haiku-5-5` is enough for the sentence check or `claude-sonnet-5-5` is needed.
Nothing here runs from the dev machine; the key lives only on the server.

1. Collect 20-30 real learner mistakes (sentence + the target word + task + what is wrong). Mix: article/case
   (10), verb form/word order (8), plural/preposition (6), 4 correct sentences (to catch false alarms).
   Remove names and private details first.
2. For each, call `AnthropicProvider.check_sentence` with `WORT_AI_CHECK_MODEL` set to each model in turn.
3. Score each reply by hand:
   - caught: the real error is in `errors[]` (right fragment, right correction);
   - missed: a real error is absent or the sentence is marked right;
   - false alarm: a correct sentence gets errors;
   - invalid: the reply fails schema validation.
4. Record in DECISIONS.md D0r: per model caught / missed / false alarms / invalid, median latency, cost for
   the set. Decision rule: Haiku if it misses at most 2 of the real errors and has 0 false alarms; otherwise
   Sonnet for the sentence check only.
