# Published game examples

These four snapshots are the user-selected successful projects shown first in the game gallery.
They do not query a private project or require a model call to play.

| ID | Title |
| --- | --- |
| jungle-assault | 丛林突击：魂斗罗 |
| meadow-journey | 草原跳跃：三关奇旅 |
| neon-coast | 霓虹赤湾 · 海岸环线竞速 |
| warehouse-breakout | 仓库突围：冷光行动 |

Each JSON contains the generated source artifact, its compiled preview bundle, and the sanitized
`build_story` run archive extracted via `scripts/extract_example_build_stories.py`, frozen together.
Raw agent planning and research files, project and visitor identifiers, conversations, and saved app data
are excluded. Covers in `apps/web/public/examples/` show actual gameplay.

The API serves only the explicitly listed IDs through the existing sandbox renderer and CSP.
The gallery uses the same preview SDK as projects, with separate in-memory state for each example
in the visitor's browser tab. Playing or restarting an example cannot change the original project.
Keep the source, compiled bundle, cover, and gallery entry in sync when publishing a new snapshot.
