# UX decisions

General interface rules, written without reference to a particular app, screen or feature, so they can move into the
design system as they are. One rule per entry: the rule, why, and where it came from (date, who decided).
Status `draft`: agreed here, not yet in the design system; `in DS`: moved, with the design-system commit or PR.

## Layout

### UX-1: A sidebar that changes the main area sits on the left, and the layout takes the full window width

- **Rule:** when a sidebar selects or filters what the main area shows, put it on the left of the main area and let
  the page run the full window width instead of a centred column. On a narrow window the sidebar stacks above the
  main area. A collapsed sidebar that opens over the page on hover lies above all page content.
- **Why:** reading goes left to right, so the control comes before what it controls; a centred column with a sidebar
  leaves the content squeezed between two empty margins.
- **Source:** 2026-10-29, garv. **Status:** draft

### UX-2: Section switches of one area are equal bars under the main navigation

- **Rule:** an area with several sections shows them as a row of equal-width header bars directly under the main
  navigation, each with the section name as a link. A section with unfinished work shows its progress as a quiet
  caption next to its name (e.g. "3 / 5").
- **Why:** the sections are siblings of equal weight; equal bars say that, and the caption tells where work is waiting
  without opening it.
- **Source:** 2026-10-29, garv (from the design canvas). **Status:** draft

### UX-3: A search block keeps one even space around its field and is closed by a divider

- **Rule:** in a block that holds a single field (search, lookup), the space from the bar above to the field, from the
  field to the divider that closes the block, and from that divider to the content below is the same token.
- **Why:** one repeated distance reads as one deliberate rhythm; different gaps make the field look misplaced.
- **Source:** 2026-10-29, garv. **Status:** draft

## Flows with several steps

### UX-4: Show one step at a time; the next one opens only on an explicit action

- **Rule:** in a sequence of tasks or questions, show the current one only. After it is answered, the next appears
  only when the user presses a "next" action; do not append it automatically below.
- **Why:** the user decides when they are done with a step (reading feedback, trying again); an automatic next step
  pulls attention away from the feedback.
- **Source:** 2026-10-29, garv. **Status:** draft

### UX-5: Navigation inside a sequence covers the done steps and the current one only

- **Rule:** tabs or a stepper that switch between the steps of a sequence list the completed steps and the current
  one. Later steps are not shown until they are reached, rather than shown as controls that do nothing.
- **Why:** a control that looks clickable and does nothing is a dead end; the count "step N of M" already says how
  much is left.
- **Source:** 2026-10-29, garv. **Status:** draft

### UX-6: An item that is not available yet is muted and not a link

- **Rule:** in a list of items (e.g. a sidebar), an item whose content is not reachable yet is shown in the muted text
  color and is not interactive.
- **Why:** it stays visible for orientation but does not invite a click that leads nowhere.
- **Source:** 2026-10-29. **Status:** draft

### UX-7: Each area keeps its own unfinished work

- **Rule:** switching to another area resumes that area's unfinished work instead of discarding the work in the area
  being left. Starting something new in an area replaces only that area's unfinished work.
- **Why:** moving between areas is exploration, not a decision to throw work away.
- **Source:** 2026-10-29, garv. **Status:** draft

## Attempts and feedback

### UX-8: A new attempt is added below the previous one, never in its place

- **Rule:** when the user answers the same question again, the new answer and its feedback appear below the earlier
  ones, as the next message. Each attempt is labelled with the question it belongs to and its attempt number. If only
  the first attempt is scored, every later attempt says so ("not scored").
- **Why:** comparing attempts is how one learns from them; replacing the old one hides the progress.
- **Source:** 2026-10-29, garv. **Status:** draft

### UX-15: Once checked, an answer is one bubble

- **Rule:** after a written answer is checked, it is shown as a single message: the corrected version (the user's
  text with the wrong parts struck through and the right ones beside them) when there are corrections, else the
  answer as written. The answer and its correction are not shown as two messages.
- **Why:** the corrected version already contains the answer; two near-identical messages make the user compare
  them instead of reading the marks.
