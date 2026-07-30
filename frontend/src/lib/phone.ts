// 台灣手機號碼固定 09 開頭共 10 碼。

const PHONE_REGEX = /^09\d{8}$/;

export const PHONE_FORMAT_HINT = "09 開頭共 10 碼，例如 0912345678";

// 輸入時即時把非數字字元濾掉、超過 10 碼截斷，讓使用者貼上「0912-345-678」
// 這類格式時也能自動清成純數字，不用自己重打。
export function sanitizePhoneInput(raw: string): string {
  return raw.replace(/\D/g, "").slice(0, 10);
}

export function isValidPhone(phone: string): boolean {
  return PHONE_REGEX.test(phone);
}
