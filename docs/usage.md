# Usage

## Asking a question

Type into the box on the home page and press <kbd>Enter</kbd>. Use
<kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line.

Questions work best when they name a subject:

- Good: *what is a vector database*, *who was Ada Lovelace*, *how does
  photosynthesis work*
- Weaker: *tell me something interesting*, *explain everything*

The engine matches your words against page text. A question with a clear
subject gives it something to match.

## Reading the answer

Every sentence ends with a small numbered pill like `1`. That number is the
source it came from. Click it and the page scrolls to that source card and
highlights it briefly.

The answer is assembled from sentences that exist on the pages we fetched. It
is not a paraphrase and it is not generated — which is why it reads like a
summary rather than a chat reply. That is the trade: you give up some fluency
and get a claim you can verify in one click.

## Reading the sources

Each source card shows:

- **Title** — click to open the page in a new tab
- **Domain** — where it came from
- **A badge** — `read` means we fetched and parsed the page; `snippet only`
  means we only saw the search result summary. A `snippet only` source is
  weaker evidence, and the badge says so.
- **A snippet** — the relevant extract

Sources are numbered in the order they appear in the answer, so `[2]` in the
text is always the second card.

## Follow-up questions

Below the sources you'll see suggested follow-ups. They are built from the
titles of the pages that were retrieved, so a suggestion is never a question
the sources can't answer.

Click one to ask it. If you're signed in, it continues the same thread and the
context carries over.

## Accounts

Signing in is optional. Anonymous searches work fully — you just don't get
history.

**To create an account:** click *Sign in* in the top bar, then *Create an
account*. Email and a password of at least 8 characters. No email verification
step.

**To sign out:** click your name in the top bar.

## History

Click *History* in the top bar. You'll see your past searches, newest first,
with a relative timestamp.

- **Click a search** to reopen it with its answer and sources intact.
- **Click ×** to delete it. This is immediate and permanent.

History is per-account. Nobody else can see it, and a shared link does not
expose your other searches.

## Sharing

Open a saved search and click *Share*. That creates a public, read-only link
and copies it to your clipboard. Anyone with the link can read that one search
— no account needed.

The link looks like `https://your-host/s/AbC123xYz`. Sharing is per-thread;
sharing one search does not expose any other.

To stop sharing, delete the thread.

## Copying an answer

Click *Copy answer*. You get the answer text plus a formatted source list, so
pasting it into a document or a message keeps the citations meaningful.

## Tips

**Be specific about the subject.** *What is retrieval-augmented generation*
beats *how does RAG work* because the first matches the article title.

**Check the badges.** If every source says `snippet only`, the answer is built
from search summaries rather than page content. Treat it as a lead, not a
conclusion.

**Follow the citations on anything that matters.** The whole point of this tool
is that you can. If a sentence's source doesn't support it, that's worth
knowing.

**Ask a narrower follow-up when an answer is thin.** The engine retrieves per
question; a more specific question retrieves more specific pages.

## Keyboard shortcuts

| Key | Action |
|---|---|
| <kbd>Enter</kbd> | Ask |
| <kbd>Shift</kbd>+<kbd>Enter</kbd> | New line in the question box |
| <kbd>Esc</kbd> | Close the sign-in dialog |
