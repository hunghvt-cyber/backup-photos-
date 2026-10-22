# Correct original media identity — 22 October 2026

## Verified diagnosis

Read-only audit run https://github.com/hunghvt-cyber/google-photos-koofr/actions/runs/39704185679
inspected the three small MP4 candidates from Daily 39693250956. Koofr bytes matched
manifest sizes/hashes, but ffprobe identified every payload as webp_pipe with no
duration. Google metadata sizes were independently readable:

| Candidate | Stored bytes | Google source bytes |
| --- | ---: | ---: |
| 1 | 1582 | 1835388 |
| 2 | 1234 | 6957115 |
| 3 | 1292 | 21063594 |

These are image previews saved with video filenames, not videos to relabel as
images. The prior first-googleusercontent-request capture can select the viewer's
preview rather than Google's actual Download. Uploaded means only that the wrong
bytes reached Koofr; previous count 52 is not 52 verified original media.

## Fix

- Daily saves the exact Playwright Download returned by the official Download
  action. It no longer intercepts or replays a generic googleusercontent request.
- Validate actual payload before upload. JPEG/PNG/GIF/WebP signatures classify
  images; an image payload cannot satisfy video metadata or a video filename.
- Video confirmation requires ffprobe, a real video stream, a non-image demuxer,
  and positive duration. ffprobe alone reporting a video stream for WebP is not
  enough. Missing tools/invalid video fail closed. Daily/Backfill install ffmpeg.
- Successful validation records the actual photo/video type in the manifest,
  rather than trusting that a /photo/ URL means the payload is a photo.
- Source-size verification in the paginated WebBackup downloader remains active.

## Previously misrecorded small videos

On the next regular serialized worker startup, inspect at most 20 uploaded video
filenames of at most 4096 bytes. Read remote content and require recorded byte-size
and SHA-256 equality before altering any row. Only a proven image payload behind a
video filename becomes error/pending retry. Provider errors/hash mismatch do not
change it. Preserve its old path/hash/upload time and every old Koofr object.

The existing worker then retries originals using the corrected downloader. Filename collision checks choose an unused media-ID/hash destination when old
bytes differ, and fail closed on unknown read failures rather than overwrite.
No deletion, rename, manifest reset, collector change or independent state writer.
The audit branch remains read-only; it does not instantiate a writer Engine.

The current running Backfill retains its checked-out source; merging does not patch
that process. Recheck/retry occurs at the next scheduled worker startup. Do not claim
three originals repaired until new manifest/Koofr/source readback proves it.

## Validation

52 offline tests pass, including real ffmpeg MP4 generation and ffprobe inspection,
WebP-as-MP4 rejection, exact browser Download selection, no upload/false success
for previews, actual manifest type correction, verified requeue, unchanged original
paths/hashes, refusal of unverified bytes and unaffected genuine image records.
Compileall and diff checks pass. These tests do not prove live original recovery.
