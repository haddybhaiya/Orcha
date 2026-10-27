# Orcha submission handoff

Prepared October 25, 2026. The DEV post is a draft, not a submitted entry.

## Review the article

- Title: **Orcha: a calmer way to decide when a purchase fits**.
- [Edit the saved DEV draft](https://dev.to/haddybhaiya/orcha-a-calmer-way-to-decide-when-a-purchase-fits-9i6-temp-slug-4727280/edit).
- DEV article ID: `4916795`.
- Local article: [SUBMISSION.md](SUBMISSION.md).
- Tags: `devchallenge`, `hf26challenge`, `ai`, `python`.
- AI disclosure: `some_ai`, also explained in the article body.
- Category: **Best Use of Gemma**.
- The narrative presents Orcha as a financial decision assistant. It briefly
  distinguishes the existing Python engine from the new assistant workflow;
  it does not attribute the project to a coding challenge.

## Verified requirements

The [official rules](https://dev.to/page/hacktoberfest-week3-2026-10-19-contest-rules)
accept a deployed demo link **or** a video. The
[official template](https://dev.to/challenges/hacktoberfest-week3-2026-10-19)
also offers these alternatives. A video and an agent transcript are optional.

The article follows the template and includes the theme, demo, code link,
architecture, open-innovation explanation, and meaningful Gemma usage.
The live demo health endpoint returned HTTP 200 with `status: ready` during this
submission pass. Existing verification reports record 229 passing local tests,
passing CI, and the three observed synthetic live workflows. Documentation-only
submission preparation did not change the application or rerun model inference.

The official entry deadline is October 25, 2026 at 11:59 PM PDT, which is
**October 26 at 12:29 PM IST**. The registry's earlier timestamp conflicts with
the specific rules; use the official rules.

## Remaining publication steps

1. Make the source accessible to judges. GitHub's authenticated repository API
   confirmed `haddybhaiya/Orcha` is **private**, with `main` as its default branch.
   The article deliberately points to `dply`, the deployed branch at commit
   `9b3e471b3bf3e90338866e887ba3300375aa3689`. No repository visibility or
   default-branch setting has been changed.
2. Review the saved draft and authorize publication. Publish the existing post;
   do not create a duplicate entry. A draft alone does not satisfy submission.
3. After publication, verify the public article body, required tags, public code
   access, and working demo link. Record its final public URL here.

A local source archive and its manifest/preflight report are prepared under
`.local/submission/`. They exclude runtime credentials, raw root dataset,
local outputs, Git history, and the InstaCloud project binding. The archive
includes the tracked legacy evidence caches required by existing tests; it is
not a claim that redistribution rights have been established for those files.
The archive has not been uploaded. Making the existing repository public would
also expose its Git history and tracked files.

The challenge requires new work during its entry window. The article discloses
the engine reuse and new assistant work; eligibility remains the organizers'
decision. The prototype's known financial-coverage limits are stated, and
specialized routing scores are not described as general financial accuracy.

No root application license was added or selected on the author's behalf.
Existing model and bundled asset notices remain intact.
