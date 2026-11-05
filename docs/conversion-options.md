# Conversion options API

Authenticated session endpoints retain the existing CSRF requirements. Worker
endpoints retain device-token ownership and job leases.

## Library review workflow

The conversion landing page has two cards per row: full conversion, video only,
audio only, and an inactive subtitle-translation placeholder. Existing download,
RSS, PC and Dolby archive settings are in the expandable settings section.

- `GET /api/conversion/workflow` returns library files with available tracker
  title/cover metadata, cached stream information, per-mode skip flags and jobs.
- `GET /api/conversion/workflow/<file-id>/media` probes the current library file
  and returns `media` plus a size/mtime `fingerprint` required at enqueue time.
- `POST /api/conversion/workflow/skip` takes `{id, mode, skip: boolean}`.
- `POST /api/conversion/workflow/queue` takes `{items: [...]}`. Each item has
  `id`, `fingerprint`, `options`, and `policy`. A batch contains 1–100 films and
  is validated before committing; at most 500 unfinished films may be queued.
- `POST /api/conversion/workflow/cancel` takes a queued job `id`.
- `POST /api/conversion/workflow/retry` takes a failed job `id`.

`options` contains `mode: full | video | audio`, `bitrate: 20 | 30 | 40`,
`dolby_vision_mode: separate | preserve`, `audio_codec: copy | ac3 | eac3`,
`audio: [stream indices]`, and `subtitle: [stream indices]`. These are **global
ffprobe stream indices**, unlike the PC ordinal API below. Video-only always
copies every audio/subtitle track. Audio-only copies video and every subtitle
track, retaining the original Dolby Vision profile. Full mode permits both
track selections and video settings. Video processing accepts DV 7/8.1 and
produces 8.1, optionally archived separately for HDR10 playback.

Selected original audio tracks are copied. Where their codec differs from the
chosen compatibility codec, an additional AC3/E-AC3 track is encoded at 48 kHz,
192 kbps for mono/stereo or 640 kbps for multichannel audio. The original codec,
object metadata and samples remain available in the copied original track.
Compatibility encoding supports known layouts through 5.1; larger/unknown
layouts require original audio. No channel downmix is requested. Verification
checks the original tracks and the expected additional codec, channel count,
layout, sample rate, language and flags. AC3's decoded surround-layout labels
are normalized only in the reference for the new compatible track.

The guide shows per-film live size estimates and a final review before starting
one durable server queue. Estimates include retained audio and added compatible
tracks; unavailable duration/audio bitrate yields no numeric estimate. An
original still occupying Seeder is additional storage, not immediate savings.

`policy` uses the manual download fields `ratio_action`, `ratio_limit`, and
`seed_minutes`: keep, stop_keep, delete, automatic, delete_ratio or delete_time.
Existing real upload and active seeding time carry over. Films in the same
torrent must have the same policy. Pending jobs block automatic cleanup until
all selected films have been published. After worker verification, qBittorrent
is stopped and receives `setLocation` to move the original to Seeder. The
existing verified active seed clock excludes the stop/move. Publication and
original-location verification precede applying the selected cleanup policy.
Converted library files remain outside original cleanup.

Preparation runs through a maintenance RPC, outside VPN supervision. Large
cross-volume work copies release the storage lock; a separate preparation lock
and durable identity allow restart recovery. Jobs never accept browser paths.
The original must have an unambiguous completed qBittorrent owner. The new
review queue runs on the server; existing PC jobs retain the API below.

## Existing PC and direct library APIs

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
