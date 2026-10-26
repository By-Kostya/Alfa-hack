import { useEffect, useState, type FormEvent } from 'react';
import {
  ApiError,
  isLinkApplication,
  type ApiClient,
  type ApplicationDetail,
  type Product,
  type ProductDetail,
} from '@alfa-hack/core-api';
import { formatRussianPhone, isRussianPhoneComplete, normalizeRussianPhone } from '@alfa-hack/core-auth';
import {
  applicationStatusLabel,
  emptyDraft,
  fieldLabel,
  formatRub,
  riskLabel,
  toApplicationRequest,
  validateDraft,
  type ApplicationDraft,
} from '@alfa-hack/core-credit';

type ApplyScreenProps = {
  api: ApiClient;
  productCode: string | null;
  token: string | null;
  sessionPhone: string | null;
  products: Product[];
  onPickProduct: (code: string) => void;
  onBack: () => void;
  onSession: (token: string) => Promise<void>;
  onDone: () => void;
};

function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Не удалось отправить заявку.';
}

export default function ApplyScreen({
  api,
  productCode,
  token,
  sessionPhone,
  products,
  onPickProduct,
  onBack,
  onSession,
  onDone,
}: ApplyScreenProps) {
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [draft, setDraft] = useState<ApplicationDraft>(emptyDraft);
  const [step, setStep] = useState<'fields' | 'phone' | 'done'>('fields');
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [result, setResult] = useState<ApplicationDetail | null>(null);
  const [phone, setPhone] = useState(() => formatRussianPhone(sessionPhone || '+7'));
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!productCode) return;
    let active = true;
    setDetail(null);
    setError('');
    setStep('fields');
    setResult(null);
    setApplicationId(null);
    api.getProductDetail(productCode)
      .then((next) => {
        if (active) setDetail(next);
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorText(requestError));
      });
    return () => {
      active = false;
    };
  }, [api, productCode]);

  useEffect(() => {
    if (sessionPhone) setPhone(formatRussianPhone(sessionPhone));
  }, [sessionPhone]);

  async function submitFields(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || !productCode || isSubmitting) return;
    const problem = validateDraft(draft, detail);
    if (problem) {
      setError(problem);
      return;
    }
    if (!token) {
      setError('');
      setStep('phone');
      return;
    }
    setIsSubmitting(true);
    setError('');
    try {
      const created = await api.createApplication(
        token,
        toApplicationRequest(productCode, draft, detail.fields),
      );
      if (isLinkApplication(created)) return;
      setApplicationId(created.id);
      setStep('phone');
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitPhone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = normalizeRussianPhone(phone);
    if (!detail || !productCode || !normalized || isSubmitting) return;
    setIsSubmitting(true);
    setError('');
    try {
      if (token && applicationId) {
        const scored = await api.confirmApplication(token, applicationId, { phone: normalized });
        setResult(scored);
        setStep('done');
        return;
      }
      const created = await api.createApplication(
        null,
        toApplicationRequest(productCode, draft, detail.fields, normalized),
      );
      if (!isLinkApplication(created)) {
        throw new ApiError('Сервер не открыл сессию.', 500);
      }
      await onSession(created.token);
      setResult(created.application);
      setStep('done');
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!productCode) {
    return (
      <section className="product-choice" aria-labelledby="auth-title">
        <button className="back-button" type="button" onClick={onBack}>← Назад</button>
        <p className="eyebrow">Заявка</p>
        <h1 id="auth-title">Выберите продукт</h1>
        <div className="product-choice-list">
          {products.map((product) => (
            <button className="product-choice-card" type="button" key={product.code} onClick={() => onPickProduct(product.code)}>
              <span className="product-choice-copy">
                <strong>{product.title}</strong>
                <span>{product.annual_rate_pct}% · {formatRub(product.min_amount_rub)} — {formatRub(product.max_amount_rub)} · {product.min_term_months}–{product.max_term_months} мес.</span>
              </span>
            </button>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="apply-screen" aria-labelledby="auth-title">
      <button className="back-button" type="button" onClick={step === 'phone' ? () => setStep('fields') : onBack}>
        ← Назад
      </button>
      <p className="eyebrow">{detail?.title ?? 'Заявка'}</p>
      {step === 'fields' && (
        <>
          <h1 id="auth-title">Условия кредита</h1>
          {detail && (
            <p className="intro">
              Ставка {detail.annual_rate_pct}% · {formatRub(detail.min_amount_rub)} — {formatRub(detail.max_amount_rub)} · {detail.min_term_months}–{detail.max_term_months} мес.
            </p>
          )}
          <form className="apply-form" onSubmit={submitFields}>
            {(detail?.fields ?? []).map((field) => (
              <Field
                key={field}
                field={field}
                detail={detail}
                draft={draft}
                onChange={(next) => {
                  setDraft(next);
                  setError('');
                }}
              />
            ))}
            {error && <p className="request-error" role="alert">{error}</p>}
            <button className="submit-button" type="submit" disabled={!detail || isSubmitting}>
              {isSubmitting ? 'Сохраняем…' : 'Продолжить'} <span aria-hidden="true">→</span>
            </button>
          </form>
        </>
      )}
      {step === 'phone' && (
        <>
          <h1 id="auth-title">Подтвердите номер</h1>
          <form className="phone-form" onSubmit={submitPhone}>
            <label className="phone-label" htmlFor="confirm-phone">Номер телефона</label>
            <input
              id="confirm-phone"
              className="apply-input"
              name="phone"
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(event) => {
                setPhone(formatRussianPhone(event.target.value));
                setError('');
              }}
              disabled={isSubmitting}
            />
            {error && <p className="request-error" role="alert">{error}</p>}
            <button className="submit-button" type="submit" disabled={!isRussianPhoneComplete(phone) || isSubmitting}>
              {isSubmitting ? 'Считаем…' : 'Подтвердить'} <span aria-hidden="true">→</span>
            </button>
          </form>
        </>
      )}
      {step === 'done' && result && (
        <>
          <h1 id="auth-title">{applicationStatusLabel(result.status, result.decision)}</h1>
          <dl className="detail-grid">
            <div><dt>Лимит</dt><dd>{formatRub(result.limit_rub)}</dd></div>
            <div><dt>Платёж</dt><dd>{formatRub(result.monthly_payment_rub)}</dd></div>
          </dl>
          {result.fallback && <p className="intro">Расчёт по формуле</p>}
          {result.report && result.report.risks.length > 0 && (
            <div className="product-requirements">
              {result.report.risks.map((risk) => <span key={risk}>{riskLabel(risk)}</span>)}
            </div>
          )}
          <button className="submit-button" type="button" onClick={onDone}>
            В кабинет <span aria-hidden="true">→</span>
          </button>
        </>
      )}
    </section>
  );
}

function Field({
  field,
  detail,
  draft,
  onChange,
}: {
  field: string;
  detail: ProductDetail | null;
  draft: ApplicationDraft;
  onChange: (draft: ApplicationDraft) => void;
}) {
  const label = fieldLabel(field);
  if (field === 'profitability_confirmed' || field === 'collateral') {
    const checked = field === 'collateral' ? draft.collateral : draft.profitabilityConfirmed;
    return (
      <label className="apply-check">
        <input
          type="checkbox"
          checked={checked}
          onChange={(event) => onChange({
            ...draft,
            [field === 'collateral' ? 'collateral' : 'profitabilityConfirmed']: event.target.checked,
          })}
        />
        {label}
      </label>
    );
  }
  if (field === 'business_plan') {
    return (
      <label className="phone-label">
        {label}
        <textarea
          className="apply-input"
          rows={5}
          placeholder="Выручка 180000 руб. в месяц"
          value={draft.businessPlan}
          onChange={(event) => onChange({ ...draft, businessPlan: event.target.value })}
        />
      </label>
    );
  }
  if (field === 'purpose') {
    return (
      <label className="phone-label">
        {label}
        <input
          className="apply-input"
          value={draft.purpose}
          onChange={(event) => onChange({ ...draft, purpose: event.target.value })}
        />
      </label>
    );
  }
  const value = field === 'loan_amount_rub'
    ? draft.loanAmountRub
    : field === 'loan_term_months'
      ? draft.loanTermMonths
      : draft.profitabilityRub;
  const key = field === 'loan_amount_rub'
    ? 'loanAmountRub'
    : field === 'loan_term_months'
      ? 'loanTermMonths'
      : 'profitabilityRub';
  const placeholder = field === 'loan_amount_rub' && detail
    ? `${formatRub(detail.min_amount_rub)} — ${formatRub(detail.max_amount_rub)}`
    : field === 'loan_term_months' && detail
      ? `${detail.min_term_months}–${detail.max_term_months}`
      : undefined;
  return (
    <label className="phone-label">
      {label}
      <input
        className="apply-input"
        inputMode="numeric"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange({ ...draft, [key]: event.target.value })}
      />
    </label>
  );
}
