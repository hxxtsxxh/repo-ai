// Output sinks. Commands never write to process.stdout directly.

export interface Io {
  out(line: string): void;
  err(line: string): void;
}

export interface MemoryIo extends Io {
  stdout: string[];
  stderr: string[];
}

export function memoryIo(): MemoryIo {
  const stdout: string[] = [];
  const stderr: string[] = [];
  return {
    stdout,
    stderr,
    out: (line) => stdout.push(line),
    err: (line) => stderr.push(line),
  };
}

export const processIo: Io = {
  out: (line) => process.stdout.write(line + "\n"),
  err: (line) => process.stderr.write(line + "\n"),
};
