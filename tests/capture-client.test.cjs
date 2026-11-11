const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function harness({deny = false, failFrame = false, token = "test-token"} = {}) {
  const calls = [], timers = [], handlers = {};
  const element = () => ({disabled: false, textContent: "", events: {},
    addEventListener(name, callback) { this.events[name] = callback; }});
  const elements = {share: element(), stop: element(), status: element(), preview: element()};
  const track = {stops: 0, events: {}, stop() { this.stops++; },
    addEventListener(name, callback) { this.events[name] = callback; }};
  const stream = {getTracks: () => [track], getVideoTracks: () => [track]};
  Object.assign(elements.preview, {videoWidth: 1280, videoHeight: 720, play: async () => {}});
  const canvas = {getContext: () => ({drawImage() {}}), toBlob: callback => callback({jpeg: true})};
  const context = {location: {hash: "#" + token, pathname: "/"}, history: {replaceState() {}},
    document: {getElementById: name => elements[name], createElement: () => canvas},
    window: {addEventListener: (name, callback) => { handlers[name] = callback; }},
    navigator: {mediaDevices: {getDisplayMedia: async options => {
      calls.push({capture: options});
      if (deny) throw Object.assign(new Error("Denied"), {name: "NotAllowedError"});
      return stream;
    }}}, crypto: {randomUUID: () => "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"},
    AbortSignal: {timeout: () => ({})},
    fetch: async (url, options) => { calls.push({url, options}); return {ok: !(failFrame && url === "/frame")}; },
    setTimeout: callback => { timers.push(callback); },
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../capture/capture.js"), "utf8"), context);
  return {calls, elements, timers, track, handlers};
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test("sharing requires a click and transmits local frames without audio", async () => {
  const h = harness();
  assert.equal(h.calls.length, 0);
  await h.elements.share.events.click();
  await flush();
  assert.equal(h.calls[0].capture.audio, false);
  assert.deepEqual(h.calls.filter(c => c.url).map(c => c.url), ["/start", "/frame"]);
  const frame = h.calls.find(c => c.url === "/frame");
  assert.equal(frame.options.headers["X-Capture-Token"], "test-token");
  assert.equal(frame.options.headers["Content-Type"], "image/jpeg");
  h.elements.stop.events.click();
  assert.equal(h.track.stops, 1);
  assert.equal(h.elements.stop.disabled, true);
  assert.equal(h.elements.share.disabled, false);
  const before = h.calls.filter(c => c.url === "/frame").length;
  h.timers.forEach(callback => callback());
  await flush();
  assert.equal(h.calls.filter(c => c.url === "/frame").length, before);
});

test("browser denial leaves no frame connection", async () => {
  const h = harness({deny: true});
  await h.elements.share.events.click();
  assert.equal(h.calls.filter(c => c.url).length, 0);
  assert.match(h.elements.status.textContent, /not granted/);
  assert.equal(h.elements.share.disabled, false);
});

test("lost desktop connection stops the selected capture track", async () => {
  const h = harness({failFrame: true});
  await h.elements.share.events.click();
  await flush();
  assert.equal(h.track.stops, 1);
  assert.match(h.elements.status.textContent, /rejected/);
});

test("closing the capture page stops capture", async () => {
  const h = harness();
  await h.elements.share.events.click();
  await flush();
  h.handlers.pagehide();
  assert.equal(h.track.stops, 1);
  assert.equal(h.elements.preview.srcObject, null);
});

test("an unpaired page cannot initiate sharing", () => {
  const h = harness({token: ""});
  assert.equal(h.elements.share.disabled, true);
  assert.equal(h.calls.length, 0);
});