- **Source:** 2026-10-29, garv. **Status:** draft

### UX-9: The corrected text stands in full, in the success color, under the marked answer

- **Rule:** when a written answer has corrections, its message shows the user's text with the wrong parts struck
  through and the right ones beside them, and under it, set apart by a hairline divider, the whole corrected text as
  one line in the success color (a themed green that keeps its contrast on the dark surface). The same text is not
  repeated elsewhere in the feedback.
- **Why:** marks show what was wrong; the clean corrected version, read in the same place, is what the user should
  remember.
- **Source:** 2026-10-29, garv. **Status:** draft
### UX-10: An error offers a next step that works without optional services

- **Rule:** every reported mistake links to a place where its rule can be learnt or practised, and that link must
  not depend on an optional or paid service being on.
- **Why:** an error without a next step is a dead end; an optional service may be off.
- **Source:** 2026-10-29. **Status:** draft

### UX-11: Entrance animation only for content that just arrived

- **Rule:** content animates in only when it is new (a result just returned). A page reloaded for another action
  (opening a field, switching a tab) shows everything at once.
- **Why:** replayed animation reads as new information when nothing changed.
- **Source:** 2026-10-29. **Status:** draft

### UX-16: Exchange messages carry a tail on their speaker's side

- **Rule:** in a question-and-answer exchange, each message box has a small triangle at its bottom corner on its
  speaker's side (the other voice on the left, the user on the right), in the box's own fill or outline. In a
  practice exchange the task has the strong (inverted) fill and the user's answers are outlined boxes on the page's
  surface color (white in the light theme), so the two voices are told apart by fill as well as by side; colors
  inside an answer (corrections) are chosen to keep their contrast on that surface.
- **Why:** the tail turns boxes into turns of a conversation and shows who speaks without reading the label.
- **Source:** 2026-10-29, garv; the answers' fill changed from inverted to outlined on the surface color 2026-10-30,
  garv. **Status:** draft

### UX-17: Sending shows the sent content at once, then a progress indicator until the result

- **Rule:** after the user sends something that takes time to check, their content appears immediately where the
  result will go, followed by an indeterminate progress bar; the send controls are disabled. The result then arrives
  in steps (its parts fade in one after another).
- **Why:** the user sees the action was taken and cannot send twice; the wait has a place on the screen.
- **Source:** 2026-10-29, garv. **Status:** draft

### UX-18: The detailed feedback lies hidden under its answer, behind "Explain more"

- **Rule:** the detailed feedback on an answer (the assessment and every mistake explained: what was written, the
  right form, the reason, the rule table with the right cell marked, a rule to remember, where to practise it) is a
  block directly under the answer that always starts hidden. A small text button under the answer, "Explain more" /
  "Hide explanation", shows it, coming out from under the answer with a short fade.
- **Why:** the corrected line already answers "what is right"; the explanation is for the user who wants to know
  why, and otherwise takes the room the next attempt needs.
- **Source:** 2026-10-29, garv. **Status:** draft
### UX-19: Working areas with framed blocks sit on a slightly grey page

- **Rule:** an area made of separate framed blocks (answers, feedback) uses a slightly darker page fill than the
  blocks themselves, so each block stands apart; navigation, sidebars and inputs keep the surface color.
- **Why:** white on white makes frames do all the separating; a light fill under them groups and lifts the blocks.
- **Source:** 2026-10-29, garv. **Status:** draft

## Tables and lists

### UX-14: Rows of a table offer their actions in a context menu; removing asks first

- **Rule:** a table whose rows are items the user owns gives each row a context menu (right click, and the Menu key
  or Shift+F10 from the keyboard) with the row's own actions: open first, then the frequent actions, then a divider
  and the destructive one last. A destructive action opens a confirmation that names the item and says what else
  is lost and that it cannot be undone; the confirming button is the red one.
- **Why:** row actions stay out of the way until asked for; the order puts the safe choice where the pointer lands
  and the destructive one furthest from it; naming the item prevents removing the wrong row.
- **Source:** 2026-10-29, garv (context menu and removal requested; order and confirmation proposed). **Status:** draft

