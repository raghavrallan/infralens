import { connect } from "node:net";

function target() {
  const url = new URL(process.env.REDIS_URL || "redis://127.0.0.1:6399/0");
  return {
    host: url.hostname || "127.0.0.1",
    port: Number(url.port || 6379),
    password: url.password ? decodeURIComponent(url.password) : "",
  };
}

function encode(args) {
  const chunks = [Buffer.from(`*${args.length}\r\n`)];
  for (const arg of args) {
    const value = Buffer.from(String(arg));
    chunks.push(Buffer.from(`$${value.length}\r\n`));
    chunks.push(value);
    chunks.push(Buffer.from("\r\n"));
  }
  return Buffer.concat(chunks);
}

function parse(buffer) {
  if (!buffer.length) return null;
  const prefix = String.fromCharCode(buffer[0]);
  const end = buffer.indexOf("\r\n");
  if (end < 0) return null;
  const line = buffer.subarray(1, end).toString();
  if (prefix === "+") return { value: line, rest: buffer.subarray(end + 2) };
  if (prefix === "-") return { value: new Error(line), rest: buffer.subarray(end + 2) };
  if (prefix === ":") return { value: Number(line), rest: buffer.subarray(end + 2) };
  if (prefix === "$") {
    const size = Number(line);
    if (size < 0) return { value: null, rest: buffer.subarray(end + 2) };
    const start = end + 2;
    if (buffer.length < start + size + 2) return null;
    return { value: buffer.subarray(start, start + size).toString(), rest: buffer.subarray(start + size + 2) };
  }
  if (prefix === "*") {
    const count = Number(line);
    if (count < 0) return { value: null, rest: buffer.subarray(end + 2) };
    let rest = buffer.subarray(end + 2);
    const items = [];
    for (let index = 0; index < count; index += 1) {
      const next = parse(rest);
      if (!next) return null;
      items.push(next.value);
      rest = next.rest;
    }
    return { value: items, rest };
  }
  return { value: new Error("Unexpected Redis reply."), rest: Buffer.alloc(0) };
}

export function redisCommand(args) {
  const { host, port, password } = target();
  return new Promise((resolve, reject) => {
    const socket = connect({ host, port });
    const timer = setTimeout(() => {
      socket.destroy();
      reject(new Error("Redis did not answer."));
    }, 1500);
    const queue = [];
    if (password) queue.push(["AUTH", password]);
    queue.push(args);
    let buffer = Buffer.alloc(0);
    let got = 0;
    const finish = (err, value) => {
      clearTimeout(timer);
      socket.end();
      if (err) reject(err);
      else resolve(value);
    };
    const read = () => {
      while (got < queue.length) {
        const parsed = parse(buffer);
        if (!parsed) return;
        buffer = parsed.rest;
        got += 1;
        if (parsed.value instanceof Error) {
          finish(parsed.value);
          return;
        }
        if (got === queue.length) finish(null, parsed.value);
      }
    };
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      read();
    });
    socket.on("error", (err) => finish(err));
    socket.on("connect", () => {
      for (const item of queue) socket.write(encode(item));
    });
  });
}
