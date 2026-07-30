// 依 schema + 目前答案算出「可見題目清單」的規則引擎。
// 這裡的邏輯需要跟 backend/app/question_schema_v1.py 描述的 schema 格式保持一致。

export interface QuestionOption {
  value: string;
  label: string;
  showIf?: ShowIfRule;
}

export interface OptionsBySource {
  source: string;
  map: Record<string, QuestionOption[]>;
  default: QuestionOption[];
}

export type ShowIfRule =
  | { field: string; includes: string }
  | { field: string; eq: string }
  | { allOf: ShowIfRule[] }
  | { anyOf: ShowIfRule[] }
  | { not: ShowIfRule };

// "info" 是非互動題：不會出現在顧客的逐題流程裡，只用來在摘要/明細顯示給設計師參考的資訊
// （例如依禿頭類型列出的接髮技術候選，是給設計師判斷用，不是顧客要選的答案）。
export type QuestionType = "multi" | "single" | "text" | "textarea" | "info";

export interface QuestionStep {
  id: string;
  type: QuestionType;
  question: string;
  sub?: string;
  // 顯示給顧客看的提醒文字（例如建議但不強制的做法），純資訊性，不影響作答與驗證。
  note?: string;
  summaryLabel?: string;
  placeholder?: string;
  options?: QuestionOption[];
  optionsBySource?: OptionsBySource;
  showIf?: ShowIfRule;
  // multi 題若有一個選項代表「其他」，這裡指定它的 value；選到時前端會多顯示一個
  // 文字框讓使用者自行描述，答案存在 answers[`${step.id}Other`]。
  otherValue?: string;
}

export type AnswerValue = string | string[] | undefined;
export type Answers = Record<string, AnswerValue>;

export function otherAnswerKey(step: QuestionStep): string {
  return `${step.id}Other`;
}

function evalRule(rule: ShowIfRule | undefined, answers: Answers): boolean {
  if (!rule) return true;
  if ("allOf" in rule) return rule.allOf.every((r) => evalRule(r, answers));
  if ("anyOf" in rule) return rule.anyOf.some((r) => evalRule(r, answers));
  if ("not" in rule) return !evalRule(rule.not, answers);
  const value = answers[rule.field];
  if ("includes" in rule) return Array.isArray(value) && value.includes(rule.includes);
  return value === rule.eq;
}

export function resolveOptions(step: QuestionStep, answers: Answers): QuestionOption[] {
  let options: QuestionOption[];
  if (step.optionsBySource) {
    const sourceValue = answers[step.optionsBySource.source];
    options =
      typeof sourceValue === "string" && step.optionsBySource.map[sourceValue]
        ? step.optionsBySource.map[sourceValue]
        : step.optionsBySource.default;
  } else {
    options = step.options ?? [];
  }
  return options.filter((opt) => evalRule(opt.showIf, answers));
}

export function computeVisibleSteps(steps: QuestionStep[], answers: Answers): QuestionStep[] {
  return steps.filter((step) => evalRule(step.showIf, answers));
}

export function formatAnswer(step: QuestionStep, answers: Answers): string {
  if (step.type === "info") {
    const options = resolveOptions(step, answers);
    return options.length > 0 ? options.map((o) => o.label).join("、") : "（無建議）";
  }
  const value = answers[step.id];
  if (value === undefined || value === null || value === "") return "（未填寫）";
  if (step.type === "multi") {
    if (!Array.isArray(value) || value.length === 0) return "（未填寫）";
    const options = resolveOptions(step, answers);
    return value
      .map((v) => {
        if (step.otherValue && v === step.otherValue) {
          const otherText = answers[otherAnswerKey(step)];
          return typeof otherText === "string" && otherText.trim() ? `其他：${otherText.trim()}` : "其他";
        }
        return options.find((o) => o.value === v)?.label ?? v;
      })
      .join("、");
  }
  if (step.type === "single") {
    const options = resolveOptions(step, answers);
    return options.find((o) => o.value === value)?.label ?? String(value);
  }
  return String(value);
}

export function isStepAnswerValid(step: QuestionStep, answers: Answers): boolean {
  const value = answers[step.id];
  if (step.type === "multi") {
    if (!Array.isArray(value) || value.length === 0) return false;
    if (step.otherValue && value.includes(step.otherValue)) {
      const otherText = answers[otherAnswerKey(step)];
      return typeof otherText === "string" && otherText.trim().length > 0;
    }
    return true;
  }
  if (step.type === "text") return typeof value === "string" && value.trim().length > 0;
  return true; // single 選了就自動前進；textarea 為選填
}
