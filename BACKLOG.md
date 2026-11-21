# Backlog - Features to consider

*Ideas for the CLI. Plan and status: [`PLAN.org`](PLAN.org).*
>-----------

## Translation
- [x] when type english word -- translate it to deutsch
- [x] when type phrase or sentence -- translate the sentence *(Argos, D00c; since 2026-11-21 only the translation is shown, D00k)*
- [ ] Less text in output (to much in a screen)

## Word list
- [x] Show list-history of the words *(`/history`, Words and Sentences tabs, delete with `x`)*
- [ ] Ability to chose the word and see sentence examples in different forms

## Exercises *(prototype: `wort tui`)*
- [ ] Ability to chose the word/words and get exercises to create different types of sentences with these words (spell check with explanation after)
- [ ] Ability to chose few words and get randomized exercises to use certain words in answers
- [ ] According to the results each word gets its score (score of user's knowing it)
  * The score is evaluated simply on number of clean sentences comparing to total exercises

## Backend & infra
- [x] store words from CLI usage to local files *(`words.jsonl`, `sentences.jsonl` in the data repository)*
- [x] sync the history to GitHub *(`wort sync`)*
- [ ] auto sync the history after close/time of the app
- [ ] let an AI assistant in the browser read and write the data repository *(only through the validated files; see README "History and sync")*

## Ideas & inspiration (brainstorm)
*Other tools to look at for new exercise types and features. Ideas only: their content is not copied.*
- [ ] **LearningApps.org** (https://learningapps.org/) — a source of exercise *types*, not content *(added 2026-10-28)*
  - Rebuild the types natively on wort's own data, graded locally: matching pairs, Lückentext, ordering, quiz, crossword, grouping.
