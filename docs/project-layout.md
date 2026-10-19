# Code, Data, and Skill Layout

| Path | Purpose |
| --- | --- |
| `tools/build_rsi.py` | Standard-library exporter and static HTML builder |
| `tools/rsi-template.html` | Dashboard HTML, CSS, JavaScript, known model definitions, and campaign-specific narrative |
| `tools/translations.json` | Embedded Chinese/English UI translations |
| `rsi/data.json` | Previously published aggregate data used to reproduce the dashboard |
| `index.html`, `rsi/index.html` | Committed static pages; `/rsi/` is an alias |
| `dist/` | Ignored static output produced with `--output-dir dist` |
| `skills/autotrain-analysis/` | Portable English skill, metadata, and three methodological references |
| `examples/research-dynamics/` | Synthetic source fixture, frozen configuration, demo builder, and saved report artifacts |
| `requirements-demo.txt` | Plotting dependency for rebuilding demo figures only |
| `deploy/github-pages.yml.example` | Optional manual workflow, inactive until deliberately installed in your repository |

The website runs without a backend, API key, remote font, or JavaScript package installation. Its page data is embedded as JSON, and links to outside references are ordinary navigation links.

## Two distinct input formats

**Dashboard:** `tools/build_rsi.py` reads the committed aggregate (`schema_version: 2`). `--snapshot` instead accepts the campaign's trusted `atb_viz` export with `episodes`, event history, Candidate entries, timing, usage, and artifact identities. It does not accept raw Benchcore `state.json` or perform the skill's lifecycle admission checks. Read the `export` function before adapting a different snapshot format.

**Worked demo:** `examples/research-dynamics/build_demo.py` reads `fixtures/demo.json` using `autotrain-synthetic-demo-fixture-v1`. Its invented records are intentionally separate from official result schemas. They cannot be supplied directly to the dashboard exporter, and passing this demo is not validation of real episode analysis.

## Adapting another campaign

The bundled dashboard remains a reproduction of the published H200 campaign. Review its fixed task/runtime labels, Track budgets, model list, and process commentary when changing data. The exporter currently embeds the same campaign metadata. Update both code and translations for a different experiment; do not merely substitute numerical rows underneath unrelated conclusions.

For analysis of real runs, use the skill with original read-only records, explicit provenance, a compatible result validator, and confirmed termination/cleanup. Publish derived data only under the applicable ANALYSIS visibility policy. An export that omits raw logs is not, by itself, publication authorization or proof of fair comparability.
