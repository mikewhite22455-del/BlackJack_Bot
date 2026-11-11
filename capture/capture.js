"use strict";
const token = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
const video = document.getElementById("preview");
const statusText = document.getElementById("status");
const shareButton = document.getElementById("share");
const stopButton = document.getElementById("stop");
const canvas = document.createElement("canvas");
let stream = null;
let streamId = null;
let generation = 0;

async function request(path, id, body) {
  const headers = {"X-Capture-Token": token, "X-Stream-Id": id};
  if (body) headers["Content-Type"] = "image/jpeg";
  const response = await fetch(path, {method: "POST", headers, body, cache: "no-store",
    signal: AbortSignal.timeout(4000)});
  if (!response.ok) throw new Error("Desktop capture link rejected the request. Reconnect from the app.");
}

function stopSharing(message = "Sharing stopped.") {
  generation++;
  const id = streamId;
  streamId = null;
  if (stream) for (const track of stream.getTracks()) track.stop();
  stream = null;
  video.srcObject = null;
  shareButton.disabled = !token;
  stopButton.disabled = true;
  statusText.textContent = message;
  if (id) request("/stop", id).catch(() => {});
}

async function sendFrames(expectedGeneration, id) {
  try {
    while (expectedGeneration === generation && stream) {
      if (video.videoWidth && video.videoHeight) {
        const scale = Math.min(1, 2560 / video.videoWidth, 1440 / video.videoHeight);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        const image = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.92));
        if (expectedGeneration !== generation) return;
        if (!image) throw new Error("The selected tab did not produce an image.");
        await request("/frame", id, image);
      }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  } catch (error) {
    if (expectedGeneration === generation) stopSharing(error.message);
  }
}

shareButton.addEventListener("click", async () => {
  shareButton.disabled = true;
  const expectedGeneration = ++generation;
  let selected = null;
  try {
    selected = await navigator.mediaDevices.getDisplayMedia({video: {displaySurface: "browser"}, audio: false,
      selfBrowserSurface: "exclude", surfaceSwitching: "exclude"});
    if (expectedGeneration !== generation) {
      selected.getTracks().forEach(track => track.stop());
      return;
    }
    stream = selected;
    streamId = crypto.randomUUID();
    await request("/start", streamId);
    const id = streamId;
    video.srcObject = stream;
    await video.play();
    stream.getVideoTracks()[0].addEventListener("ended", () => stopSharing());
    stopButton.disabled = false;
    statusText.textContent = "Sharing visible pixels with your desktop app. Check that this is the correct table.";
    sendFrames(expectedGeneration, id);
  } catch (error) {
    if (selected) selected.getTracks().forEach(track => track.stop());
    stopSharing(error.name === "NotAllowedError" ? "Sharing was not granted. Click Share casino tab to try again." : error.message);
  }
});
stopButton.addEventListener("click", () => stopSharing());
window.addEventListener("pagehide", () => stopSharing());
if (!token || !navigator.mediaDevices?.getDisplayMedia) {
  shareButton.disabled = true;
  statusText.textContent = "Open this page using Connect browser capture in the desktop app, with Chrome or Edge.";
}
