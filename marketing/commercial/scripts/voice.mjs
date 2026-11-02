import { spawn } from "node:child_process";
import { mkdir, readFile, writeFile, copyFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { KokoroTTS } from "kokoro-js";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const campaignPath = path.join(project, "campaign.json");
const workDir = path.join(project, "work");
const publicDir = path.join(project, "public");
const docsDir = path.join(project, "docs");

const run = (cmd, args) =>
  new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${cmd} ${args.join(" ")} failed (${code})\n${stderr}`));
    });
  });

async function probe(file) {
  const { stdout } = await run("ffprobe", [
    "-v",
    "error",
    "-show_entries",
    "format=duration",
    "-of",
    "csv=p=0",
    file,
  ]);
  const duration = Number(stdout.trim());
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(`No duration for ${file}`);
  }
  return duration;
}

function stamp(seconds) {
  const ms = Math.max(0, Math.round(seconds * 1000));
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  const milli = ms % 1000;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")},${String(milli).padStart(3, "0")}`;
}

function clock(seconds) {
  const rounded = Math.max(0, seconds);
  const m = Math.floor(rounded / 60);
  const s = rounded - m * 60;
  return `${m}:${s.toFixed(2).padStart(5, "0")}`;
}

const campaign = JSON.parse(await readFile(campaignPath, "utf8"));
await mkdir(workDir, { recursive: true });
await mkdir(publicDir, { recursive: true });
await mkdir(docsDir, { recursive: true });

const fps = campaign.fps;
const tail = 0.16;
const sceneGap = 0.36;

console.log(`Loading Kokoro voice ${campaign.voice}`);
const tts = await KokoroTTS.from_pretrained("onnx-community/Kokoro-82M-v1.0-ONNX", {
  dtype: "q8",
});

const pieces = [];
const scenes = [];
let cursor = 0;
let captionIndex = 1;
const srt = [];

for (let sceneIndex = 0; sceneIndex < campaign.scenes.length; sceneIndex += 1) {
  const scene = campaign.scenes[sceneIndex];
  const sceneStart = cursor;
  const lines = [];
  for (let lineIndex = 0; lineIndex < scene.lines.length; lineIndex += 1) {
    const text = scene.lines[lineIndex];
    const wav = path.join(workDir, `${scene.id}-${lineIndex}.wav`);
    process.stdout.write(`Voice ${scene.id} ${lineIndex + 1}/${scene.lines.length}\n`);
    const audio = await tts.generate(text, { voice: campaign.voice });
    await audio.save(wav);
    const spoken = await probe(wav);
    const pad = lineIndex === scene.lines.length - 1 && sceneIndex === campaign.scenes.length - 1 ? 0.7 : tail;
    const extra = lineIndex === scene.lines.length - 1 && sceneIndex < campaign.scenes.length - 1 ? sceneGap : 0;
    const hold = pad + extra;
    const silence = path.join(workDir, `${scene.id}-${lineIndex}-gap.wav`);
    await run("ffmpeg", [
      "-y",
      "-f",
      "lavfi",
      "-i",
      "anullsrc=r=24000:cl=mono",
      "-t",
      hold.toFixed(3),
      silence,
    ]);
    pieces.push(wav, silence);
    const from = Math.round(cursor * fps);
    const frames = Math.max(1, Math.round((spoken + hold) * fps));
    lines.push({ text, from, frames });
    srt.push(`${captionIndex}\n${stamp(cursor)} --> ${stamp(cursor + spoken)}\n${text}\n`);
    captionIndex += 1;
    cursor += spoken + hold;
  }
  const from = Math.round(sceneStart * fps);
  const frames = Math.max(1, Math.round(cursor * fps) - from);
  const { lines: _spoken, ...visual } = scene;
  scenes.push({
    id: scene.id,
    kind: scene.kind,
    from,
    frames,
    lines,
    visual,
  });
}

