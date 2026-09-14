# README diagram sources

The four JSON files are the authored Archify sources: one component overview and one AIS query sequence, each in English and Chinese. README uses the eight light/dark PNG exports under `docs/assets/`.

The architecture sources pin repository evidence to the code-fix commit. The sequence is a representative source-derived path, not a recorded online LLM trace. Regeneration does not require application credentials.

With [Archify](https://github.com/tt-a1i/archify) available locally, run from this repository root (replace `/path/to/archify` and create the output directory first):

```text
node /path/to/archify/bin/archify.mjs validate architecture docs/diagrams/overview.en.architecture.json --quality showcase --repo-root . --json
node /path/to/archify/bin/archify.mjs deliver architecture docs/diagrams/overview.en.architecture.json /path/to/output/overview.en.html --quality showcase --repo-root . --json
node /path/to/archify/bin/archify.mjs visual-check /path/to/output/overview.en.html --json
```

For the query diagram, use `sequence` and `agent-query.en.sequence.json`; repeat for `zh-CN`. Open the delivered HTML and use its native PNG export in both themes, naming dark images with `.dark.png`. The interactive HTML is a local viewing/export artifact; GitHub README displays static images with links to enlarge them.

After architecture changes, update the evidence revision and line references along with the semantic relationships. Require 9/9 showcase checks, review both themes, and inspect the final embedded images. Do not edit exported PNG pixels to change labels.

Generated with Archify 2.17.0-dev.1. Archify is a documentation authoring tool, not an application runtime dependency. Use its matching schema if regenerating with a different version.
