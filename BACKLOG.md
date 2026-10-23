# Backlog - Features to consider

*This document is used to add and describe features that could improve the process of learning the language.*
>-----------

## Translation
- [x] when type english word -- translate it to deutsch *(CLI and web lookup)*
- [x] when type phrase or sentence -- translate the sentence with accent on individual words *(CLI: Argos, D00c; web: one entry per word)*
- [ ] Less text in output (to much in a screen)

## Word list 
- [x] Show list-history of last 20-40 words *(CLI `/history`, web Verlauf)* | *with the score of "knowing", more in "Exercises")*
- [ ] Ability to chose the word and see sentence examples in different forms


## Exercises
- [x] Ability to chose the word/words and get exercises to create different types of sentences with these words. (spell check with explanation after) *(web: Sätze bilden; explanations need the AI key)*
- [x] Ability to chose few words and get randomized exercises to use certain words in answers. *(web: Abfrage)*
- [x] According to the spell-check results each word gets its score (score of user's knowing it) *(0-10 per skill)*

## Score evaluation
*Score will help to understand which words need more attention*
* The score is avaluated simply on number of clean sentences comparing to total exercieses

## Web view
*Web view can give more possibilities to enhance learnings*
- [x] Dashboard with words, scores, and exercieses
- [ ] Ability to upload a text (paste/image) and then work with it by hovering the word and see translations (+save the words and phrases to your base) *(hover translations work on every page; Texte upload is not built)*

## Backend & infra
- [x] store words from CLI usage to local file. *(user.db, `wort export`)*
- [ ] add a auto sync the words after close/time of the app
- [x] connect sync action on the web-view (security: web only reads, local only sends) *(`wort sync`, write-only token)*