const normalized = [];
for (let index = 0; index < pieces.length; index += 1) {
  const next = path.join(workDir, `norm-${String(index).padStart(3, "0")}.wav`);
  await run("ffmpeg", ["-y", "-i", pieces[index], "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", next]);
  normalized.push(next);
}
const listPath = path.join(workDir, "concat.txt");
await writeFile(listPath, normalized.map((file) => `file '${file}'`).join("\n"));
const rawVoice = path.join(workDir, "voice-raw.wav");
await run("ffmpeg", ["-y", "-f", "concat", "-safe", "0", "-i", listPath, "-c", "copy", rawVoice]);
const voiceover = path.join(publicDir, "voiceover.wav");
try {
  await run("ffmpeg", [
    "-y",
    "-i",
    rawVoice,
    "-ar",
    "48000",
    "-ac",
    "1",
    "-af",
    "loudnorm=I=-16:TP=-1.5:LRA=11",
    voiceover,
  ]);
} catch (error) {
  console.warn(`Loudnorm skipped: ${error.message}`);
  await copyFile(rawVoice, voiceover);
}

const musicOut = path.join(publicDir, "music.mp3");
try {
  await run("ffmpeg", [
    "-y",
    "-i",
    campaign.music.file,
    "-af",
    "loudnorm=I=-28:TP=-2.5:LRA=11",
    musicOut,
  ]);
} catch (error) {
  console.warn(`Music loudnorm skipped: ${error.message}`);
  await copyFile(campaign.music.file, musicOut);
}

const whoosh = path.join(workDir, "whoosh.wav");
const chime = path.join(workDir, "chime.wav");
await run("ffmpeg", [
  "-y",
  "-f",
  "lavfi",
  "-i",
  "anoisesrc=color=pink:duration=0.26:sample_rate=24000",
  "-ac",
  "1",
  "-af",
  "highpass=f=500,lowpass=f=3200,afade=t=in:st=0:d=0.03,afade=t=out:st=0.05:d=0.21,volume=0.45",
  whoosh,
]);
await run("ffmpeg", [
  "-y",
  "-f",
  "lavfi",
  "-i",
  "sine=frequency=587:duration=0.42:sample_rate=24000",
  "-af",
  "afade=t=in:st=0:d=0.02,afade=t=out:st=0.05:d=0.37,volume=0.28",
  chime,
]);
const sfxInputs = ["-f", "lavfi", "-t", cursor.toFixed(3), "-i", "anullsrc=r=24000:cl=mono"];
const sfxFilters = [];
const mixLabels = ["[0]"];
scenes.forEach((scene, index) => {
  const hit = scene.kind === "intro" || scene.kind === "close" ? chime : whoosh;
  sfxInputs.push("-i", hit);
  const delay = Math.max(0, Math.round((scene.from / fps) * 1000));
  sfxFilters.push(`[${index + 1}]adelay=${delay}:all=1[h${index}]`);
  mixLabels.push(`[h${index}]`);
});
sfxFilters.push(`${mixLabels.join("")}amix=inputs=${mixLabels.length}:duration=first:normalize=0[a]`);
await run("ffmpeg", [
  "-y",
  ...sfxInputs,
  "-filter_complex",
  sfxFilters.join(";"),
  "-map",
  "[a]",
  path.join(publicDir, "sfx.wav"),
]);

const timeline = {
  fps,
  width: campaign.width,
  height: campaign.height,
  hasAudio: true,
  hasSfx: true,
  musicVolume: 0.85,
  scenes,
};
await writeFile(path.join(publicDir, "timeline.json"), JSON.stringify(timeline, null, 2));
await writeFile(campaign.output.srt, srt.join("\n"));

const storyboard = [
  "# Timestamped storyboard",
  "",
  `Measured from the Kokoro voice track at ${fps} fps. Canvas ${campaign.width}×${campaign.height}.`,
  "",
  ...scenes.map((scene) => {
    const start = scene.from / fps;
    const end = (scene.from + scene.frames) / fps;
    const spoken = scene.lines.map((line) => line.text).join(" ");
    return [
      `## ${clock(start)}–${clock(end)} · ${scene.id} · ${scene.kind}`,
      "",
      spoken,
      "",
    ].join("\n");
  }),
  `Total ${clock(cursor)}.`,
  "",
].join("\n");
await writeFile(path.join(docsDir, "storyboard.md"), storyboard);
console.log(`Voice ready. ${clock(cursor)} across ${scenes.length} scenes.`);
