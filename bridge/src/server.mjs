import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import QRCode from "qrcode";
import { randomUUID } from "crypto";
import { rm } from "fs/promises";
import { existsSync } from "fs";
import { join } from "path";
import { execFile } from "child_process";
import { promisify } from "util";

const execFileAsync = promisify(execFile);
import whatsappWeb from "whatsapp-web.js";

const { Client, LocalAuth, MessageMedia } = whatsappWeb;

dotenv.config({ override: false }); // don't clobber env vars already set by start.sh

const app = express();
const port = Number(process.env.PORT || 3001);
const bridgeApiKey = process.env.BRIDGE_API_KEY || "change-me-bridge-key";
const backendBaseUrl = process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000/api";
const headless = (process.env.PUPPETEER_HEADLESS || "true").toLowerCase() === "true";

app.use(cors());
app.use(express.json({ limit: "2mb" }));

/** @type {Map<string, {id:string, client:any, status:string, qrCodeDataUrl:string|null, connectedPhone:string|null, connectedName:string|null, lastError:string|null}>} */
const sessions = new Map();

function log(level, message, extra) {
  const timestamp = new Date().toISOString();
  if (extra === undefined) {
    console[level](`[${timestamp}] ${message}`);
  } else {
    console[level](`[${timestamp}] ${message}`, extra);
  }
}

function requireBridgeKey(req, res, next) {
  if (req.headers["x-bridge-key"] !== bridgeApiKey) {
    return res.status(401).json({ detail: "Invalid bridge key" });
  }
  next();
}

function normalizePhone(value) {
  return String(value || "").replace(/\D/g, "");
}

