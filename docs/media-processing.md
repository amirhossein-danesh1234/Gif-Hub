# Media Processing

The Phase 0 pipeline:

1. Validate file size against `MAX_UPLOAD_BYTES`.
2. Sniff the real content signature instead of trusting the extension.
3. Use FFprobe for video/GIF duration and dimension checks.
4. Generate:
   - `original_asset`
   - `normalized_gif_asset`
   - `optimized_mp4_asset`
   - `thumbnail_asset`
5. Store assets under stable keys:
   - `media/{media_id}/original/{sha256}.{ext}`
   - `media/{media_id}/normalized/{sha256}.gif`
   - `media/{media_id}/optimized/{sha256}.mp4`
   - `media/{media_id}/thumbnail/{sha256}.jpg`

All FFmpeg and FFprobe calls use argument lists and never `shell=True`.
