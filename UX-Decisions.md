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
