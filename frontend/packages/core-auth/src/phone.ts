const RU_PHONE_LENGTH = 11;

export function digitsOnly(value: string): string {
  return value.replace(/\D/g, '');
}

export function normalizeRussianPhone(value: string): string | null {
  let digits = digitsOnly(value);

  if (digits.length === 10) {
    digits = `7${digits}`;
  } else if (digits.length === RU_PHONE_LENGTH && digits.startsWith('8')) {
    digits = `7${digits.slice(1)}`;
  }

  if (digits.length !== RU_PHONE_LENGTH || !digits.startsWith('7')) {
    return null;
  }

  return digits;
}

export function formatRussianPhone(value: string): string {
  const digits = digitsOnly(value).replace(/^8/, '7').replace(/^7/, '').slice(0, 12);
  const parts = [digits.slice(0, 3), digits.slice(3, 6), digits.slice(6, 8), digits.slice(8, 10)];
  const [area, first, second, third] = parts;

  let result = '+7';
  if (area) result += ` (${area}`;
  if (area.length === 3) result += ')';
  if (first) result += ` ${first}`;
  if (second) result += `-${second}`;
  if (third) result += `-${third}`;

  return result;
}

export function isRussianPhoneComplete(value: string): boolean {
  return normalizeRussianPhone(value) !== null;
}
