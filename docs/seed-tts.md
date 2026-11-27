# Seed TTS 3.0

`seed_tts_generate` speaks supplied text or SSML using
`dola-seed-tts-3.0` and an authorized voice. Use `seed_audio_generate` instead
for full-scene speech, music and sound generation.

## Availability

**Local stdio only**, with `BYTEPLUS_SEED_SPEECH_API_KEY`. The existing
`BYTEPLUS_SEED_AUDIO_BASE_URL` setting serves both Seed Audio and Seed TTS.
No new credential, background job, voice administration or provider task is added.
`ark_list_models` with `{"input":{"kind":"audio"}}` lists TTS when configured.
Discovery does not verify voice access or provider entitlement.

Call the tool directly with the usual `input` wrapper. The server collects the
provider's JSONL stream into one complete audio artifact, not live MCP audio.
It always persists: there is no `persist` switch and no provider download URL.
HTTP remains URL-only and does not register or advertise this tool.

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
| `output_path` / `overwrite` | Optional local copy under live MCP roots or `OUTPUT_ROOTS`; overwrite defaults false |

TTS collection is bounded to 10 MiB of decoded audio, 8 MiB per JSONL event
and 8 MiB of metadata, plus a total wire bound. The relaxed inline-audio store
policy does not remove these streaming limits. MP3, PCM and Ogg Opus map to
`audio/mpeg`, `audio/pcm` and `audio/ogg` respectively.

## Results and Recovery

The result contains `artifact`, resolved `output_format`, `session_id`,
`request_id`, optional `provider_log_id`, and `alignments`. Word
`start_time` / `end_time` values are in seconds. Empty alignment does not mean
the audio failed. Only a successful final event with nonempty audio is persisted.

Use `seed_media_export_artifact` or `output_path` to avoid putting audio bytes
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

This port adapts the merged upstream contract to direct stdio execution.
Local validation uses synthetic streams with network sockets disabled.
It does not establish current account/voice entitlement or live audio quality.
Live provider validation for this direct-call port remains a separate gate.
