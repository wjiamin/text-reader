// A voice that fails to load with an error
export const env = { set wasmPaths(value) {} };

export class KokoroTTS {
  static async from_pretrained() {
    throw new Error("Out of memory");
  }
}
