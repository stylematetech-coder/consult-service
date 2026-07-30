import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ResponseSummary } from "../api/client";
import { isValidPhone, PHONE_FORMAT_HINT, sanitizePhoneInput } from "../lib/phone";

export function Lookup() {
  const [phone, setPhone] = useState("");
  const [results, setResults] = useState<ResponseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSearch(e: FormEvent) {
    e.preventDefault();
    if (!phone.trim()) return;
    if (!isValidPhone(phone)) {
      setError(`手機號碼格式不正確，請輸入${PHONE_FORMAT_HINT}`);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.listResponses(phone);
      setResults(res.responses);
    } catch {
      setError("查詢失敗，請稍後再試一次");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <div className="card">
        <div className="title">設計師查詢</div>
        <div className="subtitle">輸入顧客手機號碼查詢歷史問卷</div>
        <form onSubmit={handleSearch}>
          <input
            className="field-input"
            type="tel"
            inputMode="numeric"
            maxLength={10}
            placeholder="手機號碼（0912345678）"
            value={phone}
            onChange={(e) => setPhone(sanitizePhoneInput(e.target.value))}
          />
          <div className="actions">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? "查詢中…" : "查詢"}
            </button>
          </div>
        </form>

        {error && <div className="error-text">{error}</div>}

        {results && results.length === 0 && <div className="subtitle">查無資料</div>}

        {results && results.length > 0 && (
          <div>
            {results.map((r) => (
              <Link key={r.id} to={`/lookup/${r.id}`} className="list-row">
                <div className="row-name">
                  {r.name}
                  <span className={`status-badge status-${r.status}`}>
                    {r.status === "submitted" ? "已送出" : "填寫中"}
                  </span>
                </div>
                <div className="row-meta">{r.created_at}</div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
