import type { ApplicationCreateRequest, Product, ProductDetail } from '@alfa-hack/core-api';

const PRODUCT_COPY: Record<string, { badge: string; description: string }> = {
  working_capital: {
    badge: 'Оборот',
    description: 'На закупки, аренду и текущие платежи',
  },
  startup: {
    badge: 'Старт',
    description: 'На запуск нового дела',
  },
  equipment: {
    badge: 'Техника',
    description: 'На станки, транспорт и оснащение',
  },
  contract: {
    badge: 'Контракт',
    description: 'На исполнение договора',
  },
  overdraft: {
    badge: 'Овердрафт',
    description: 'На кассовые разрывы',
  },
  refinance: {
    badge: 'Рефинанс',
    description: 'На замену действующего кредита',
  },
};

export type ProductCard = Product & {
  badge: string;
  description: string;
  ratePct: number;
  minAmountRub: number;
  maxAmountRub: number;
  minTermMonths: number;
  maxTermMonths: number;
};

export function presentProduct(product: Product): ProductCard {
  const copy = PRODUCT_COPY[product.code] ?? { badge: 'Кредит', description: '' };
  return {
    ...product,
    ...copy,
    ratePct: product.annual_rate_pct,
    minAmountRub: product.min_amount_rub,
    maxAmountRub: product.max_amount_rub,
    minTermMonths: product.min_term_months,
    maxTermMonths: product.max_term_months,
  };
}

const FIELD_LABELS: Record<string, string> = {
  loan_amount_rub: 'Сумма кредита',
  loan_term_months: 'Срок кредита',
  purpose: 'Цель кредита',
  profitability_rub: 'Доходность в месяц',
  profitability_confirmed: 'Доходность подтверждена',
  collateral: 'Есть залог',
  business_plan: 'Бизнес-план',
  own_funds_rub: 'Собственные средства',
  credit_rating: 'Кредитный рейтинг',
};

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? 'Дополнительные данные';
}

const RISK_LABELS: Record<string, string> = {
  thin_margin: 'тонкая маржа',
  rent: 'аренда',
  slow_ramp: 'медленный выход на поток',
  client_concentration: 'зависимость от одного клиента',
  lumpy_revenue: 'рваная выручка',
  seasonality: 'сезонность',
  fixed_costs: 'постоянные расходы',
  location: 'место',
  negative_unit_economics: 'отрицательная юнит-экономика',
  subsidies: 'зависимость от субсидий',
  competition: 'конкуренция',
  rare_payment: 'редкие платежи',
  unclear_payer: 'неясный плательщик',
  small_market: 'узкий рынок',
  cold_start: 'холодный старт',
  fraud: 'риск мошенничества',
  late_monetization: 'поздняя монетизация',
  inventory: 'склад',
  customs: 'таможня',
  returns: 'возвраты',
  fx: 'валюта',
};

export function riskLabel(code: string): string {
  return RISK_LABELS[code] ?? code;
}

export function applicationStatusLabel(status: string, decision: string | null): string {
  if (status === 'draft') return 'Черновик';
  if (decision === 'approve') return 'Одобрена';
  if (decision === 'reduced') return 'Одобрена на меньшую сумму';
  if (decision === 'reject') return 'Отказ';
  if (decision === 'unknown') return 'Нужно уточнить данные';
  return 'Заявка принята';
}

export function formatRub(value: number | null): string {
  if (value === null) return '—';
  return `${new Intl.NumberFormat('ru-RU').format(value)} ₽`;
}

export function formatCompactRub(value: number): string {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency',
    currency: 'RUB',
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export type ApplicationDraft = {
  loanAmountRub: string;
  loanTermMonths: string;
  purpose: string;
  profitabilityRub: string;
  profitabilityConfirmed: boolean;
  collateral: boolean;
  businessPlan: string;
};

export function emptyDraft(): ApplicationDraft {
  return {
    loanAmountRub: '',
    loanTermMonths: '',
    purpose: '',
    profitabilityRub: '',
    profitabilityConfirmed: false,
    collateral: false,
    businessPlan: '',
  };
}

function integer(value: string): number | null {
  const trimmed = value.trim();
  if (!/^-?\d+$/.test(trimmed)) return null;
  return Number(trimmed);
}

export function validateDraft(draft: ApplicationDraft, detail: ProductDetail): string | null {
  const fields = detail.fields;
  if (fields.includes('loan_amount_rub')) {
    const amount = integer(draft.loanAmountRub);
    if (amount === null || amount < detail.min_amount_rub || amount > detail.max_amount_rub) {
      return `Сумма — от ${formatRub(detail.min_amount_rub)} до ${formatRub(detail.max_amount_rub)}.`;
    }
  }
  if (fields.includes('loan_term_months')) {
    const term = integer(draft.loanTermMonths);
    if (term === null || term < detail.min_term_months || term > detail.max_term_months) {
      return `Срок — от ${detail.min_term_months} до ${detail.max_term_months} месяцев.`;
    }
  }
  if (fields.includes('purpose') && !draft.purpose.trim()) return 'Укажите цель кредита.';
  if (fields.includes('profitability_rub') && integer(draft.profitabilityRub) === null) {
    return 'Укажите доходность в рублях за месяц.';
  }
  if (fields.includes('business_plan') && !draft.businessPlan.trim()) return 'Добавьте бизнес-план.';
  return null;
}

export function toApplicationRequest(
  product: string,
  draft: ApplicationDraft,
  fields: string[],
  phone?: string,
): ApplicationCreateRequest {
  const request: ApplicationCreateRequest = {
    product,
    loan_amount_rub: integer(draft.loanAmountRub) ?? 0,
    loan_term_months: integer(draft.loanTermMonths) ?? 0,
  };
  if (phone) request.phone = phone;
  if (fields.includes('purpose')) request.purpose = draft.purpose.trim();
  if (fields.includes('profitability_rub')) request.profitability_rub = integer(draft.profitabilityRub);
  if (fields.includes('profitability_confirmed')) request.profitability_confirmed = draft.profitabilityConfirmed;
  if (fields.includes('collateral')) request.collateral = draft.collateral;
  if (fields.includes('business_plan')) request.business_plan = draft.businessPlan.trim();
  return request;
}
