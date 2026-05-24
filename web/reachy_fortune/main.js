let pc;
let dc;
const handledToolCalls = new Set();

const connectButton = document.querySelector("#connect");
const disconnectButton = document.querySelector("#disconnect");
const fortuneButton = document.querySelector("#fortune");
const playAudioButton = document.querySelector("#playAudio");
const statusEl = document.querySelector("#status");
const logEl = document.querySelector("#log");
const transcriptEl = document.querySelector("#transcript");
const imageEl = document.querySelector("#fortuneImage");
const interpretationEl = document.querySelector("#interpretation");
const remoteAudio = document.querySelector("#remoteAudio");
const reachyOutputEl = document.querySelector("#reachyOutput");
const audioOutputEl = document.querySelector("#audioOutput");
let assistantTranscript = "";
let userTranscript = "";

function log(message, data) {
  const suffix = data ? `\n${JSON.stringify(data, null, 2)}` : "";
  logEl.textContent += `${message}${suffix}\n\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(text) {
  statusEl.textContent = text;
}

connectButton.addEventListener("click", connectRealtime);
disconnectButton.addEventListener("click", disconnectRealtime);
playAudioButton.addEventListener("click", () => ensureRemoteAudioPlaying("manual"));
fortuneButton.addEventListener("click", () => {
  sendUserText("你能给我分析今天的运势，并画一张道教大师用毛笔写出来的运势图吗？");
});
audioOutputEl.addEventListener("change", applyAudioOutputDevice);
refreshReachyStatus();
refreshAudioOutputDevices();

async function connectRealtime() {
  setStatus("Requesting microphone...");
  pc = new RTCPeerConnection();
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
    setStatus("Connected. Speak to Reachy.");
    connectButton.disabled = true;
    disconnectButton.disabled = false;
    dc.send(JSON.stringify({
      type: "response.create",
      response: {
        instructions: "用中文简单问候用户，并说明你已经准备好听他说话。",
      },
    }));
    ensureRemoteAudioPlaying("connected");
  });
  dc.addEventListener("message", handleRealtimeEvent);

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const response = await fetch("/session", {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: offer.sdp,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  await pc.setRemoteDescription({ type: "answer", sdp: await response.text() });
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
    setStatus("Audio is blocked. Click Play audio.");
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
  dc.send(JSON.stringify({ type: "response.create" }));
}

async function handleRealtimeEvent(raw) {
  const event = JSON.parse(raw.data);
  if (event.type === "error") {
    log("Realtime error", event);
  }
  if (event.type === "response.output_audio_transcript.delta" || event.type === "response.audio_transcript.delta") {
    assistantTranscript += event.delta || "";
    renderTranscript();
  }
  if ((event.type === "response.output_audio_transcript.done" || event.type === "response.audio_transcript.done") && event.transcript) {
    assistantTranscript = event.transcript;
    renderTranscript();
    log(`Reachy transcript: ${event.transcript}`);
    if (reachyOutputEl.checked) {
      fetch("/api/reachy/express/mystical", { method: "POST" }).catch(() => {});
    }
  }
  if (event.type === "response.output_text.delta" || event.type === "response.text.delta") {
    assistantTranscript += event.delta || "";
    renderTranscript();
  }
  if ((event.type === "response.output_text.done" || event.type === "response.text.done") && event.text) {
    assistantTranscript = event.text;
    renderTranscript();
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
    captureTranscriptFromResponse(event.response);
    const calls = event.response?.output?.filter((x) => x.type === "function_call" && x.name === "robot_draw") || [];
    for (const item of calls) {
      await handleRobotDrawCall(item);
    }
  }
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
      reachy_output: reachyOutputEl.checked,
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
      instructions: "请用中文把 tool result 里的 interpretation 讲给用户听。不要念坐标点，不要说 JSON。",
    },
  }));
}

async function refreshReachyStatus() {
  try {
    const status = await fetch("/api/reachy/status").then((r) => r.json());
    log("Reachy status", status);
  } catch {
    log("Reachy status unavailable.");
  }
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
