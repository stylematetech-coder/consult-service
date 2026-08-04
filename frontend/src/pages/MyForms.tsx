import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Gender, type ResponseSummary } from "../api/client";
import { isValidPhone, PHONE_FORMAT_HINT, sanitizePhoneInput } from "../lib/phone";

type Phase = "intro" | "list";

const GENDER_OPTIONS: { value: Gender; label: string }[] = [
  { value: "male", label: "男生" },
  { value: "female", label: "女生" },
];

// 客人從 LINE 開場卡「預約」按鈕點進來，網址帶 ?uid=<LINE userId>——這是
// 唯一能分辨「這些表單是不是同一位客人的」依據（見 backend/app/routers/
// responses.py 的 GET /responses/mine）。沒有這個參數就沒有身分可以查詢，
// 顯示引導訊息即可，不試圖用其他方式（例如電話）代替，那正是先前改掉的
// 安全漏洞（客人講的電話任何人都講得出來）。line_uid 只在背後當識別依據，
// 不取代姓名電話這一步——客人一律要先打完姓名電話，才看得到自己的表單列表
// （2026-08-04 調整：原本是先看列表、按 + 才問姓名電話，順序反了）。
export function MyForms() {
  const navigate = useNavigate();
  const lineUid = new URLSearchParams(window.location.search).get("uid");

  const [phase, setPhase] = useState<Phase>("intro");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [gender, setGender] = useState<Gender | null>(null);
  const [introError, setIntroError] = useState<string | null>(null);

  const [responses, setResponses] = useState<ResponseSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  if (!lineUid) {
    return (
      <div className="page">
        <div className="card">
          <div className="title">找不到您的身分</div>
          <div className="subtitle">
            請透過 LINE 對話裡「預約」按鈕開啟的連結進入，才能查看或建立您的表單。
          </div>
        </div>
      </div>
    );
  }

  async function handleIntroSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || !phone.trim() || !gender) {
      setIntroError("請填寫姓名、手機號碼，並選擇性別");
      return;
    }
    if (!isValidPhone(phone)) {
      setIntroError(`手機號碼格式不正確，請輸入${PHONE_FORMAT_HINT}`);
      return;
    }
    setIntroError(null);
    try {
      const res = await api.listMine(lineUid!);
      setResponses(res.responses);
      setPhase("list");
    } catch {
      setListError("查詢失敗，請稍後再試一次");
      setPhase("list");
    }
  }

  async function handleCreateNew() {
    setCreateError(null);
    setCreating(true);
    try {
      const res = await api.createResponse(name.trim(), phone, gender!, lineUid);
      const prefilledParam = res.response.prefilled ? "&prefilled=1" : "";
      navigate(`/edit/${res.response.id}?uid=${encodeURIComponent(lineUid!)}${prefilledParam}`);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "建立表單失敗，請稍後再試一次");
      setCreating(false);
    }
  }

  if (phase === "intro") {
    return (
      <div className="page">
        <div className="card">
          <div className="title">髮型預約表單</div>
          <div className="subtitle">請先留下您的姓名、手機號碼與性別</div>
          <form onSubmit={handleIntroSubmit}>
            {introError && <div className="error-text">{introError}</div>}
            <input
              className="field-input"
              placeholder="姓名"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="field-input"
              type="tel"
              inputMode="numeric"
              maxLength={10}
              placeholder="手機號碼（0912345678）"
              value={phone}
              onChange={(e) => setPhone(sanitizePhoneInput(e.target.value))}
            />
            <div className="options-row" style={{ marginBottom: 20 }}>
              {GENDER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className={gender === opt.value ? "option-btn selected" : "option-btn"}
                  onClick={() => setGender(opt.value)}
                >
                  <span>{opt.label}</span>
                  {gender === opt.value && <span>✓</span>}
                </button>
              ))}
            </div>
            <div className="actions">
              <button type="submit" className="btn-primary">
                繼續
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="card">
        <div className="title">我的表單</div>
        <div className="subtitle">填寫中的表單可以繼續填，已送出的可以查看內容</div>

        {listError && <div className="error-text">{listError}</div>}

        {responses === null && !listError && <div className="subtitle">載入中…</div>}

        {responses && responses.length === 0 && (
          <div className="subtitle">您還沒有任何表單，點下方按鈕開始填寫第一份吧</div>
        )}

        {responses && responses.length > 0 && (
          <div>
            {responses.map((r) =>
              r.status === "in_progress" ? (
                <Link
                  key={r.id}
                  to={`/edit/${r.id}?uid=${encodeURIComponent(lineUid)}`}
                  className="list-row"
                >
                  <div className="row-name">
                    {r.name}
                    <span className={`status-badge status-${r.status}`}>填寫中</span>
                  </div>
                  <div className="row-meta">{r.created_at}</div>
                </Link>
              ) : (
                <Link key={r.id} to={`/lookup/${r.id}`} className="list-row">
                  <div className="row-name">
                    {r.name}
                    <span className={`status-badge status-${r.status}`}>已送出</span>
                    <span className={`status-badge status-${r.booking_status}`}>
                      {r.booking_status === "scheduled"
                        ? `已約 ${r.booked_datetime ?? ""}`
                        : "尚未預約"}
                    </span>
                  </div>
                  <div className="row-meta">{r.submitted_at ?? r.created_at}</div>
                </Link>
              ),
            )}
          </div>
        )}

        {createError && <div className="error-text">{createError}</div>}

        <div className="actions">
          <button type="button" className="btn-primary" disabled={creating} onClick={handleCreateNew}>
            {creating ? "建立中…" : "＋ 新增表單"}
          </button>
        </div>
      </div>
    </div>
  );
}
