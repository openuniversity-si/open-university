# ADR-06 spike: how `mux-video` takes the signed token

Status: deprecated by D-111 (the Open University product left this repository; PADRAO-DEV F3a).

Superseded (D-062, 2026-10-26): Mux is removed from the app ([ADR-11](ADR-11-playback-engine.md)). This page records the 2026-10-09 spike only; none of the files or packages it names exist.

Source: `@mux/mux-video@0.31.5` and `@mux/playback-core` (bundled code and `.d.ts`), read 2026-10-09. No network spike: the real check is `pnpm mux:probe --once` after deploy.

## Findings

- The element accepts the playback token as the `playback-token` attribute or the `playbackToken` property (`tokens.playback` is the same value; `tokens.thumbnail` / `tokens.storyboard` / `tokens.drm` are separate).
- playback-core's `toMuxVideoURL` builds `https://stream.mux.com/{playbackId}.m3u8`. When a token is present it **drops every other query parameter** (`max_resolution`, `min_resolution`, rendition order…) and sets only `?token=<jwt>`. Those options must be claims in the JWT, not attributes.
- Nothing is requested until `playback-id` is set. The poster is ours (F04b media repository), so no `image.mux.com` thumbnail token is needed.
- JWT shape the server signs (`src/playback/token.ts`): RS256, `kid` header, claims `sub=<playbackId>`, `aud="v"`, `exp = now + duration + 1 h`.
- `startTime` (`start-time`) sets the first position before load; afterwards we set `currentTime`.
- Mux Data is on by default (`disable-tracking` turns it off). Beacons go to `*.litix.io`, which the no-video guard blocks in tests; the test build has no `mux-video` at all.

## Decision

- `src/playback/mux-engine.tsx` (`MuxTransport`) dynamically imports `@mux/mux-video` and `media-chrome/dist/media-controller.js` on intent (hover, focus, pointerdown) or on the play gesture. It then creates `<media-controller nohotkeys gesturesdisabled noautohide>` around `<mux-video slot="media" playsinline>`, sets `playbackToken` **before** `playbackId`, and calls `play()`. No Media Chrome controls are rendered; the Player draws its own.
- The token is signed at route render (`/c/[course]/[lesson]`, `force-dynamic`). Try again calls `refreshPlaybackToken` (server action: origin check, catalog lookup, rate limit), and the transport rebuilds the element with the new token.
- If Safari drops the gesture across the lazy import, `play()` rejects with `NotAllowedError`. The engine then goes to `paused` and the next tap plays synchronously.
- `pnpm build` resolves `@tower/playback-engine` to the Mux engine; `pnpm build:test` resolves it to FakeEngine (`bundle:check` proves each build contains only its own engine).
