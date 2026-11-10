// Unpacks data the way the real voice's pronunciation dictionary does: by
// looping over a stream with "for await", which Safari can't do on its own
export const env = { set wasmPaths(value) {} };

export class KokoroTTS {
  static async from_pretrained() {
    const parts = [];
    for await (const part of new Blob(["dictionary"]).stream()) parts.push(part);
    if (!parts.length) throw new Error("nothing unpacked");
    return new KokoroTTS();
  }

  async generate(text) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    return { audio: new Float32Array(text.split(/\s+/).length * 1200), sampling_rate: 24000 };
  }
}
