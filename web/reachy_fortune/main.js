let pc;
let dc;
const handledToolCalls = new Set();
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
const audioOutputEl = document.querySelector("#audioOutput");
let assistantTranscript = "";
let userTranscript = "";
let initialGreetingSent = false;

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
  if (handledToolCalls.has(item.call_id)) return;
  handledToolCalls.add(item.call_id);
  let args = {};
  try {
    args = JSON.parse(item.arguments || "{}");
  } catch {
    args = {};
  }
  log("Tool call: robot_draw", args);
  const result = await fetch("/api/robot_draw", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt: args.prompt || "给我分析今天的运势",
      style: args.style || "道教符箓、毛笔、玄妙、抽象",
      reachy_output: true,
    }),
  }).then((r) => r.json());

  imageEl.src = `${result.image_url}?t=${Date.now()}`;
  interpretationEl.textContent = result.interpretation;
  log("Tool result", {
    point_count: result.point_count,
    image_url: result.image_url,
    reachy_output: result.reachy_output,
    reachy_mode: result.reachy_mode,
  });

  dc.send(JSON.stringify({
    type: "conversation.item.create",
    item: {
      type: "function_call_output",
      call_id: item.call_id,
      output: JSON.stringify(result),
    },
  }));
  dc.send(JSON.stringify({
    type: "response.create",
    response: {
      output_modalities: ["audio"],
      instructions: "请用中文把 tool result 里的 interpretation 讲给用户听。不要念坐标点，不要说 JSON。",
    },
  }));
}

async function refreshAudioOutputDevices() {
  if (!navigator.mediaDevices?.enumerateDevices) return;
  const selected = audioOutputEl.value;
  const devices = await navigator.mediaDevices.enumerateDevices();
  const outputs = devices.filter((device) => device.kind === "audiooutput");
  audioOutputEl.textContent = "";
  audioOutputEl.append(new Option("System default", ""));
  for (const device of outputs) {
    const label = device.label || `Speaker ${audioOutputEl.length}`;
    audioOutputEl.append(new Option(label, device.deviceId));
  }
  if ([...audioOutputEl.options].some((option) => option.value === selected)) {
    audioOutputEl.value = selected;
  }
  audioOutputEl.disabled = typeof remoteAudio.setSinkId !== "function";
}

async function applyAudioOutputDevice() {
  if (typeof remoteAudio.setSinkId !== "function") {
    return;
  }
  try {
    await remoteAudio.setSinkId(audioOutputEl.value);
    log("Audio output selected", { device: audioOutputEl.selectedOptions[0]?.text || "System default" });
  } catch (error) {
    log("Audio output selection failed", { message: error.message });
  }
}
