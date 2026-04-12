import { useRef, useState } from "react";
import { uploadReceipt } from "../../lib/api/ourcents";

type UploadStatus = "idle" | "uploading" | "success" | "duplicate" | "error";

interface UploadResult {
  status: string;
  receipt_id?: number;
  info?: Record<string, unknown>;
}

export default function Upload() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [result, setResult] = useState<UploadResult | null>(null);
  const [error, setError] = useState("");

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
    setUploadStatus("idle");
    setResult(null);
    setError("");
    if (f) {
      const reader = new FileReader();
      reader.onload = () => setPreview(reader.result as string);
      reader.readAsDataURL(f);
    } else {
      setPreview(null);
    }
  }

  async function handleUpload() {
    if (!file) return;
    setUploadStatus("uploading");
    setError("");
    try {
      const res = await uploadReceipt(file) as UploadResult;
      setResult(res);
      if (res.status === "pending_confirmation" || res.status === "success") {
        setUploadStatus("success");
      } else if (res.status.startsWith("duplicate")) {
        setUploadStatus("duplicate");
      } else {
        setUploadStatus("error");
        setError(res.status);
      }
    } catch (e: unknown) {
      setUploadStatus("error");
      setError(e instanceof Error ? e.message : "Upload failed");
    }
  }

  return (
    <div style={{ padding: "1.5rem", maxWidth: 600 }}>
      <h2>Upload Receipt</h2>

      <div
        style={{
          border: "2px dashed #cbd5e1",
          borderRadius: 8,
          padding: "2rem",
          textAlign: "center",
          cursor: "pointer",
          marginBottom: "1rem",
          background: "#f8fafc",
        }}
        onClick={() => inputRef.current?.click()}
      >
        {preview ? (
          <img src={preview} alt="Preview" style={{ maxHeight: 200, maxWidth: "100%", borderRadius: 4 }} />
        ) : (
          <p style={{ color: "#94a3b8", margin: 0 }}>Click to select a receipt image (JPG, PNG, WEBP)</p>
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/jpg,image/webp"
        style={{ display: "none" }}
        onChange={handleFileChange}
      />

      {file && (
        <p style={{ fontSize: "0.9rem", color: "#475569" }}>
          {file.name} ({(file.size / 1024).toFixed(1)} KB)
        </p>
      )}

      <button
        onClick={handleUpload}
        disabled={!file || uploadStatus === "uploading"}
        style={{
          padding: "0.6rem 1.4rem",
          background: "#6366f1",
          color: "white",
          border: "none",
          borderRadius: 6,
          cursor: file && uploadStatus !== "uploading" ? "pointer" : "not-allowed",
          opacity: !file || uploadStatus === "uploading" ? 0.6 : 1,
        }}
      >
        {uploadStatus === "uploading" ? "Uploading…" : "Upload Receipt"}
      </button>

      {uploadStatus === "success" && result && (
        <div style={{ marginTop: "1rem", padding: "1rem", background: "#f0fdf4", borderRadius: 6, border: "1px solid #bbf7d0" }}>
          <strong>✓ Receipt processed</strong>
          <p style={{ margin: "0.5rem 0 0" }}>Receipt #{result.receipt_id} is pending confirmation.</p>
          <a href="/ourcents/receipts" style={{ color: "#6366f1" }}>Go to Receipts →</a>
        </div>
      )}

      {uploadStatus === "duplicate" && (
        <div style={{ marginTop: "1rem", padding: "1rem", background: "#fef9c3", borderRadius: 6, border: "1px solid #fde68a" }}>
          <strong>⚠ Duplicate detected</strong>
          <p style={{ margin: "0.5rem 0 0" }}>{String(result?.info?.reason ?? "This receipt appears to have been uploaded before.")}</p>
        </div>
      )}

      {uploadStatus === "error" && (
        <div style={{ marginTop: "1rem", padding: "1rem", background: "#fef2f2", borderRadius: 6, border: "1px solid #fecaca" }}>
          <strong>✗ Upload failed</strong>
          <p style={{ margin: "0.5rem 0 0" }}>{error}</p>
        </div>
      )}
    </div>
  );
}
