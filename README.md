# IM binding dialog: before and after

Screenshots for the IM binding change in bytedance/deer-flow. They show what a user sees after clicking Connect next to a binding-code app in the sidebar.

| File | What it shows |
| --- | --- |
| `binding-before-en.png`, `binding-before-zh.png` | `main`: the `/connect` command in a success toast that disappears, in English even in the Chinese UI |
| `binding-after-en.png`, `binding-after-zh.png` | This change: a dialog keeps the command on screen with a copy button, the expiry time and the binding status |

Both were captured from production frontend builds (`main` and this change) with Playwright against mocked Gateway responses and a fixed clock. The binding code is a made-up example.
