import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type BusinessHoursDay, type Gender, type QuestionnaireSchema } from "../api/client";
import {
  type Answers,
  computeVisibleSteps,
  formatAnswer,
  isStepAnswerValid,
  otherAnswerKey,
  resolveOptions,
} from "../lib/engine";

type Phase = "loading" | "form" | "submitted";

const WEEKDAY_LABELS = ["日", "一", "二", "三", "四", "五", "六"];

function currentYearMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function addMonths(yearMonth: string, delta: number): string {
  const [year, month] = yearMonth.split("-").map(Number);
  const d = new Date(year, month - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function todayDateString(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

// 姓名/電話/性別的收集與「建立表單」這個動作，都移到 MyForms.tsx 的入口
// 流程去做了(2026-08-04 調整：客人要先打完姓名電話、才看得到/建得了表單，
// 不是先看列表、點 + 才問)。這裡只負責「續填一筆已經存在的表單」，一律
// 透過 /edit/:id 進來，記錄本身(含姓名/電話/性別)已經在建立當下就有了。
export function Questionnaire() {
  const { id: editId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const lineUidParam = new URLSearchParams(window.location.search).get("uid");

  const [schema, setSchema] = useState<QuestionnaireSchema | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [phase, setPhase] = useState<Phase>("loading");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");

  const [responseId, setResponseId] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [currentIndex, setCurrentIndex] = useState(0);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [showPrefillNote, setShowPrefillNote] = useState(false);

  // 表單最後一步的「選預約時間」——bookingDate/bookingTime 都選定後才會進到
  // 摘要畫面；兩者分開存(不混進 answers)，因為這不是 schema 驅動的題目，是
  // 直接打 calendar-service 資料串出來的獨立步驟。
  const [viewMonth, setViewMonth] = useState(currentYearMonth);
  const [businessDays, setBusinessDays] = useState<BusinessHoursDay[]>([]);
  const [bookingDate, setBookingDate] = useState<string | null>(null);
  const [bookingTime, setBookingTime] = useState<string | null>(null);
  const [slots, setSlots] = useState<string[]>([]);
  const [slotsLoading, setSlotsLoading] = useState(false);
  const [bookingError, setBookingError] = useState<string | null>(null);
  const [bookingSubmitting, setBookingSubmitting] = useState(false);

  const advanceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const patchTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    api
      .getActiveSchema()
      .then((res) => setSchema(res.schema))
      .catch(() => setLoadError("無法載入問卷題目，請確認後端服務是否已啟動。"));
  }, []);

  // 載入這筆既有草稿：直接跳進 "form" 階段(姓名/電話/性別在建立當下就已經
  // 有了，不用重問)。萬一這筆其實已經送出(理論上「我的表單」只會把
  // in_progress 導來這裡，但直接打網址仍可能碰到)，改導去唯讀的檢視頁，
  // 不要讓客人以為還能用這個表單流程去改一筆已經定案的紀錄。
  useEffect(() => {
    if (!editId) {
      setLoadError("缺少表單編號，請從「我的表單」重新進入。");
      return;
    }
    api
      .getResponse(editId)
      .then((res) => {
        if (res.response.status === "submitted") {
          navigate(`/lookup/${editId}`, { replace: true });
          return;
        }
        setName(res.response.name);
        setPhone(res.response.phone);
        setResponseId(res.response.id);
        setAnswers(res.response.answers);
        // MyForms 剛建立這筆時如果帶了上次送出的答案當初始值，會在導過來的
        // 網址加上 prefilled=1；這裡只是讀出來顯示提示文字，不影響資料本身。
        setShowPrefillNote(new URLSearchParams(window.location.search).get("prefilled") === "1");
        setPhase("form");
      })
      .catch(() => setLoadError("找不到這筆表單，可能已經被刪除。"));
  }, [editId, navigate]);

  // allSteps 含 info 型別（例如接髮技術建議），只給摘要顯示用；
  // interactiveSteps 才是顧客實際會逐題作答、拿來算「第 x / y 題」的清單。
  const allSteps = useMemo(() => (schema ? computeVisibleSteps(schema.steps, answers) : []), [schema, answers]);
  const interactiveSteps = useMemo(() => allSteps.filter((s) => s.type !== "info"), [allSteps]);
  const total = interactiveSteps.length;
  const idx = Math.min(currentIndex, total);
  const isSummary = idx >= total;
  const currentStep = isSummary ? null : interactiveSteps[idx];

  // "services" 這題的答案換算成中文字串（例如 "染髮、燙髮"）——跟
  // calendar-service 的六大服務類別是同一套字，估算時長/查可約時段都要用
  // 這個字串，不是 answers.services 原本的英文 value 陣列。
  const servicesStep = schema?.steps.find((s) => s.id === "services");
  const serviceLabel = servicesStep ? formatAnswer(servicesStep, answers) : "";
  const gender = (answers.gender as Gender | undefined) ?? "male";

  const bookingConfirmed = Boolean(bookingDate && bookingTime);
  const showBookingStep = isSummary && !bookingConfirmed;

  useEffect(() => {
    if (!showBookingStep) return;
    api
      .getBusinessHours(viewMonth)
      .then((res) => setBusinessDays(res.days))
      .catch(() => setBusinessDays([]));
  }, [showBookingStep, viewMonth]);

  useEffect(() => {
    if (!showBookingStep || !bookingDate) {
      setSlots([]);
      return;
    }
    setSlotsLoading(true);
    setBookingError(null);
    api
      .getSlots(bookingDate, serviceLabel, gender)
      .then((res) => setSlots(res.slots))
      .catch(() => setBookingError("無法取得可預約時段，請稍後再試"))
      .finally(() => setSlotsLoading(false));
  }, [showBookingStep, bookingDate, serviceLabel, gender]);

  function selectBookingDate(date: string) {
    setBookingDate(date);
    setBookingTime(null);
  }

  function goBackFromBooking() {
    setBookingDate(null);
    setBookingTime(null);
    goBack();
  }

  function autosave(nextAnswers: Answers) {
    if (!responseId) return;
    api.patchAnswers(responseId, nextAnswers).catch(() => {
      /* 現場自填情境下，autosave 失敗先靜默重試下一次操作即可，不打斷填寫流程 */
    });
  }

  function selectSingleAndAdvance(stepId: string, value: string) {
    setAnswers((prev) => {
      const next: Answers = { ...prev, [stepId]: value };
      // 依賴這一題選項的下一題（例如接髮技術建議依禿頭類型而定）也一併清掉，避免殘留不相容的舊答案
      for (const step of schema?.steps ?? []) {
        if (step.optionsBySource?.source === stepId) delete next[step.id];
      }
      autosave(next);
      return next;
    });
    clearTimeout(advanceTimer.current);
    advanceTimer.current = setTimeout(() => setCurrentIndex((i) => i + 1), 200);
  }

  function toggleMulti(stepId: string, value: string) {
    setAnswers((prev) => {
      const arr = Array.isArray(prev[stepId]) ? [...(prev[stepId] as string[])] : [];
      const next: Answers = {
        ...prev,
        [stepId]: arr.includes(value) ? arr.filter((v) => v !== value) : [...arr, value],
      };
      autosave(next);
      return next;
    });
  }

  function handleTextChange(stepId: string, value: string) {
    setAnswers((prev) => {
      const next = { ...prev, [stepId]: value };
      clearTimeout(patchTimer.current);
      patchTimer.current = setTimeout(() => autosave(next), 400);
      return next;
    });
  }

  function goNext() {
    setCurrentIndex((i) => i + 1);
  }

  function goBack() {
    setCurrentIndex((i) => Math.max(0, i - 1));
  }

  async function handleSubmit() {
    if (!responseId || !bookingDate || !bookingTime) return;
    setSubmitError(null);
    setBookingSubmitting(true);
    try {
      await api.patchAnswers(responseId, answers);
      await api.createBooking(responseId, bookingDate, bookingTime);
    } catch (err) {
      // 這個時段可能剛被約走、或已經不在營業時間內——回到選時間畫面，
      // 重新抓一次可用時段，而不是讓顧客以為已經約成功了。
      setBookingSubmitting(false);
      setBookingTime(null);
      setBookingError(err instanceof Error ? err.message : "預約失敗，請重新選擇時段");
      return;
    }
    try {
      await api.submitResponse(responseId);
      setPhase("submitted");
    } catch {
      setSubmitError("送出失敗，請稍後再試一次");
    } finally {
      setBookingSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <div className="page">
        <div className="card error-text">{loadError}</div>
      </div>
    );
  }

  if (!schema || phase === "loading") {
    return (
      <div className="page">
        <div className="card">載入中…</div>
      </div>
    );
  }

  if (phase === "submitted") {
    return (
      <div className="page">
        <div className="card thanks">
          <div className="title">感謝您的填寫</div>
          <div className="subtitle">您的諮詢資料已送出，設計師將依此為您規劃專屬方案。</div>
          <button
            type="button"
            className="btn-primary"
            onClick={() =>
              navigate(lineUidParam ? `/?uid=${encodeURIComponent(lineUidParam)}` : "/")
            }
          >
            返回我的表單
          </button>
        </div>
      </div>
    );
  }

  if (showBookingStep) {
    const [viewYear, viewMonthNum] = viewMonth.split("-").map(Number);
    const daysInMonth = new Date(viewYear, viewMonthNum, 0).getDate();
    const leadingBlanks = new Date(viewYear, viewMonthNum - 1, 1).getDay();
    const byDate = new Map(businessDays.map((d) => [d.date, d]));
    const today = todayDateString();

    return (
      <div className="page">
        <div className="card">
          <div className="title">選擇預約時間</div>
          <div className="subtitle">請選擇有營業的日期與可預約時段</div>

          <div className="calendar-header">
            <button type="button" className="btn-secondary" onClick={() => setViewMonth((m) => addMonths(m, -1))}>
              ‹
            </button>
            <span>{viewYear} 年 {viewMonthNum} 月</span>
            <button type="button" className="btn-secondary" onClick={() => setViewMonth((m) => addMonths(m, 1))}>
              ›
            </button>
          </div>

          <div className="calendar-grid">
            {WEEKDAY_LABELS.map((w) => (
              <div className="calendar-weekday" key={w}>{w}</div>
            ))}
            {Array.from({ length: leadingBlanks }).map((_, i) => (
              <div key={`blank-${i}`} />
            ))}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const dateStr = `${viewMonth}-${String(i + 1).padStart(2, "0")}`;
              const info = byDate.get(dateStr);
              const isPast = dateStr < today;
              const disabled = isPast || !info || info.closed;
              return (
                <button
                  key={dateStr}
                  type="button"
                  className={dateStr === bookingDate ? "calendar-day selected" : "calendar-day"}
                  disabled={disabled}
                  onClick={() => selectBookingDate(dateStr)}
                >
                  {i + 1}
                </button>
              );
            })}
          </div>

          {bookingDate && (
            <div className="slot-section">
              <div className="question-sub">{bookingDate} 可預約時段</div>
              {slotsLoading && <div className="question-note">載入中…</div>}
              {!slotsLoading && slots.length === 0 && (
                <div className="question-note">這天沒有可預約的時段了，請選別的日期。</div>
              )}
              <div className="slot-grid">
                {slots.map((time) => (
                  <button
                    key={time}
                    type="button"
                    className={time === bookingTime ? "option-btn selected" : "option-btn"}
                    onClick={() => setBookingTime(time)}
                  >
                    {time}
                  </button>
                ))}
              </div>
            </div>
          )}

          {bookingError && <div className="error-text">{bookingError}</div>}
          <div className="actions">
            <button type="button" className="btn-secondary" onClick={goBackFromBooking}>
              上一步
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (isSummary) {
    // info 型別（例如接髮技術建議）是給設計師參考用，不在顧客自己看的摘要頁顯示；
    // 這份資料仍會完整保留在後端，設計師查詢的明細頁看得到。
    const summaryList = [
      { label: "姓名", answer: name },
      { label: "手機號碼", answer: phone },
      { label: "預約時間", answer: `${bookingDate} ${bookingTime}` },
      ...allSteps
        .filter((step) => step.type !== "info")
        .map((step) => ({
          label: step.summaryLabel ?? step.question,
          answer: formatAnswer(step, answers),
        })),
    ];
    return (
      <div className="page">
        <div className="card">
          <div className="title">預約摘要</div>
          <div className="subtitle">{new Date().toLocaleDateString("zh-TW", { year: "numeric", month: "long", day: "numeric" })}</div>
          <div className="summary-list">
            {summaryList.map((item) => (
              <div className="summary-item" key={item.label}>
                <div className="summary-label">{item.label}</div>
                <div className="summary-answer">{item.answer}</div>
              </div>
            ))}
          </div>
          {submitError && <div className="error-text">{submitError}</div>}
          <div className="actions">
            <button type="button" className="btn-secondary" onClick={() => setBookingTime(null)}>
              上一步
            </button>
            <button type="button" className="btn-primary" disabled={bookingSubmitting} onClick={handleSubmit}>
              {bookingSubmitting ? "送出中…" : "確認送出"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!currentStep) return null;

  const isMulti = currentStep.type === "multi";
  const isSingle = currentStep.type === "single";
  const isText = currentStep.type === "text";
  const isTextarea = currentStep.type === "textarea";
  const options = isMulti || isSingle ? resolveOptions(currentStep, answers) : [];
  const currentValue = answers[currentStep.id];
  const otherTextValue = answers[otherAnswerKey(currentStep)];
  const isLast = idx === total - 1;
  const valid = isStepAnswerValid(currentStep, answers);
  const showNextButton = isMulti || isText || isTextarea;

  return (
    <div className="page">
      <div className="card">
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${Math.round((idx / total) * 100)}%` }} />
        </div>
        <div className="step-count">
          第 {idx + 1} / {total} 題
        </div>
        {idx === 0 && showPrefillNote && (
          <div className="question-note">已為您帶入上次填寫的資料，如有變動請逐題修改。</div>
        )}
        <div className="question">{currentStep.question}</div>
        {currentStep.sub && <div className="question-sub">{currentStep.sub}</div>}
        {currentStep.note && <div className="question-note">{currentStep.note}</div>}

        {(isMulti || isSingle) && (
          <div className="options">
            {options.map((opt) => {
              const selected = isMulti
                ? Array.isArray(currentValue) && currentValue.includes(opt.value)
                : currentValue === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  className={selected ? "option-btn selected" : "option-btn"}
                  onClick={() =>
                    isMulti
                      ? toggleMulti(currentStep.id, opt.value)
                      : selectSingleAndAdvance(currentStep.id, opt.value)
                  }
                >
                  <span>{opt.label}</span>
                  {selected && <span>✓</span>}
                </button>
              );
            })}
          </div>
        )}

        {isMulti &&
          currentStep.otherValue &&
          Array.isArray(currentValue) &&
          currentValue.includes(currentStep.otherValue) && (
            <input
              className="field-input"
              placeholder="請描述"
              value={typeof otherTextValue === "string" ? otherTextValue : ""}
              onChange={(e) => handleTextChange(otherAnswerKey(currentStep), e.target.value)}
            />
          )}

        {isText && (
          <input
            className="field-input"
            placeholder={currentStep.placeholder}
            value={typeof currentValue === "string" ? currentValue : ""}
            onChange={(e) => handleTextChange(currentStep.id, e.target.value)}
          />
        )}

        {isTextarea && (
          <textarea
            className="field-textarea"
            placeholder={currentStep.placeholder}
            value={typeof currentValue === "string" ? currentValue : ""}
            onChange={(e) => handleTextChange(currentStep.id, e.target.value)}
          />
        )}

        <div className="actions">
          {idx > 0 && (
            <button type="button" className="btn-secondary" onClick={goBack}>
              上一步
            </button>
          )}
          {showNextButton && (
            <button type="button" className="btn-primary" disabled={!valid} onClick={goNext}>
              {isLast ? "查看摘要" : "下一步"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
