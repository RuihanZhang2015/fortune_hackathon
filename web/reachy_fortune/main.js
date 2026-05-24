let pc;
let dc;
const handledToolCalls = new Set();
const pendingToolCalls = new Map();
const SILENT_WAV = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQQAAAAAAA==";

const connectButton = document.querySelector("#connect");
const sendTestButton = document.querySelector("#sendTest");
const disconnectButton = document.querySelector("#disconnect");
const statusEl = document.querySelector("#status");
const logEl = document.querySelector("#log");
const transcriptEl = document.querySelector("#transcript");
const imageEl = document.querySelector("#fortuneImage");
const interpretationEl = document.querySelector("#interpretation");
const remoteAudio = document.querySelector("#remoteAudio");
const speakerTargetEl = document.querySelector("#speakerTarget");
const audioOutputEl = document.querySelector("#audioOutput");
let assistantTranscript = "";
let userTranscript = "";
let initialGreetingSent = false;
let audioOutputs = [];

function log(message, data) {
  const suffix = data ? `\n${JSON.stringify(data, null, 2)}` : "";
  logEl.textContent += `${message}${suffix}\n\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text) {
  statusEl.textContent = text;
}

connectButton.addEventListener("click", connectRealtime);
sendTestButton.addEventListener("click", () => sendUserText("请用中文回复：语音测试成功。"));
disconnectButton.addEventListener("click", disconnectRealtime);
speakerTargetEl.addEventListener("change", applyAudioOutputDevice);
audioOutputEl.addEventListener("change", applyAudioOutputDevice);
refreshAudioOutputDevices();

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
  pc.addTrack(stream.getAudioTracks()[0]);
  await refreshAudioOutputDevices();
  await applyAudioOutputDevice();

  dc = pc.createDataChannel("oai-events");
  dc.addEventListener("open", () => {
    setStatus("Connected. Warming up Reachy...");
    connectButton.disabled = true;
    sendTestButton.disabled = false;
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
  connectButton.disabled = false;
  sendTestButton.disabled = true;
  disconnectButton.disabled = true;
  setStatus("Disconnected");
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
    sendInitialGreeting();
  }
  if (event.type === "response.created") {
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
    if (event.type === "response.output_item.done" && pending.name === "robot_draw") {
      await handleRobotDrawCall(pending);
    }
  }
  if (event.type === "response.function_call_arguments.delta" && event.call_id) {
    const pending = pendingToolCalls.get(event.call_id) || { call_id: event.call_id, name: event.name, arguments: "" };
    pending.name = event.name || pending.name;
    pending.arguments += event.delta || "";
    pendingToolCalls.set(event.call_id, pending);
  }
  if (event.type === "response.function_call_arguments.done") {
    const item = {
      call_id: event.call_id,
      name: event.name || pendingToolCalls.get(event.call_id)?.name,
      arguments: event.arguments || pendingToolCalls.get(event.call_id)?.arguments || "{}",
    };
    if (item.name === "robot_draw") {
      await handleRobotDrawCall(item);
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
    setStatus("Connected. Speak to Reachy.");
    captureTranscriptFromResponse(event.response);
    const calls = event.response?.output?.filter((x) => x.type === "function_call" && x.name === "robot_draw") || [];
    for (const item of calls) {
      await handleRobotDrawCall(item);
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
      instructions: "用中文简单问候用户，并说明你已经准备好听他说话。",
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

async function handleRobotDrawCall(item) {
  if (!item.call_id || handledToolCalls.has(item.call_id)) return;
  handledToolCalls.add(item.call_id);
  pendingToolCalls.delete(item.call_id);
  let args = {};
  try {
    args = JSON.parse(item.arguments || "{}");
  } catch {
    args = {};
  }
  log("Tool call: robot_draw", {
    call_id: item.call_id,
    arguments: args,
  });
  setStatus("Drawing fortune...");

  let result;
  try {
    const response = await fetch("/api/robot_draw", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: args.prompt || "给我分析今天的运势",
        style: args.style || "道教符箓、毛笔、玄妙、抽象",
        reachy_output: true,
      }),
    });
    result = await response.json();
    if (!response.ok || result.ok === false) {
      throw new Error(result.detail || result.error || `robot_draw failed with HTTP ${response.status}`);
    }
  } catch (error) {
    const message = formatError(error);
    setStatus(`robot_draw failed: ${message}`);
    log("Tool error", { message });
    sendFunctionCallOutput(item.call_id, {
      ok: false,
      error: message,
      interpretation: "玄运图暂时没有画成，请温柔地告诉用户稍后再试。",
    });
    requestToolResultResponse("请用中文简短说明绘图暂时失败，请用户稍后再试。");
    return;
  }

  if (result.image_url) {
    imageEl.src = `${result.image_url}?t=${Date.now()}`;
  }
  interpretationEl.textContent = result.interpretation || "";
  setStatus("Fortune drawing ready.");
  log("Tool result", {
    ...compactRobotDrawResult(result),
    tool_call: compactRobotDrawToolCall(result.tool_call),
  });

  sendFunctionCallOutput(item.call_id, compactRobotDrawResult(result));
  requestToolResultResponse("请用中文把 tool result 里的 interpretation 讲给用户听。不要念坐标点，不要说 JSON。");
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
