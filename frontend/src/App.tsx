import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, createApiClient, type Cabinet } from '@alfa-hack/core-api';
import { formatRussianPhone, isRussianPhoneComplete, normalizeRussianPhone } from '@alfa-hack/core-auth';

const TOKEN_KEY = 'alfa-hack:token';
const api = createApiClient();

function App() {
  const [phone, setPhone] = useState('+7');
  const [cabinet, setCabinet] = useState<Cabinet | null>(null);
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRestoring, setIsRestoring] = useState(() => Boolean(sessionStorage.getItem(TOKEN_KEY)));

  const isComplete = isRussianPhoneComplete(phone);
  const normalizedPhone = normalizeRussianPhone(phone);

  useEffect(() => {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return;

    api.getCabinet(token)
      .then(setCabinet)
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

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!normalizedPhone || isSubmitting) return;

    setError('');
    setIsSubmitting(true);
    try {
      const session = await api.createSession(normalizedPhone);
      if (!session.token) throw new Error('Сервер не вернул токен входа.');

      sessionStorage.setItem(TOKEN_KEY, session.token);
      const nextCabinet = await api.getCabinet(session.token);
      setCabinet(nextCabinet);
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
    setError('');

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

        <div className="auth-content">
          <div className="auth-copy">
            {cabinet ? (
              <div className="cabinet-view">
                <p className="eyebrow">Личный кабинет</p>
                <h1 id="auth-title">Вы вошли</h1>
                <p className="intro">{cabinet.user.phone}</p>
                <h2 className="products-title">Доступные продукты</h2>
                <ul className="product-list">
                  {cabinet.products.map((product) => (
                    <li key={product.code}>
                      {product.title}
                    </li>
                  ))}
                </ul>
                <button className="logout-button" type="button" onClick={handleLogout}>Выйти</button>
              </div>
            ) : (
              <>
                <p className="eyebrow">Личный кабинет</p>
                <h1 id="auth-title">Вход по номеру телефона</h1>
                <p className="intro">Введите номер телефона, чтобы войти в кабинет</p>

                <form className="phone-form" onSubmit={handleSubmit} noValidate>
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

export default App;
