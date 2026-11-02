# Your own pictures

Any picture you put here stays on your computer: Git ignores everything in this folder except this file and the
example. Each app you don't list keeps its neon figure.

1. Add your images to this folder. Widescreen works best, at least 1280x720.
2. Copy `pictures.example.json` to `pictures.json` and edit it.
3. Run `./setup.sh <device ip:port> --no-debloat --no-airplay`, and turn the Home button helper back on afterwards.

| Field | What it does |
|---|---|
| `file` | The image's file name in this folder |
| `package` | The app it belongs to. List yours with `adb shell pm list packages` |
| `tagline` | The short line shown above the row. Leave it out to keep the current one |
| `mirror` | `true` flips the picture, to put a person on the right, away from the text |
| `shift` | Pixels to move the picture right, away from the clock and tagline |
| `brightness` | `1.0` is unchanged. Use about `0.8` for bright pictures |

## Copyright

Film and TV stills, game art and channel thumbnails normally belong to someone else. Don't commit them, and don't
publish a fork or theme with them in it. Use pictures you have the right to use, and if you're unsure, keep them
to your own device.
