# Conversion options API

Authenticated session endpoints retain the existing CSRF requirements. Worker
endpoints retain device-token ownership and job leases.

`POST /api/conversion/devices/<id>/select` accepts the existing `media_folder`,
`name`, `bitrate` (integer 20/30/40) plus `conversion_mode: "video" | "audio"`.
`POST /api/conversion/library` accepts `id`, `bitrate` and the same mode.
Both accept `selected_audio_tracks: [0, 2]` for audio mode. Indices are zero-based
audio ordinals, not global ffprobe stream indices; omission/null keeps every
audio track. At least one unique integer index is required when a list is sent.
Lists are sorted into source order and checked against the actual source probe.
Video mode rejects track filtering. The selection is persisted and included in
reports, worker commands and retry identity checks.
Omission defaults to `video` for compatibility. Invalid modes are rejected.
Mode is persisted in queue entries, library jobs, shared commands and reports;
retries and existing output reuse must match it. Audio mode retains bitrate as
queue metadata for compatibility; it does not apply it to copied video.

`video` uses the existing NVEncC HEVC target bitrate and copies all audio.
`audio` uses FFmpeg to copy video, subtitles, attachments, chapters and metadata,
and converts every selected ordinary audio stream to lossless FLAC. Unselected
audio tracks are explicitly excluded; the default selection retains all tracks. No channel-count or
layout override is passed to FFmpeg. Verification checks each stream's channel
count, layout, sample rate, language/title, disposition and track count. Video
codec/profile, geometry, timing, HDR and source Dolby Vision configuration must
remain intact. Audio-only bypasses the video conversion's DV separation policy.

TrueHD, E-AC-3, DTS, AC-4 and MLP streams are conservatively copied, even when
ffprobe does not identify Atmos/DTS:X. Their codecs can carry object metadata;
a channel count cannot prove that metadata is absent. Already-FLAC streams are
also copied. Unknown layouts or unsupported channel counts fail closed. This
is format conversion of channel audio, not an Atmos transcoder or a guaranteed
file-size reduction. Originals remain under the existing safe publication rules.

`GET /api/conversion/devices/<id>/bitrates` adds these fields to each matched file:

- `duration_seconds`: positive number or null.
- `audio_tracks`: ordered list of `{codec, output_codec, action, channels,
  channel_layout, language, title, description, profile, index, stream_index, reason}`. Description comes
  from MKV title, description, comment or handler_name tags, in that priority.
  `index` is the stable selection ordinal; `stream_index` is diagnostic metadata.
  Unsupported tracks stay visible with `action: "unsupported"` and `error`,
  and may be deselected while retaining supported tracks. Selected unsupported
  tracks are rejected by the actual conversion probe. Supported actions are `copy`
  and `convert`.
- `audio_error`: no-audio error or null; per-track errors are attached to their track.
- `estimates`: keys `20`, `30`, `40`, `audio`. Each contains
  `{estimated_bytes, saved_bytes, approximate: true, reason}`.

Video estimates use `duration * (target_Mbps * 1e6 + total_bps - video_bps) / 8`
with 1% mux allowance. All non-video tracks contribute, not just the first audio
language. These are VBR targets, not hard size limits. Missing duration or a
separate video bitrate yields null bytes and an explanation. Savings may be
negative. FLAC size depends on sample entropy, so audio mode returns null rather
than inventing a saving. Runtime disk reservation uses a conservative decoded
PCM allowance. The bounded header cache is upgraded to scan version 4.

PC workspace `conversion_version: 3` advertises audio-mode support. Versions 1 and 2
continue to support video jobs; audio requests are refused until the PC is
updated. A downgraded PC cannot start an already queued audio job. Server fallback
uses the same command and validation policy. Transfer-based workers below
version 3 also skip audio jobs rather than claiming and ignoring their settings.

Reference: [FFmpeg stream mapping and stream copy](https://ffmpeg.org/ffmpeg.html),
[Dolby Atmos home-theater bitstream and object metadata](https://professional.dolby.com/siteassets/tv/home/dolby-atmos/dolby-atmos-for-home-theater.pdf).

Validation includes real FFmpeg conversion of Danish 7.1 / 5.1(side) and English
stereo streams to FLAC, with all tracks, Danish only and English only, including descriptions and SHA-256 equality of the copied video payload.
GPU encoding and Windows packaging require their respective runtime environments.