async function postToBackend(path, payload, tag) {
  try {
    const resp = await fetch(`${backendBaseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Bridge-Key": bridgeApiKey },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      throw new Error(`${resp.status} ${await resp.text()}`);
    }
  } catch (err) {
    log("error", tag, { error: String(err) });
  }
}

function sessionToJson(s) {
  return {
    id: s.id,
    status: s.status,
    qr_code_data_url: s.qrCodeDataUrl,
    connected_phone: s.connectedPhone,
    connected_name: s.connectedName,
    last_error: s.lastError,
  };
}

async function downloadMediaDataUrl(message) {
  if (!message.hasMedia) return null;
  try {
    const media = await message.downloadMedia();
    if (!media) return null;
    const mt = media.mimetype || "";
    if (!mt.startsWith("image/") && !mt.startsWith("audio/")) return null;
    return `data:${media.mimetype};base64,${media.data}`;
  } catch (err) {
    log("warn", "Media download failed", { error: String(err) });
    return null;
  }
}

function wireClientEvents(session) {
  const { id: sessionId, client } = session;

  client.on("qr", async (qr) => {
    session.status = "qr_ready";
    session.qrCodeDataUrl = await QRCode.toDataURL(qr);
    session.lastError = null;
    log("info", "QR ready", { sessionId });
  });

  client.on("authenticated", () => {
    session.status = "authenticated";
    session.lastError = null;
    log("info", "Session authenticated", { sessionId });
  });

  client.on("ready", () => {
    const info = client.info;
    session.status = "connected";
    session.qrCodeDataUrl = null;
    session.connectedPhone = info?.wid?.user || null;
    session.connectedName = info?.pushname || null;
    session.lastError = null;
    log("info", "Session connected", { sessionId, phone: session.connectedPhone, name: session.connectedName });
  });

  client.on("disconnected", (reason) => {
    session.status = "disconnected";
    session.qrCodeDataUrl = null;
    session.connectedPhone = null;
    session.connectedName = null;
    session.lastError = String(reason);
    log("error", "Session disconnected", { sessionId, reason: String(reason) });
  });

  client.on("message_ack", async (message, ack) => {
    if (!message.fromMe) return;
    // WhatsApp ACK levels: 1=server/sent, 2=device/delivered, 3=read, 4=played
    const statusMap = { 1: "sent", 2: "delivered", 3: "read", 4: "read" };
    const deliveryStatus = statusMap[ack];
    if (!deliveryStatus) return;
    await postToBackend("/internal/bridge/ack", {
      session_id: sessionId,
      provider_message_id: message.id._serialized,
      delivery_status: deliveryStatus,
    }, "ack-forward-failed");
  });

  client.on("message", async (message) => {
    if (message.fromMe) return;
    const contact = await message.getContact();
    const mediaDataUrl = await downloadMediaDataUrl(message);
    await postToBackend("/internal/bridge/messages", {
      session_id: sessionId,
      provider_message_id: message.id._serialized,
      sender_phone: normalizePhone(contact.number || message.from || ""),
      sender_name: contact.pushname || contact.name || null,
      message_type: message.type === "chat" ? "text" : message.type,
      body: message.body || null,
      media_url: mediaDataUrl,
      transcript: null,
    }, "inbound-forward-failed");
    log("info", "Inbound message forwarded", { sessionId, from: normalizePhone(contact.number || message.from || ""), hasMedia: !!mediaDataUrl });
  });

  // message_create (Alfred's sent messages) is intentionally NOT synced to the gateway.
  // The gateway already records every outbound message it sends via send_text_via_bridge,
  // and nudge-originated messages go through /api/internal/push (also tracked by gateway).
  // Syncing message_create caused duplicate / wrong-contact entries because WhatsApp
  // uses opaque LID chat IDs (e.g. 101615268835354@lid) that don't match real phone numbers.
}

// Per-session in-flight initialize() promises and "being deleted" markers.
const _initPromises = new Map(); // sessionId -> Promise
const _deletingSet  = new Set(); // sessionIds currently undergoing destructive delete

async function _killChromiumForProfile(authDir) {
  try {
    await execFileAsync("pkill", ["-9", "-f", authDir], { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 800));
  } catch (_) {
    // pkill exits non-zero when no processes matched — safe to ignore.
  }
}

async function _hasChromiumProcs(authDir) {
  try {
    const { stdout } = await execFileAsync("pgrep", ["-f", authDir], { timeout: 3000 });
    return stdout.trim().length > 0;
  } catch (_) {
    return false; // pgrep exits non-zero when nothing found
  }
}

// Kill Chrome, wipe the auth dir, and verify both conditions hold.
// Retries up to 5 times in case Chrome recreates the profile after each kill.
async function _forceWipeAuthProfile(authDir, sessionId) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await _killChromiumForProfile(authDir);
    await rm(authDir, { recursive: true, force: true }).catch(() => {});
    await new Promise((r) => setTimeout(r, 600));
    const dirGone   = !existsSync(authDir);
    const chromeLive = await _hasChromiumProcs(authDir);
    if (dirGone && !chromeLive) return; // fully clean
    log("warn", "Auth wipe incomplete, retrying", { sessionId, attempt, dirGone, chromeLive });
  }
  const dirStillExists = existsSync(authDir);
  const chromeLive     = await _hasChromiumProcs(authDir);
  if (dirStillExists || chromeLive) {
    throw new Error(`Forget Device failed after retries: dir=${dirStillExists} chrome=${chromeLive}`);
  }
}

function createSession(sessionId) {
  if (sessions.has(sessionId)) {
    return sessions.get(sessionId);
  }

  const client = new Client({
    authStrategy: new LocalAuth({ clientId: sessionId }),
    puppeteer: { headless, args: ["--no-sandbox", "--disable-setuid-sandbox"] },
  });

  const session = {
    id: sessionId,
    client,
    status: "starting",
    qrCodeDataUrl: null,
    connectedPhone: null,
    connectedName: null,
    lastError: null,
  };

  sessions.set(sessionId, session);
  wireClientEvents(session);

  const authDir = join(process.cwd(), ".wwebjs_auth", `session-${sessionId}`);
  const initPromise = client.initialize()
    .catch((err) => {
      if (_deletingSet.has(sessionId)) {
        // This session is being deleted — a late init completion could recreate the profile.
        // Kill Chrome and wipe any profile fragments it may have written.
        log("warn", "Late init error on deleting session — cleaning up", { sessionId });
        _killChromiumForProfile(authDir)
          .then(() => rm(authDir, { recursive: true, force: true }))
          .catch(() => {});
      } else {
        session.status = "error";
        session.lastError = String(err);
        log("error", "Session init failed — Bridge kept alive", { sessionId, error: String(err) });
      }
    })
    .finally(() => { _initPromises.delete(sessionId); });

  _initPromises.set(sessionId, initPromise);
  log("info", "Session created and initializing", { sessionId });
  return session;
}

async function destroySession(sessionId, { wipeAuth = false } = {}) {
  const session = sessions.get(sessionId);
  if (!session) return false;

  const authDir = join(process.cwd(), ".wwebjs_auth", `session-${sessionId}`);

  if (wipeAuth) {
    // Mark as deleting BEFORE killing Chrome so any late init handlers see the flag.
    _deletingSet.add(sessionId);
    // Kill Chrome first — this causes the in-flight initialize() to reject quickly
    // rather than waiting for the full 8 s timeout.
    await _killChromiumForProfile(authDir);
  }

  // Await the in-flight initialize() (now likely already rejected by the kill above).
  const initPromise = _initPromises.get(sessionId);
  if (initPromise) {
    await Promise.race([initPromise, new Promise((r) => setTimeout(r, 5000))]);
  }

  try { await session.client.destroy(); } catch (_) { /* ignore */ }
  sessions.delete(sessionId);
  _initPromises.delete(sessionId);

  if (wipeAuth) {
    await _forceWipeAuthProfile(authDir, sessionId);
    _deletingSet.delete(sessionId);
    log("info", "Session destroyed + auth wiped", { sessionId });
  } else {
    log("info", "Session destroyed (auth preserved)", { sessionId });
  }
  return true;
}

// Routes

app.get("/health", (_req, res) => res.json({ status: "ok" }));

app.get("/sessions", requireBridgeKey, (_req, res) => {
  res.json([...sessions.values()].map(sessionToJson));
});

app.post("/sessions", requireBridgeKey, (req, res) => {
  const sessionId = String(req.body.session_id || randomUUID());
  if (sessions.has(sessionId)) {
    return res.status(200).json(sessionToJson(sessions.get(sessionId)));
  }
  const session = createSession(sessionId);
  res.status(201).json(sessionToJson(session));
});

app.get("/sessions/:id", requireBridgeKey, (req, res) => {
  const session = sessions.get(req.params.id);
  if (!session) return res.status(404).json({ detail: "Session not found" });
  res.json(sessionToJson(session));
});

app.post("/sessions/:id/restart", requireBridgeKey, async (req, res) => {
  const session = sessions.get(req.params.id);
  if (!session) return res.status(404).json({ detail: "Session not found" });
  // Reinitialize in-memory client without touching the auth profile.
  // Existing WhatsApp linked-device session is preserved and will auto-reconnect.
  await destroySession(req.params.id, { wipeAuth: false });
  const newSession = createSession(req.params.id);
  res.json(sessionToJson(newSession));
});

app.delete("/sessions/:id", requireBridgeKey, async (req, res) => {
  try {
    const ok = await destroySession(req.params.id, { wipeAuth: true });
    if (!ok) return res.status(404).json({ detail: "Session not found" });
    res.status(204).send();
  } catch (err) {
    // Auth directory could not be removed (e.g. Chromium still held file handles).
    log("error", "Forget Device failed", { sessionId: req.params.id, error: String(err) });
    res.status(500).json({ detail: String(err) });
  }
});

app.post("/sessions/:id/messages/text", requireBridgeKey, async (req, res) => {
  const session = sessions.get(req.params.id);
  if (!session) return res.status(404).json({ detail: "Session not found" });
  if (session.status !== "connected") {
    return res.status(409).json({ detail: "Session is not connected" });
  }

  const recipientPhone = normalizePhone(req.body.recipient_phone || "");
  const body = String(req.body.body || "").trim();
  if (!recipientPhone || !body) {
    return res.status(400).json({ detail: "recipient_phone and body are required" });
  }

  const numberId = await session.client.getNumberId(recipientPhone).catch(() => null);
  const chatId = numberId?._serialized || `${recipientPhone}@c.us`;
  log("info", "Sending message", { sessionId: req.params.id, recipientPhone });

  try {
    const sent = await session.client.sendMessage(chatId, body);
    log("info", "Message sent", { sessionId: req.params.id, providerMessageId: sent.id._serialized });
    return res.json({ provider_message_id: sent.id._serialized });
  } catch (err) {
    session.lastError = String(err);
    log("error", "Send failed", { sessionId: req.params.id, error: String(err) });
    return res.status(502).json({ detail: String(err) });
  }
});

app.post("/sessions/:id/messages/media", requireBridgeKey, async (req, res) => {
  const session = sessions.get(req.params.id);
  if (!session) return res.status(404).json({ detail: "Session not found" });
  if (session.status !== "connected") {
    return res.status(409).json({ detail: "Session is not connected" });
  }

  const recipientPhone = normalizePhone(req.body.recipient_phone || "");
  const data = String(req.body.data || "").trim();
  const mimetype = String(req.body.mimetype || "image/jpeg");
  const caption = req.body.caption || "";

  if (!recipientPhone || !data) {
    return res.status(400).json({ detail: "recipient_phone and data are required" });
  }

  const numberId = await session.client.getNumberId(recipientPhone).catch(() => null);
  const chatId = numberId?._serialized || `${recipientPhone}@c.us`;
  const media = new MessageMedia(mimetype, data);

  try {
    const sent = await session.client.sendMessage(chatId, media, caption ? { caption } : undefined);
    log("info", "Image sent", { sessionId: req.params.id, recipientPhone });
    return res.json({ provider_message_id: sent.id._serialized });
  } catch (err) {
    session.lastError = String(err);
    log("error", "Image send failed", { sessionId: req.params.id, error: String(err) });
    return res.status(502).json({ detail: String(err) });
  }
});

app.listen(port, "0.0.0.0", () => {
  log("info", `Alfred bridge listening on http://0.0.0.0:${port}`);
});

