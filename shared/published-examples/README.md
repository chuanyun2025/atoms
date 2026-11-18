# Published website and slide examples

These snapshots are three websites and three slide decks selected from the user's
completed projects. The homepage displays all six, and the slides page also displays
the three complete decks above its existing templates.

| ID | Title | Kind |
| --- | --- | --- |
| jinheng-finance | 金衡财经 · 深色行情门户与资讯分析站 | Website |
| independent-studio | 独立站 · 深色编辑杂志风品牌单页 | Website |
| shiguang-amber | 拾光集 · 琥珀暖光的日用选物店 | Website |
| shenzhen-travel | 深圳旅游规划演示文稿 | Slides |
| annual-review | 年度个人工作汇报 · 网页幻灯片 | Slides |
| customer-q2-review | 客户运营团队 Q2 复盘 | Slides |

Each JSON includes the source artifact, the compiled bundle, and the sanitized `build_story`
archive extracted from the same successful version's SQLite run chain (`scripts/extract_example_build_stories.py`).
Private conversations, project and visitor identifiers, raw agent planning files,
and saved application data are excluded. Covers in `apps/web/public/examples/` are actual
page screenshots. Previews use the existing isolated SDK, without model calls or writes
to the author's original projects. Each example has separate browser-tab memory for
its own demonstration data.

The allowlist and snapshot loading live in `apps/api/atoms/examples.py`, and gallery
metadata lives in `apps/web/src/studioExamples.ts`. Update the source, compiled bundle,
cover, and metadata together when replacing a published example.
