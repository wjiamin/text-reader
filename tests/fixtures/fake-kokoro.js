// Stands in for kokoro-js in tests: the same shape, with silence for audio
export const env = { set wasmPaths(value) {} };

export class KokoroTTS {
  static async from_pretrained(model, { progress_callback } = {}) {
    progress_callback?.({ status: "progress", file: "model.onnx", loaded: 50, total: 100 });
    progress_callback?.({ status: "progress", file: "model.onnx", loaded: 100, total: 100 });
    return new KokoroTTS();
  }

  async generate(text) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    return { audio: new Float32Array(text.split(/\s+/).length * 1200), sampling_rate: 24000 };
  }
}