## Language

### UX-13: The interface language is separate from the content language

- **Rule:** in a product that teaches or shows content in one language, the interface (navigation, buttons,
  headings, messages) follows the user's chosen interface language, while the content and its verdict words stay in
  the content language. The switch is a dropdown in the right part of the main navigation, showing the current
  language by its own name (English, Deutsch); the choice belongs to the user's profile.
- **Why:** the user must always understand how to operate the product, while the content keeps its learning value;
  a language name in its own language is recognisable to someone who cannot read the current one.
- **Source:** 2026-10-29, garv. **Status:** draft

## Brand

### UX-12: The favicon is one mark in one accent color, the same in both themes, without an outline

- **Rule:** the favicon is the logo mark alone, filled with one accent color from the palette that reads on light and
  dark browser chrome, with no outline or per-theme variant.
- **Why:** one file, recognisable in any tab bar; an outline at 16px turns into noise.
- **Source:** 2026-10-29, garv. **Status:** draft

## Answers, controls and small screens

Added with the GUI refresh of 2026-10-30. The source of each is the review in `GUI-REFRESH.org` (what was measured on the
screen) and garv's request to follow current good practice rather than the design system's own rules. These wordings are
written by Claude and not yet reviewed by garv. Status of all: `draft`.

### UX-20: The verdict of an answer is always visible; only its explanation is folded

- **Rule:** the first thing under a checked answer is its verdict: a badge (glyph, word and colour), what it was worth
  ("Score +1", or "not scored"), and one line per part that was judged. Only the longer explanation (UX-18) waits behind
  "Explain more", and that button appears only when there is something to explain. The newest verdict takes the focus when
  it appears, so a screen reader reads it.
- **Why:** "was I right, and what did it count?" is the question after every answer; hiding it behind an expander made a
  right answer and a wrong one look the same until the learner opened it.
- **Source:** 2026-10-30, GUI refresh (the hidden verdict was a critical finding). **Status:** draft

### UX-21: A verdict is never colour alone

- **Rule:** every verdict or state shown by colour also carries a glyph and a word (✓ right, ~ almost, ✗ wrong, i a hint),
  in a badge with a border. Text colours for them are chosen for 4.5:1 on the surface they sit on, in both themes.
- **Why:** colour-blind users and anyone in poor light cannot tell red from green; a glyph and a word cost nothing.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-22: One filled button per screen; the rest are outlined or plain

- **Rule:** the one action a screen is for ("Start", "Send", "Next task") is the only filled button; alternatives are outlined;
  the quiet ones ("Save and leave", "Answer again") are plain text. Every button is at least 44 px high.
- **Why:** with every action drawn the same, the main one has to be found by reading; a size and a fill say it first, and
  44 px is the smallest target a thumb hits reliably.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-23: What is needed to answer stays visible; what only helps is one disclosure that works without hover

- **Rule:** the options of a multiple-choice task and any notice that changes how to answer stay on the page. Hints, an
  example answer and "what this form means" sit in one disclosure ("Hints") that opens by keyboard and by touch. Nothing
  needed is behind a hover tooltip.
- **Why:** a tooltip does not exist on a touch screen and is easy to miss with a keyboard; options that are hidden make
  the task unanswerable.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-24: A way out says what happens to the work

- **Rule:** a control that leaves an unfinished sequence says whether the work is kept ("Save and leave"); it does not say
  "Finish" unless it ends the sequence and shows the result.
- **Why:** a label that promises an end while the work stays open makes the learner wonder whether it was lost.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-25: The progress of a sequence is stated once, and its steps show how each one went

- **Rule:** one line ("Task 2 of 5") and one bar say where the learner is; the steps beside it list the finished tasks and
  the current one (UX-5), each with the glyph of its verdict, and link back to it. The same count is not repeated as a
  title suffix, a tab strip and a sidebar caption.
- **Why:** three counters that say the same thing compete with the task; steps that carry the outcome add something the
  count cannot.
