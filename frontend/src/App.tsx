import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, createApiClient, type Cabinet } from '@alfa-hack/core-api';
import { formatRussianPhone, isRussianPhoneComplete, normalizeRussianPhone } from '@alfa-hack/core-auth';

const TOKEN_KEY = 'alfa-hack:token';
const api = createApiClient();

function App() {
  const [phone, setPhone] = useState('+7');
  const [step, setStep] = useState<'phone' | 'code'>('phone');
  const [code, setCode] = useState('');
  const [cabinet, setCabinet] = useState<Cabinet | null>(null);
  const [cabinetScreen, setCabinetScreen] = useState<'dashboard' | 'product-choice'>('dashboard');
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRestoring, setIsRestoring] = useState(() => Boolean(sessionStorage.getItem(TOKEN_KEY)));

  const isComplete = isRussianPhoneComplete(phone);
  const normalizedPhone = normalizeRussianPhone(phone);

  useEffect(() => {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return;

    api.getCabinet(token)
      .then((nextCabinet) => {
        setCabinet(nextCabinet);
        setCabinetScreen('dashboard');
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof ApiError && requestError.status === 401) {
          sessionStorage.removeItem(TOKEN_KEY);
        }
        setError(getErrorMessage(requestError));
      })
      .finally(() => setIsRestoring(false));
  }, []);

  function handlePhoneChange(value: string) {
    setPhone(formatRussianPhone(value));
    setError('');
  }

  function handlePhoneSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!normalizedPhone || isSubmitting) return;

    setError('');
    api.requestMockSmsCode(normalizedPhone);
    setCode('');
    setStep('code');
  }

  async function handleCodeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!normalizedPhone || isSubmitting) return;

    if (!api.verifyMockSmsCode(normalizedPhone, code)) {
      setError('Неверный код. Проверьте его и попробуйте ещё раз.');
      return;
    }

    setError('');
    setIsSubmitting(true);
    try {
      const session = await api.createSession(normalizedPhone);
      if (!session.token) throw new Error('Сервер не вернул токен входа.');

      sessionStorage.setItem(TOKEN_KEY, session.token);
      const nextCabinet = await api.getCabinet(session.token);
      setCabinet(nextCabinet);
      setCabinetScreen('dashboard');
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        sessionStorage.removeItem(TOKEN_KEY);
      }
      setError(getErrorMessage(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLogout() {
    const token = sessionStorage.getItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_KEY);
    setCabinet(null);
    setCabinetScreen('dashboard');
    setSelectedProduct(null);
    setError('');
    setStep('phone');
    setCode('');

    if (!token) return;
    try {
      await api.deleteSession(token);
    } catch {
      // The local session is cleared even when the server cannot be reached.
    }
  }

  if (isRestoring) {
    return <main className="loading-screen" role="status">Загружаем личный кабинет…</main>;
  }

  return (
    <main className="auth-layout">
      <section className="auth-panel" aria-labelledby="auth-title">
        <header className="topbar">
          <div className="wordmark" aria-label="Альфа-Бизнес">
            <span className="wordmark__alpha">Альфа</span><span className="wordmark__bank">Бизнес</span>
          </div>
        </header>

        <div className={`auth-content${cabinet ? ' auth-content--dashboard' : ''}`}>
          <div className={`auth-copy${cabinet ? ' auth-copy--dashboard' : ''}`}>
            {cabinet ? (
              cabinetScreen === 'dashboard' ? (
                <section className="dashboard" aria-labelledby="auth-title">
                  <div className="dashboard-heading">
                    <div>
                      <p className="eyebrow">Личный кабинет</p>
                      <h1 id="auth-title">Здравствуйте</h1>
                      <p className="dashboard-phone">{cabinet.user.phone}</p>
                    </div>
                    <button
                      className="dashboard-cta"
                      type="button"
                      onClick={() => {
                        setCabinetScreen('product-choice');
                        setSelectedProduct(null);
                      }}
                    >
                      <span aria-hidden="true">＋</span> Взять кредит
                    </button>
                  </div>

                  <div className="dashboard-stats" aria-label="Сводка по кабинету">
                    <article className="dashboard-stat">
                      <span>Заявки</span>
                      <strong>{cabinet.applications.length}</strong>
                    </article>
                    <article className="dashboard-stat">
                      <span>Активные кредиты</span>
                      <strong>{cabinet.credits.filter((credit) => credit.status === 'active').length}</strong>
                    </article>
                    <article className="dashboard-stat">
                      <span>Продукты</span>
                      <strong>{cabinet.products.length}</strong>
                    </article>
                  </div>

                  <section className="dashboard-section" aria-labelledby="applications-title">
                    <div className="dashboard-section-heading">
                      <h2 id="applications-title">Мои заявки</h2>
                      <span>{cabinet.applications.length}</span>
                    </div>
                    {cabinet.applications.length ? (
                      <ul className="dashboard-list">
                        {cabinet.applications.slice(0, 3).map((application) => (
                          <li key={application.id} className="dashboard-list-item">
                            <div>
                              <strong>{getProductTitle(cabinet, application.product)}</strong>
                              <span>{formatShortDate(application.created_at)}</span>
                            </div>
                            <div className="dashboard-list-meta">
                              <strong>{formatRub(application.limit_rub ?? application.loan_amount_rub)}</strong>
                              <span>{getApplicationStatus(application.status, application.decision)}</span>
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="dashboard-empty">Заявок пока нет</p>
                    )}
                  </section>

                  <section className="dashboard-section" aria-labelledby="credits-title">
                    <div className="dashboard-section-heading">
                      <h2 id="credits-title">Мои кредиты</h2>
                      <span>{cabinet.credits.length}</span>
                    </div>
                    {cabinet.credits.length ? (
                      <ul className="dashboard-list">
                        {cabinet.credits.slice(0, 3).map((credit) => (
                          <li key={credit.id} className="dashboard-list-item">
                            <div>
                              <strong>{getProductTitle(cabinet, credit.product)}</strong>
                              <span>{credit.status === 'active' ? 'Активен' : credit.status}</span>
                            </div>
                            <div className="dashboard-list-meta">
                              <strong>{formatRub(credit.amount_rub)}</strong>
                              <span>Платёж {formatRub(credit.monthly_payment_rub)} в месяц</span>
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="dashboard-empty">Кредитов пока нет</p>
                    )}
                  </section>
                  <button className="logout-button" type="button" onClick={handleLogout}>Выйти</button>
                </section>
              ) : (
                <section className="product-choice" aria-labelledby="auth-title">
                  <button
                    className="back-button"
                    type="button"
                    onClick={() => setCabinetScreen('dashboard')}
                  >
                    ← Личный кабинет
                  </button>
                  <p className="eyebrow">Подбор кредита</p>
                  <h1 id="auth-title">Для чего нужен кредит?</h1>
                  <p className="intro">Выберите задачу, чтобы начать с подходящего продукта</p>
                  <div className="product-choice-list">
                    {cabinet.products.map((product) => (
                      <button
                        className={`product-choice-card${selectedProduct === product.code ? ' product-choice-card--selected' : ''}`}
                        type="button"
                        key={product.code}
                        aria-pressed={selectedProduct === product.code}
                        onClick={() => setSelectedProduct(product.code)}
                      >
                        <span className="product-choice-check" aria-hidden="true">
                          {selectedProduct === product.code ? '✓' : ''}
                        </span>
                        <span className="product-choice-copy">
                          <strong>{getProductTitle(cabinet, product.code)}</strong>
                          <span>{getProductDescription(product.code)}</span>
                        </span>
                      </button>
                    ))}
                  </div>
                  {selectedProduct && (
                    <p className="selected-product" role="status">
                      Вы выбрали: {getProductTitle(cabinet, selectedProduct)}
                    </p>
                  )}
                </section>
              )
            ) : step === 'phone' ? (
              <>
                <p className="eyebrow">Личный кабинет</p>
                <h1 id="auth-title">Вход по номеру телефона</h1>
                <p className="intro">Введите номер телефона, чтобы войти в кабинет</p>

                <form className="phone-form" onSubmit={handlePhoneSubmit} noValidate>
                  <label className="phone-label" htmlFor="phone">Номер телефона</label>
                  <div className={`phone-control${phone.length > 2 && !isComplete ? ' phone-control--invalid' : ''}`}>
                    <span className="phone-country" aria-hidden="true">🇷🇺 <span>+7</span></span>
                    <input
                      id="phone"
                      name="phone"
                      type="tel"
                      inputMode="tel"
                      autoComplete="tel-national"
                      placeholder="(999) 123-45-67"
                      value={phone.slice(2).trimStart()}
                      onChange={(event) => handlePhoneChange(event.target.value)}
                      aria-describedby="phone-hint phone-error"
                      aria-invalid={phone.length > 2 && !isComplete}
                      disabled={isSubmitting}
                    />
                    {isComplete && <span className="phone-check" aria-label="Номер введён полностью">✓</span>}
                  </div>
                  <p className="field-hint" id="phone-hint">Российский номер телефона</p>
                  <p className="field-error" id="phone-error" aria-live="polite">
                    {phone.length > 2 && !isComplete ? 'Проверьте номер телефона' : ''}
                  </p>
                  <button className="submit-button" type="submit" disabled={!isComplete || isSubmitting}>
                    {isSubmitting ? 'Входим…' : 'Продолжить'} <span aria-hidden="true">→</span>
                  </button>
                  {error && <p className="request-error" role="alert">{error}</p>}
                </form>
              </>
            ) : (
              <>
                <p className="eyebrow">Подтверждение номера</p>
                <h1 id="auth-title">Введите код из СМС</h1>
                <p className="intro">Код для номера {phone}</p>

                <form className="phone-form" onSubmit={handleCodeSubmit} noValidate>
                  <label className="phone-label" htmlFor="sms-code">Код подтверждения</label>
                  <input
                    className="sms-code-input"
                    id="sms-code"
                    name="sms-code"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]*"
                    maxLength={4}
                    placeholder="····"
                    value={code}
                    onChange={(event) => {
                      setCode(event.target.value.replace(/\D/g, '').slice(0, 4));
                      setError('');
                    }}
                    aria-describedby={error ? 'code-hint code-error' : 'code-hint'}
                    aria-invalid={Boolean(error)}
                    disabled={isSubmitting}
                  />
                  <p className="code-hint" id="code-hint">Для демонстрации введите 0000</p>
                  {error && <p className="request-error" id="code-error" role="alert">{error}</p>}
                  <button className="submit-button" type="submit" disabled={code.length !== 4 || isSubmitting}>
                    {isSubmitting ? 'Входим…' : 'Подтвердить'} <span aria-hidden="true">→</span>
                  </button>
                  <button
                    className="change-phone-button"
                    type="button"
                    onClick={() => {
                      setStep('phone');
                      setCode('');
                      setError('');
                    }}
                  >
                    Изменить номер
                  </button>
                </form>
              </>
            )}

          </div>

          <aside className="brand-note" aria-label="Альфа-Бизнес">
            <div className="brand-note__topline" />
            <p className="brand-note__label">АЛЬФА-БИЗНЕС</p>
            <p className="brand-note__message">Финансирование<br />для бизнеса</p>
            <div className="brand-note__baseline" aria-hidden="true" />
            <span className="brand-note__index" aria-hidden="true">А</span>
          </aside>
        </div>
      </section>
      <div className="red-edge" aria-hidden="true" />
    </main>
  );
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Не удалось выполнить вход. Попробуйте ещё раз.';
}

function getProductTitle(cabinet: Cabinet, code: string): string {
  return cabinet.products.find((product) => product.code === code)?.title ?? code;
}

function getProductDescription(code: string): string {
  if (code === 'working_capital') return 'Пополнить оборот действующего бизнеса';
  if (code === 'startup') return 'Запустить новое дело по бизнес-плану';
  return 'Посмотреть условия продукта';
}

function getApplicationStatus(status: string, decision: string | null): string {
  if (status === 'draft') return 'Черновик';
  if (decision === 'approve') return 'Одобрена';
  if (decision === 'reduced') return 'Одобрена на меньшую сумму';
  if (decision === 'reject') return 'Отказ';
  if (decision === 'unknown') return 'Нужно уточнить данные';
  return status;
}

function formatRub(value: number | null): string {
  if (value === null) return '—';
  return `${new Intl.NumberFormat('ru-RU').format(value)} ₽`;
}

function formatShortDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).format(date);
}

export default App;
