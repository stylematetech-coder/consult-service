import type { Answers, QuestionStep } from "../lib/engine";

const API_URL = import.meta.env.VITE_API_URL ?? "/api";

export interface QuestionnaireSchema {
  id: string;
  version: string;
  is_active: boolean;
  created_at: string;
  steps: QuestionStep[];
}

export type Gender = "male" | "female";

export interface ResponseSummary {
  id: string;
  schema_id: string;
  name: string;
  phone: string;
  gender: Gender;
  status: "in_progress" | "submitted";
  created_at: string;
  submitted_at: string | null;
}

export interface ResponseRecord extends ResponseSummary {
  answers: Answers;
}

export interface CreateResponseResult extends ResponseRecord {
  // resumed：接續同一天內尚未填完的草稿；prefilled：帶入上次已送出問卷的答案當初始值。
  resumed: boolean;
  prefilled: boolean;
}

// FastAPI 的錯誤回應 detail 可能是一句話（例如我們自己丟的 409），也可能是
// pydantic 驗證失敗時的物件陣列（每個物件裡有 msg）；這裡統一整理成一句可以
// 直接顯示給使用者看的文字，而不是把整包物件的 JSON 字串丟出去。
function extractErrorMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === "object" && typeof (d as { msg?: unknown }).msg === "string" ? (d as { msg: string }).msg : JSON.stringify(d)))
      .join("；");
  }
  return `Request failed: ${status}`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(extractErrorMessage(body, res.status));
  }
  return res.json() as Promise<T>;
}

export const api = {
  getActiveSchema: () => request<{ schema: QuestionnaireSchema }>("/schema/active"),

  getSchema: (id: string) => request<{ schema: QuestionnaireSchema }>(`/schema/${id}`),

  // lineUid：從 LINE 聊天室的預約按鈕開啟時，網址會帶 ?uid=<LINE userId>，
  // 隨建檔寫進資料庫，讓 LINE bot 能把「填完表單」對回正確的聊天室。
  // 直接開網址（沒有 uid）也照常運作。
  createResponse: (name: string, phone: string, gender: Gender, lineUid?: string | null) =>
    request<{ response: CreateResponseResult }>("/responses", {
      method: "POST",
      body: JSON.stringify({ name, phone, gender, line_uid: lineUid ?? null }),
    }),

  patchAnswers: (id: string, answers: Answers) =>
    request<{ response: ResponseRecord }>(`/responses/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ answers }),
    }),

  submitResponse: (id: string) =>
    request<{ response: ResponseRecord }>(`/responses/${id}/submit`, { method: "POST" }),

  listResponses: (phone: string) =>
    request<{ responses: ResponseSummary[] }>(`/responses?phone=${encodeURIComponent(phone)}`),

  getResponse: (id: string) => request<{ response: ResponseRecord }>(`/responses/${id}`),
};
