# Bonsai local setup

Architecture Coach can use Ternary Bonsai 2 27B for reviews, repository quizzes, instructor explanations and OpenSpec improvement plans. These operations use saved evidence and never implement code changes automatically.

The PTQ1_0 model downloaded through LM Studio needs the author's [Prism llama.cpp fork](https://github.com/PrismML-Eng/Bonsai-demo). Stock LM Studio and Ollama currently cannot load this format: see the [model's known issues](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf/blob/main/KNOWN_ISSUES.md). Architecture Coach lists downloaded LM Studio language models but keeps discovery separate from execution validation.

## Windows setup

Install Architecture Coach using `install.cmd` first. From its checkout:

```powershell
.\"Install Bonsai Local.cmd"
.\"Start Bonsai Local.cmd"
```

The installer downloads the official Windows x64 Vulkan runtime for `prism-b10754-2459f68`, checks its pinned SHA256 hash, and installs under `%LOCALAPPDATA%\ArchCoach\prism`. Vulkan supports NVIDIA and other compatible GPUs through their installed drivers. It does not download weights, modify LM Studio, add a WebUI, or install tools. Archive licenses are retained with the binaries. Installation fails without publishing partial files if the download or verification fails.

The launcher uses the existing file below your home directory:

```text
.lmstudio/models/prism-ml/Ternary-Bonsai-2-27B-gguf/Ternary-Bonsai-2-27B-PTQ1_0.gguf
```

Use an explicit model path if yours differs:

```powershell
.\"Start Bonsai Local.cmd" --model "D:\Models\Ternary-Bonsai-2-27B-PTQ1_0.gguf"
```

Wait for the model to load. In Architecture Coach Settings, select **Prism · Bonsai local**, keep `ternary-bonsai-2-27b`, and save. Refresh diagnostics to check the loaded model and context. The provider connects only to `127.0.0.1:1235`; other providers keep their own settings. Choosing Prism never invokes Codex or silently substitutes Qwen.

The launcher uses one slot, 32,768 context tokens and all available GPU layers. Architecture Coach requests schema-constrained, non-thinking output with the author's non-thinking sampling parameters to keep review and teaching calls bounded. The Codex reasoning-effort selector applies to Codex only. Increase **Seconds per AI call** and **Seconds per review** in Settings if your hardware needs more time.

Vulkan uses `Vulkan0` by default to avoid splitting work across a discrete GPU and a slower integrated GPU. If your preferred device has another ID, pass `--device Vulkan1` (or the runtime's correct device ID) to the launcher.

The launcher creates a private API key under the same application data directory. Architecture Coach reads it locally; it never appears in browser settings or exported reports. With a custom data directory, use the same `--data-dir` for Architecture Coach and the Bonsai launcher. Unauthenticated model API requests are rejected.

## CPU and shutdown

For a machine without a supported NVIDIA driver:

```powershell
.\"Install Bonsai Local.cmd" --backend cpu
.\"Start Bonsai Local.cmd" --backend cpu
```

CPU inference can be substantially slower. Use Ctrl+C in the Bonsai launcher to stop its server. **Exit app** stops Architecture Coach; independently launched model servers stay running until stopped separately. Cancelling a coach job closes its request and leaves the model service available for later jobs.

For NVIDIA CUDA instead of Vulkan, pass `--backend cuda` to both commands. This installs CUDA 12.4 binaries plus runtime DLLs, requiring a larger download. Backend installations are separate and use the same existing model weights.

A second launcher refuses an occupied port and leaves the existing process alone. If a native load error occurs, inspect the launcher output, verify the GPU driver/memory and model path, then retry explicitly. No automatic model downloads or provider retries take place.

For private verification or a separate installation, both commands accept `--data-dir "D:\Coach Data"`. Keep model files, logs and source-derived acceptance results out of public Git history.
