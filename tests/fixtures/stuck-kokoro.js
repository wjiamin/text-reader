// A voice that never finishes loading, like a phone that ran out of memory
export const env = { set wasmPaths(value) {} };

export class KokoroTTS {
  static from_pretrained() {
    return new Promise(() => {});
  }
}
