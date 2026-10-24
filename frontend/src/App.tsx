import { useState, type FormEvent } from 'react';
import { formatRussianPhone, isRussianPhoneComplete, normalizeRussianPhone } from '@alfa-hack/core-auth';

function App() {
  const [phone, setPhone] = useState('+7');
  const [submitted, setSubmitted] = useState(false);

  const isComplete = isRussianPhoneComplete(phone);
  const normalizedPhone = normalizeRussianPhone(phone);

  function handlePhoneChange(value: string) {
    setPhone(formatRussianPhone(value));
    setSubmitted(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!normalizedPhone) return;
    setSubmitted(true);
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
            <p className="eyebrow">Личный кабинет</p>
            <h1 id="auth-title">Вход по номеру телефона</h1>
            <p className="intro">Введите номер, который вы указывали при оформлении заявки</p>

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
                />
                {isComplete && <span className="phone-check" aria-label="Номер введён полностью">✓</span>}
              </div>
              <p className="field-hint" id="phone-hint">Российский номер телефона</p>
              <p className="field-error" id="phone-error" aria-live="polite">
                {phone.length > 2 && !isComplete ? 'Проверьте номер телефона' : ''}
              </p>
              <button className="submit-button" type="submit" disabled={!isComplete}>
                Продолжить <span aria-hidden="true">→</span>
              </button>
              {submitted && (
                <p className="submit-message" role="status">
                  Номер введён: +{normalizedPhone}
                </p>
              )}
            </form>

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

export default App;
