let pc;
let dc;
const handledToolCalls = new Set();
const pendingToolCalls = new Map();
const SILENT_WAV = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQQAAAAAAA==";

const connectButton = document.querySelector("#connect");
const sendTestButton = document.querySelector("#sendTest");
const manualToolButton = document.querySelector("#manualTool");
const muteMicButton = document.querySelector("#mutemic");
const disconnectButton = document.querySelector("#disconnect");
const statusEl = document.querySelector("#status");
const logEl = document.querySelector("#log");
const transcriptEl = document.querySelector("#transcript");
const canvasEl = document.querySelector("#fortuneCanvas");
const interpretationEl = document.querySelector("#interpretation");
const manualToolOutputEl = document.querySelector("#manualToolOutput");
const remoteAudio = document.querySelector("#remoteAudio");
const speakerTargetEl = document.querySelector("#speakerTarget");
const audioOutputEl = document.querySelector("#audioOutput");
let assistantTranscript = "";
let userTranscript = "";
let initialGreetingSent = false;
let audioOutputs = [];
let isResponseActive = false;
let pendingUserResponse = false;
let micMuted = false;
let micTrack = null;

function log(message, data) {
  const suffix = data ? `\n${JSON.stringify(data, null, 2)}` : "";
  logEl.textContent += `${message}${suffix}\n\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text) {
  statusEl.textContent = text;
}

const DRAWING_SCALE = 0.65;

function normalizeStrokes(strokes) {
  if (!strokes?.length) return null;
  // Model sometimes sends [[x,y],...] instead of [[[x,y],...]]; wrap if needed.
  if (typeof strokes[0][0] === "number") return [strokes];
  return strokes;
}

function drawStrokesOnCanvas(strokes) {
  const size = canvasEl.width;
  const margin = 90;
  const scale = Math.min((size - 2 * margin) / 0.46, (size - 2 * margin) / 0.34) * DRAWING_SCALE;
  const cx = size / 2;
  const cy = size / 2;
  const ctx = canvasEl.getContext("2d");
  ctx.fillStyle = "#f4ebd6";
  ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = "#221c14";
  ctx.lineWidth = 5;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  for (const stroke of strokes) {
    if (stroke.length < 2) continue;
    ctx.beginPath();
    ctx.moveTo(cx + stroke[0][0] * scale, cy - stroke[0][1] * scale);
    for (let i = 1; i < stroke.length; i++) {
      ctx.lineTo(cx + stroke[i][0] * scale, cy - stroke[i][1] * scale);
    }
    ctx.stroke();
  }
  ctx.strokeStyle = "#bea47a";
  ctx.lineWidth = 2;
  ctx.strokeRect(margin - 20, margin - 20, size - 2 * (margin - 20), size - 2 * (margin - 20));
}

async function drawRenderedImageOnCanvas(imageUrl) {
  if (!imageUrl) return;
  const image = new Image();
  image.decoding = "async";
  await new Promise((resolve, reject) => {
    image.onload = () => resolve();
    image.onerror = () => reject(new Error("Failed to load rendered image"));
    image.src = imageUrl;
  });
  const ctx = canvasEl.getContext("2d");
  ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
  ctx.drawImage(image, 0, 0, canvasEl.width, canvasEl.height);
}

connectButton.addEventListener("click", connectRealtime);
sendTestButton.addEventListener("click", () => sendUserText("Please reply in English: voice test successful."));
manualToolButton.addEventListener("click", triggerManualToolCall);
muteMicButton.addEventListener("click", toggleMicMute);
disconnectButton.addEventListener("click", disconnectRealtime);
speakerTargetEl.addEventListener("change", applyAudioOutputDevice);
audioOutputEl.addEventListener("change", applyAudioOutputDevice);
refreshAudioOutputDevices();

async function triggerManualToolCall() {
  manualToolButton.disabled = true;
  setStatus("Manually triggering robot_draw...");
  const manualArgs = {
    prompt: "给我分析今天的运势",
    style: "极简道教符箓、最多三个元素、直线折线、少于100个轨迹点、留白",
    title: "manual_fortune",
  };
  renderManualToolOutput("Manual request", manualArgs);
  try {
    await handleRobotDrawCall({
      call_id: `manual_${Date.now()}`,
      arguments: JSON.stringify(manualArgs),
    }, "manual");
  } finally {
    manualToolButton.disabled = false;
  }
}

function renderManualToolOutput(title, payload) {
  if (!manualToolOutputEl) return;
  manualToolOutputEl.textContent = `${title}\n${JSON.stringify(payload, null, 2)}`;
}

async function connectRealtime() {
  try {
    await startRealtimeConnection();
  } catch (error) {
    setStatus(`Connection failed: ${formatError(error)}`);
    log("Connection failed", { message: formatError(error) });
    disconnectRealtime();
  }
}

async function startRealtimeConnection() {
  setStatus("Requesting microphone...");
  await unlockAudioPlayback();
  initialGreetingSent = false;
  isResponseActive = false;
  pendingUserResponse = false;
  pc = new RTCPeerConnection();
  pc.addEventListener("connectionstatechange", () => {
    log("Peer connection state", {
      connection_state: pc.connectionState,
      ice_state: pc.iceConnectionState,
      signaling_state: pc.signalingState,
    });
  });
  pc.ontrack = (event) => {
    remoteAudio.srcObject = event.streams[0];
    remoteAudio.muted = false;
    remoteAudio.volume = 1;
    log("Remote audio track received", {
      streams: event.streams.length,
      track_kind: event.track.kind,
      track_state: event.track.readyState,
    });
    ensureRemoteAudioPlaying("ontrack");
  };

  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  micTrack = stream.getAudioTracks()[0];
  pc.addTrack(micTrack);
  await refreshAudioOutputDevices();
  await applyAudioOutputDevice();

  dc = pc.createDataChannel("oai-events");
  dc.addEventListener("open", () => {
    setStatus("Connected. Warming up Reachy...");
    connectButton.disabled = true;
    sendTestButton.disabled = false;
    muteMicButton.disabled = false;
    disconnectButton.disabled = false;
    ensureRemoteAudioPlaying("connected");
  });
  dc.addEventListener("message", handleRealtimeEvent);

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  log("Local SDP summary", summarizeSdp(offer.sdp));
  const response = await fetch("/session", {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: offer.sdp,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  const answerSdp = await response.text();
  log("Remote SDP summary", summarizeSdp(answerSdp));
  await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });
}

async function unlockAudioPlayback() {
  try {
    remoteAudio.srcObject = null;
    remoteAudio.src = SILENT_WAV;
    remoteAudio.muted = true;
    await remoteAudio.play();
    remoteAudio.pause();
    remoteAudio.removeAttribute("src");
    remoteAudio.load();
    remoteAudio.muted = false;
    remoteAudio.volume = 1;
    log("Audio playback unlocked");
  } catch (error) {
    log("Audio unlock skipped", { message: error.message });
    remoteAudio.muted = false;
  }
}

function formatError(error) {
  const message = error?.message || String(error);
  try {
    const parsed = JSON.parse(message);
    return parsed.detail || message;
  } catch {
    return message;
  }
}

function summarizeSdp(sdp) {
  return {
    has_audio: sdp.includes("m=audio"),
    has_data_channel: sdp.includes("m=application"),
    audio_lines: sdp.split("\n").filter((line) => line.startsWith("m=audio") || line.startsWith("a=send") || line.startsWith("a=recv")),
  };
}

async function ensureRemoteAudioPlaying(source) {
  if (!remoteAudio.srcObject) {
    log("Remote audio is not ready yet", { source });
    return;
  }
  try {
    remoteAudio.muted = false;
    remoteAudio.volume = 1;
    await remoteAudio.play();
    log("Remote audio playback started", {
      source,
      paused: remoteAudio.paused,
      muted: remoteAudio.muted,
      volume: remoteAudio.volume,
    });
  } catch (error) {
    setStatus("Audio playback is blocked by the browser.");
    log("Remote audio playback blocked", { source, message: error.message });
  }
}

function disconnectRealtime() {
  if (dc) dc.close();
  if (pc) {
    pc.getSenders().forEach((sender) => sender.track && sender.track.stop());
    pc.close();
  }
  pc = null;
  dc = null;
  micTrack = null;
  isResponseActive = false;
  pendingUserResponse = false;
  if (micMuted) {
    micMuted = false;
    muteMicButton.textContent = "Mute mic";
    muteMicButton.classList.remove("muted");
  }
  connectButton.disabled = false;
  sendTestButton.disabled = true;
  muteMicButton.disabled = true;
  disconnectButton.disabled = true;
  setStatus("Disconnected");
}

function toggleMicMute() {
  if (!micTrack) return;
  micMuted = !micMuted;
  micTrack.enabled = !micMuted;
  muteMicButton.textContent = micMuted ? "Unmute mic" : "Mute mic";
  muteMicButton.classList.toggle("muted", micMuted);
  log(micMuted ? "Microphone muted — output only mode" : "Microphone unmuted");
}

function sendUserText(text) {
  if (!dc || dc.readyState !== "open") {
    log("Not connected yet.");
    return;
  }
  dc.send(JSON.stringify({
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [{ type: "input_text", text }],
    },
  }));
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      output_modalities: ["audio"],
    },
  }));
}

async function handleRealtimeEvent(raw) {
  const event = JSON.parse(raw.data);
  if (event.type === "error") {
    setStatus(`Realtime error: ${event.error?.message || "unknown error"}`);
    log("Realtime error", event);
  }
  if (event.type === "session.created" || event.type === "session.updated") {
    setStatus("Connected. Speak to Reachy.");
    log(event.type, event.session ? {
      model: event.session.model,
      output_modalities: event.session.output_modalities,
      voice: event.session.audio?.output?.voice,
    } : undefined);
    if (event.type === "session.created") {
      assistantTranscript = "";
      userTranscript = "";
      renderTranscript();
      dc.send(JSON.stringify({ type: "input_audio_buffer.clear" }));
    }
    sendInitialGreeting();
  }
  if (event.type === "input_audio_buffer.committed") {
    if (micMuted) {
      log("VAD committed — mic muted, ignoring");
    } else if (isResponseActive) {
      log("VAD committed — response active, queuing for after current response");
      pendingUserResponse = true;
    } else {
      log("VAD committed — sending response.create");
      dc.send(JSON.stringify({ type: "response.create", response: { output_modalities: ["audio"] } }));
    }
  }
  if (event.type === "response.created") {
    isResponseActive = true;
    setStatus("Reachy is responding...");
  }
  if (event.type === "response.output_audio_transcript.delta" || event.type === "response.audio_transcript.delta") {
    assistantTranscript += event.delta || "";
    renderTranscript();
  }
  if ((event.type === "response.output_audio_transcript.done" || event.type === "response.audio_transcript.done") && event.transcript) {
    assistantTranscript = event.transcript;
    renderTranscript();
    setStatus("Reachy replied.");
    log(`Reachy transcript: ${event.transcript}`);
    fetch("/api/reachy/express/mystical", { method: "POST" }).catch(() => {});
  }
  if (event.type === "response.output_text.delta" || event.type === "response.text.delta") {
    assistantTranscript += event.delta || "";
    renderTranscript();
  }
  if ((event.type === "response.output_text.done" || event.type === "response.text.done") && event.text) {
    assistantTranscript = event.text;
    renderTranscript();
    setStatus("Reachy replied.");
    log(`Reachy text: ${event.text}`);
  }
  if ((event.type === "response.output_item.added" || event.type === "response.output_item.done") && event.item?.type === "function_call") {
    const pending = pendingToolCalls.get(event.item.call_id) || { call_id: event.item.call_id, arguments: "" };
    pending.name = event.item.name || pending.name;
    pending.arguments = event.item.arguments || pending.arguments;
    pendingToolCalls.set(event.item.call_id, pending);
  }
  if (event.type === "response.function_call_arguments.delta" && event.call_id) {
    const pending = pendingToolCalls.get(event.call_id) || { call_id: event.call_id, name: event.name, arguments: "" };
    pending.name = event.name || pending.name;
    pending.arguments += event.delta || "";
    pendingToolCalls.set(event.call_id, pending);
  }
  if (event.type === "response.function_call_arguments.done") {
    const pending = pendingToolCalls.get(event.call_id);
    if (pending) {
      pending.arguments = event.arguments || pending.arguments;
      pendingToolCalls.set(event.call_id, pending);
    }
  }
  if (event.type === "conversation.item.input_audio_transcription.delta") {
    userTranscript += event.delta || "";
    renderTranscript();
  }
  if (event.type === "conversation.item.input_audio_transcription.completed") {
    userTranscript = event.transcript || userTranscript;
    renderTranscript();
    log(`You transcript: ${userTranscript}`);
  }
  if (event.type === "response.done") {
    isResponseActive = false;
    setStatus("Connected. Speak to Reachy.");
    captureTranscriptFromResponse(event.response);
    const calls = event.response?.output?.filter((x) => x.type === "function_call" && x.name === "robot_draw") || [];
    log(`response.done — output items: ${event.response?.output?.length ?? 0}, robot_draw calls: ${calls.length}`);
    for (const item of calls) {
      await handleRobotDrawCall(item);
    }
    if (calls.length === 0 && pendingUserResponse) {
      pendingUserResponse = false;
      log("Sending queued response.create for pending user speech");
      dc.send(JSON.stringify({ type: "response.create", response: { output_modalities: ["audio"] } }));
    }
  }
}

function sendInitialGreeting() {
  if (initialGreetingSent || !dc || dc.readyState !== "open") {
    return;
  }
  initialGreetingSent = true;
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      output_modalities: ["audio"],
      instructions: "Say a brief, warm hello in English. Do NOT call robot_draw. Just introduce yourself and wait for the user to speak.",
    },
  }));
}

function captureTranscriptFromResponse(response) {
  const text = response?.output
    ?.flatMap((item) => item.content || [])
    ?.map((content) => content.transcript || content.text || "")
    ?.filter(Boolean)
    ?.join("\n");
  if (text) {
    assistantTranscript = text;
    renderTranscript();
    log(`Reachy transcript fallback: ${text}`);
  }
}

function renderTranscript() {
  transcriptEl.textContent = [
    userTranscript ? `You: ${userTranscript}` : "",
    assistantTranscript ? `Reachy: ${assistantTranscript}` : "",
  ].filter(Boolean).join("\n\n");
}

async function handleRobotDrawCall(item, source = "auto") {
  if (!item.call_id || handledToolCalls.has(item.call_id)) return;
  handledToolCalls.add(item.call_id);
  pendingToolCalls.delete(item.call_id);
  let args = {};
  try {
    args = JSON.parse(item.arguments || "{}");
  } catch {
    args = {};
  }
  log("Tool call: robot_draw", { call_id: item.call_id, source, title: args.title, reading: args.reading });
  setStatus("Drawing fortune...");

  // Render strokes on canvas immediately — no network roundtrip needed.
  const strokes = normalizeStrokes(args.strokes);
  if (strokes) {
    drawStrokesOnCanvas(strokes);
  }

  // Immediately close the tool call and trigger voice response — don't wait for the backend.
  // OpenAI already generated interpretation in the tool call args.
  sendFunctionCallOutput(item.call_id, {
    ok: true,
    title: args.title || "fortune",
    interpretation: args.interpretation || "",
  });
  requestToolResultResponse(
    "The robot is drawing. Continue speaking in English for about one minute — poetic and mysterious, no pauses, no questions. " +
    "First read the interpretation aloud, then expand on the deeper meaning of today's fortune, the symbolism of the figure, " +
    "specific guidance for the user's day, and close with a warm blessing. Never read out coordinates or JSON."
  );

  // Backend fetch runs in parallel: renders image and publishes to ngrok.
  try {
    const response = await fetch("/api/robot_draw", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: args.prompt || "给我分析今天的运势",
        style: args.style || "道教符箓、毛笔、玄妙、抽象",
        reachy_output: true,
        strokes: normalizeStrokes(args.strokes),
        title: args.title || null,
        reading: args.reading || null,
        interpretation: args.interpretation || null,
      }),
    });
    const result = await response.json();
    if (!response.ok || result.ok === false) {
      throw new Error(result.detail || result.error || `robot_draw failed with HTTP ${response.status}`);
    }
    interpretationEl.textContent = result.interpretation || args.interpretation || "";
    if (result.image_url) {
      try {
        await drawRenderedImageOnCanvas(`${result.image_url}${result.image_url.includes("?") ? "&" : "?"}t=${Date.now()}`);
      } catch (imageError) {
        log("Render image load failed", { message: formatError(imageError), image_url: result.image_url });
      }
    }
    if (source === "manual") {
      renderManualToolOutput("Manual result", {
        request: {
          prompt: args.prompt || "给我分析今天的运势",
          style: args.style || "道教符箓、毛笔、玄妙、抽象",
          title: args.title || null,
          reading: args.reading || null,
          interpretation: args.interpretation || null,
          strokes_count: Array.isArray(args.strokes) ? args.strokes.length : 0,
        },
        response: compactRobotDrawResult(result),
      });
    }
    setStatus("Fortune drawing ready.");
    log("Backend result", {
      ...compactRobotDrawResult(result),
      tool_call: compactRobotDrawToolCall(result.tool_call),
    });
  } catch (error) {
    const message = formatError(error);
    setStatus(`robot_draw backend failed: ${message}`);
    if (source === "manual") {
      renderManualToolOutput("Manual error", {
        message,
        request: {
          prompt: args.prompt || "给我分析今天的运势",
          style: args.style || "道教符箓、毛笔、玄妙、抽象",
          title: args.title || null,
        },
      });
    }
    log("Backend error", { message });
  }
}

function sendFunctionCallOutput(callId, output) {
  if (!dc || dc.readyState !== "open") {
    log("Cannot send tool output: data channel is closed.", { call_id: callId });
    return;
  }
  dc.send(JSON.stringify({
    type: "conversation.item.create",
    item: {
      type: "function_call_output",
      call_id: callId,
      output: JSON.stringify(output),
    },
  }));
}

function requestToolResultResponse(instructions) {
  if (!dc || dc.readyState !== "open") {
    return;
  }
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      output_modalities: ["audio"],
      instructions,
    },
  }));
}

function compactRobotDrawResult(result) {
  return {
    ok: Boolean(result.ok),
    title: result.title,
    interpretation: result.interpretation,
    symbols: result.symbols,
    image_url: result.image_url,
    toolpath_url: result.toolpath_url,
    point_count: result.point_count,
    drawing_seed: result.drawing_seed,
    reachy_output: result.reachy_output,
    reachy_mode: result.reachy_mode,
    arm_publish: result.arm_publish,
  };
}

function compactRobotDrawToolCall(toolCall) {
  if (!toolCall) {
    return undefined;
  }
  const points = toolCall.xy_points || [];
  return {
    type: toolCall.type,
    coordinate_frame: toolCall.coordinate_frame,
    point_count: points.length,
    first_points: points.slice(0, 5),
    last_points: points.slice(-5),
  };
}

async function refreshAudioOutputDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected = audioOutputEl.value;
  const devices = await navigator.mediaDevices.enumerateDevices();
  audioOutputs = devices.filter((device) => device.kind === "audiooutput");
  audioOutputEl.textContent = "";
  audioOutputEl.append(new Option("System default", ""));
  for (const device of audioOutputs) {
    const label = device.label || `Speaker ${audioOutputEl.length}`;
    audioOutputEl.append(new Option(label, device.deviceId));
  }
  const reachyOutput = getReachyAudioOutput();
  if (speakerTargetEl.value === "reachy" && reachyOutput) {
    audioOutputEl.value = reachyOutput.deviceId;
  } else if ([...audioOutputEl.options].some((option) => option.value === selected)) {
    audioOutputEl.value = selected;
  }
  audioOutputEl.disabled = typeof remoteAudio.setSinkId !== "function";
}

async function applyAudioOutputDevice() {
  if (typeof remoteAudio.setSinkId !== "function") {
    return;
  }
  const targetDeviceId = getSelectedAudioOutputDeviceId();
  if (speakerTargetEl.value === "reachy" && !targetDeviceId) {
    setStatus("Reachy Mini speaker not found. Use macOS audio output or pair it as an audio device.");
    log("Reachy Mini speaker not found", {
      available_outputs: audioOutputs.map((device) => device.label || "(unlabeled output)"),
    });
    return;
  }
  try {
    await remoteAudio.setSinkId(targetDeviceId);
    log("Audio output selected", {
      target: speakerTargetEl.value,
      device: getAudioOutputLabel(targetDeviceId),
    });
  } catch (error) {
    log("Audio output selection failed", { message: error.message });
  }
}

function getSelectedAudioOutputDeviceId() {
  if (speakerTargetEl.value !== "reachy") {
    return audioOutputEl.value;
  }
  const reachyOutput = getReachyAudioOutput();
  return reachyOutput?.deviceId || "";
}

function getReachyAudioOutput() {
  return audioOutputs.find((device) => /reachy|mini/i.test(device.label || ""));
}

function getAudioOutputLabel(deviceId) {
  if (!deviceId) {
    return "System default";
  }
  const output = audioOutputs.find((device) => device.deviceId === deviceId);
  return output?.label || "Selected speaker";
}
