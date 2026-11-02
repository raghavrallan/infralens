# Quality-assurance report

File: `marketing/infralens-agentic.mp4`

| Check | Result |
| --- | --- |
| Landscape 1920×1080 | pass |
| 16:9 | pass |
| Not vertical | pass |
| H.264 | pass |
| AAC audio | pass |
| MP4 container | pass |
| Duration 60–120s | pass |

```json
{
  "width": 1920,
  "height": 1080,
  "videoCodec": "h264",
  "audioCodec": "aac",
  "fps": "30/1",
  "duration": 108.245333,
  "size": 13464764,
  "format": "mov,mp4,m4a,3gp,3g2,mj2"
}
```

Visual review is from the composition code: every scene uses the 1920×1080 frame, the background is full-bleed, and captions sit inside the lower safe area. No live tenant screenshot was available, so the console is a reconstruction and is labeled on screen.
