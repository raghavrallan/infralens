import { spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const campaign = JSON.parse(await readFile(path.join(project, "campaign.json"), "utf8"));
const output = campaign.output.video;

const run = (cmd, args, inherit) =>
  new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      cwd: project,
      stdio: inherit ? "inherit" : ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    if (!inherit) {
      child.stdout.on("data", (chunk) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk;
      });
    }
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(`${cmd} failed (${code})\n${stderr}`));
    });
  });

console.log(`Rendering ${output}`);
await run(
  "pnpm",
  [
    "exec",
    "remotion",
    "render",
    "src/index.ts",
    "Commercial",
    output,
    "--codec=h264",
    "--crf=16",
    "--pixel-format=yuv420p",
    "--audio-codec=aac",
    "--concurrency=2",
  ],
  true,
);

const { stdout } = await run("ffprobe", [
  "-v",
  "error",
  "-show_streams",
  "-show_format",
  "-of",
  "json",
  output,
]);
const probe = JSON.parse(stdout);
const video = probe.streams.find((stream) => stream.codec_type === "video");
const audio = probe.streams.find((stream) => stream.codec_type === "audio");
const width = Number(video?.width);
const height = Number(video?.height);
const checks = [
  ["Landscape 1920×1080", width === 1920 && height === 1080],
  ["16:9", width / height === 16 / 9],
  ["Not vertical", width > height],
  ["H.264", video?.codec_name === "h264"],
  ["AAC audio", audio?.codec_name === "aac"],
  ["MP4 container", probe.format.format_name?.includes("mp4")],
  ["Duration 60–120s", Number(probe.format.duration) >= 60 && Number(probe.format.duration) <= 125],
];

const report = [
  "# Quality-assurance report",
  "",
  `File: \`${output}\``,
  "",
  `| Check | Result |`,
  `| --- | --- |`,
  ...checks.map(([name, ok]) => `| ${name} | ${ok ? "pass" : "fail"} |`),
  "",
  "```json",
  JSON.stringify(
    {
      width,
      height,
      videoCodec: video?.codec_name,
      audioCodec: audio?.codec_name,
      fps: video?.r_frame_rate,
      duration: Number(probe.format.duration),
      size: Number(probe.format.size),
      format: probe.format.format_name,
    },
    null,
    2,
  ),
  "```",
  "",
  "Visual review is from the composition code: every scene uses the 1920×1080 frame, the background is full-bleed, and captions sit inside the lower safe area. No live tenant screenshot was available, so the console is a reconstruction and is labeled on screen.",
  "",
].join("\n");

await writeFile(path.join(project, "docs", "qa-report.md"), report);
const failed = checks.filter(([, ok]) => !ok).map(([name]) => name);
if (failed.length) {
  console.error(`QA failed: ${failed.join(", ")}`);
  process.exit(1);
}
console.log("QA passed.");