- **Source:** 2026-10-30, GUI refresh (the "Task 1" label appeared five times at once). **Status:** draft

### UX-26: In a row of sections, the open one is marked by more than colour

- **Rule:** the open section of a section switch (UX-2) is marked by a heavy underline and a stronger weight; the others are
  in the muted text colour, which still passes 4.5:1. Each section's caption (progress) stays beside its name.
- **Why:** three equal titles gave no sign of where the learner was.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-27: A phone gets a header that scrolls away and side lists that fold

- **Rule:** under 720 px the sticky header becomes ordinary page content, a list that sits beside the content on a wide
  window (a session's words) becomes one disclosure row above it, and a full-height region uses the visible window height
  (`dvh`), not the largest one.
- **Why:** the header, mode row and a word list together took more than half of a phone screen before the task; a bar
  pinned to `100vh` ends up under the browser's own bar.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-28: Text in another language than the interface is marked as such

- **Rule:** content in a different language from the interface (the words and sentences being learnt, translations) carries
  its own `lang`; the interface text around it does not.
- **Why:** a screen reader reads German with English pronunciation unless it is told; it is also what makes UX-13 usable
  without sight.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

### UX-29: A text field says how it is sent

- **Rule:** under a multi-line answer field, one line says "Enter sends · Shift+Enter starts a new line". Focus starts in the
  field when a task waits (not on a touch screen, where it would open the keyboard over the task).
- **Why:** Enter-to-send is a convention of chat, not of forms, and nothing tells a first-time user.
- **Source:** 2026-10-30, GUI refresh. **Status:** draft

## Lists, selection and fields

Added with the second GUI refresh of 2026-10-30 (the word list and the texts). Wordings written by Claude, not yet
reviewed by garv. Status of all: `draft`.

### UX-30: A bar above a list says what is chosen, or why its actions wait

- **Rule:** the actions that need a choice (practise, delete, move) sit in one bar above the list, always in the same
  place. With nothing chosen the bar says what to do ("Select words to practise them") and its buttons are disabled; with
  a choice it says how many ("2 selected") and the buttons work. The main action is the filled one (UX-22).
- **Why:** buttons that are simply grey leave the reader guessing whether the page is broken; a sentence beside them
  answers it, and a bar that stays put does not move the list when the first row is ticked.
- **Source:** 2026-10-30, GUI refresh (finding W-a). **Status:** draft

### UX-31: The field a page is for has a visible label and its own button

- **Rule:** a search or lookup field carries a visible label above it and a button beside it; Enter also works. A filter of
  a list on the same page has a visible label too. A placeholder is an example, never the label.
- **Why:** a grey box with a placeholder gives no name once text is typed and no hint that it can be sent by touch; the
  label stays and the button is a target for a thumb.
- **Source:** 2026-10-30, GUI refresh (finding W-b). **Status:** draft

### UX-32: Row selection is visible without hover

- **Rule:** the checkbox of a row is drawn at all times, not only under the pointer. Rows are at least 44 px high.
- **Why:** a touch screen has no hover, so a hidden checkbox means selection cannot be found, and a keyboard user only
  meets it by tabbing into it.
- **Source:** 2026-10-30, GUI refresh (finding W-a). **Status:** draft

### UX-33: A destructive action asks first, from every place it can be reached

- **Rule:** removing something that takes other data with it (a score, answers, notes) asks for confirmation in the
  same way from the row menu, from the open item and from anywhere else; the confirmation names the item and says what
  goes with it. The confirming button is the destructive one, in the error colour, and is not filled.
- **Why:** the same action answering at once from one place and asking from another teaches that the confirmation is
  optional; a name in the question makes a wrong click visible.
- **Source:** 2026-10-30, GUI refresh (the open word's "Remove word" deleted at once, the row menu asked). **Status:** draft

### UX-34: A count has a singular

- **Rule:** counts and result lines use the singular where the number is one ("1 word", "1 hit"), in every interface
  language, not "1 words".
- **Why:** it is the first thing a reader notices as unfinished.
- **Source:** 2026-10-30, GUI refresh (finding W-d). **Status:** draft
