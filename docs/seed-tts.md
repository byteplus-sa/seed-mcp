# Seed TTS 3.0

`seed_tts_generate` speaks supplied text or SSML using
`dola-seed-tts-3.0` and an authorized voice. Use `seed_audio_generate` instead
for full-scene speech, music and sound generation.

## Availability

**Hosted HTTP:** returns complete audio directly, with no TOS or output storage.
Supply live `X-Seed-Speech-Api-Key` and independent `X-MCP-Client-Secret` headers.
**Local stdio:** uses `BYTEPLUS_SEED_SPEECH_API_KEY` and local artifact storage.
Both share the Seed Speech gateway. `ark_list_models` with
`{"input":{"kind":"audio"}}` lists TTS; discovery does not verify voice entitlement.

## Direct Audio Delivery

The server collects the provider's JSONL stream, then returns one complete
MCP `AudioContent` block at `content[0]`. Its `data` field is Base64 and its
wire `mimeType` is `audio/mpeg`, `audio/pcm`, or `audio/ogg`.
This is a completed tool response, not real-time audio streaming.

`structuredContent.audio` contains `content_index`, `mime_type`, decoded
`bytes` and `sha256`; `artifact` is null on HTTP. Audio bytes are not
duplicated in structured or text metadata. Save the decoded content block on
the client. PCM is raw audio; use the returned format and sample rate to
interpret it. Native playback and saving UI depend on the MCP client and have
not been verified across every supported client.

Decoded audio is capped at **30 MiB**, which becomes **40 MiB of Base64**
before metadata and protocol overhead. Configure client/proxy response limits
accordingly; the server's 2 MiB inbound request cap is unrelated.
No TOS credentials, bucket, download URL, hosted file, artifact resource or
recovery API is involved. A lost response cannot be retrieved later.
Keep the request ID and never automatically repeat synthesis after a timeout
or disconnect: the provider may have billed the request.

Stdio still persists audio and supports `output_path`/artifact export.
There is no `persist` flag; local output options are rejected on HTTP.

## Choose a Voice

Use an exact compatible Speaker ID from the
[Seed TTS 3.0 voice list](https://docs.byteplus.com/en/docs/byteplusvoice/voicelist-3-0),
or an existing authorized cloned voice ID. There is no automatic voice selection,
cloning, enrollment or voice-list API in this server. Voice/model compatibility
and language-specific controls remain provider-dependent.

Example English preset: `multi_female_skye_v3_uranus_bigtts`.

## Direct Calls

Call `seed_tts_generate`:

```json
{
  "input": {
    "voice_id": "multi_female_skye_v3_uranus_bigtts",
    "text": "Welcome to the demonstration.",
    "language_code": "en",
    "enable_subtitle": true
  }
}
```

Delivery and pronunciation controls:

```json
{
  "input": {
    "voice_id": "multi_female_skye_v3_uranus_bigtts",
    "text": "MCP connects your tools.",
    "voice_settings": {
      "speed": 0.9,
      "volume": 1.0,
      "instructions": ["Speak clearly and warmly."]
    },
    "pronunciation_dictionary": {
      "tone": ["MCP/model context protocol"]
    },
    "output_format": {"format": "mp3", "sample_rate": 24000, "bit_rate": 64000}
  }
}
```

For SSML, replace `text` with `ssml`, for example
`"<speak>Welcome to the demonstration.</speak>"`. Exactly one is required.
Supported tags depend on the selected voice/model.

## Controls and Limits

| Field | Contract |
| --- | --- |
| `voice_id` | Required nonblank ID, at most 256 characters |
| `text` / `ssml` | Exactly one; 1-10,000 characters, nonblank; SSML cap is local |
| `model` | Only `dola-seed-tts-3.0` |
| `language_code` | Defaults to `auto`; use provider codes such as `en` |
| `output_format.format` | `mp3` (default), `pcm`, `ogg_opus` |
| `output_format.sample_rate` | 8000, 16000, 22050, 24000, 32000, 44100 or 48000 Hz; default 24000 for MP3/PCM; Opus requires 48000 |
| `output_format.bit_rate` | 64000 (default) or 160000 bits/s; omit for PCM; 8000 Hz MP3 requires 64000 |
| `voice_settings` | Speed/volume 0.5-2.0, pitch -12 to 12, delivery instructions and cloned-voice similarity boost |
| `pronunciation_dictionary.tone` | `term/replacement` or pinyin rules; local cap 100 rules of at most 1000 characters |
| `enable_subtitle` | Optional word alignment, default false |
| `session_id` | Optional provider conversation continuity ID; reuse sequentially, not as an idempotency key |
| `text_normalization` / `enable_markdown_filter` | Default true / false |
| `silence_duration` | Trailing silence in milliseconds, 0-30000 |
| `output_path` / `overwrite` | Stdio-only local copy under live MCP roots or `OUTPUT_ROOTS`; rejected over HTTP |

TTS collection is bounded to 30 MiB of decoded audio, 8 MiB per JSONL event
and 8 MiB of metadata, plus a total wire bound. The relaxed inline-audio store
policy does not remove these streaming limits. MP3, PCM and Ogg Opus map to
`audio/mpeg`, `audio/pcm` and `audio/ogg` respectively.

## Results and Recovery

The result contains `audio` metadata on HTTP or `artifact` on stdio, resolved `output_format`, `session_id`,
`request_id`, optional `provider_log_id`, and `alignments`. Word
`start_time` / `end_time` values are in seconds. Empty alignment does not mean
the audio failed. Only a successful final event with nonempty audio is delivered.

On HTTP, save the native audio block before discarding the result. There is no
download URL, server-side copy or polling operation. Failure responses are
text-only and do not expose partial audio. Save request IDs for reconciliation;
do not automatically synthesize again.

On stdio, use `seed_media_export_artifact` or `output_path` to avoid putting audio bytes
into model context. Artifact-store writes themselves need no output roots.
Storage failure can return `artifact.fallback_data` within
`ARTIFACT_INLINE_FALLBACK_MAX_BYTES`. If fallback is disabled or too small, a
text-only `persist_speech` error retains the client request ID, storage error code
and confirmed synthesis completion. `retryable=false` forbids automatic
resynthesis; `ambiguous_completion=false` means synthesis is known to have
completed, not that it was free or delivered successfully.
There is no provider URL to recover. Do not automatically synthesize again.

Ordinary client-cleanup and post-synthesis progress-notification failures are
logged without replacing the result, provider error or cancellation.
External cancellation still propagates, including during persistence or progress.

The built-in budget estimate is **USD 20 per million input characters**,
including SSML markup and audio tags, not an account quote. Admission and local
budget reservation precede dispatch. Definitive rejection or connection failure
releases the reservation; successful or uncertain synthesis commits it.
Timeouts, disconnects and malformed/incomplete successful streams may have been
billed. No automatic synthesis retries occur. External cancellation propagates
and closes the stream; it is not provider cancellation.

## Sources and Validation

- [Seed TTS 3.0 HTTP API](https://docs.byteplus.com/en/docs/byteplusvoice/seed-tts-3-0-http-streaming)
- [Seed TTS 3.0 voice list](https://docs.byteplus.com/en/docs/byteplusvoice/voicelist-3-0)
- [Upstream implementation and evidence, PR #135](https://github.com/byteplus-sa/ark-mcp/pull/135)

This port adapts the merged upstream contract to direct calls.
Offline validation uses synthetic streams and sockets disabled, without storage writes on HTTP.
It does not establish current account/voice entitlement or live audio quality.
Live provider validation for this direct-call port remains a separate gate.
