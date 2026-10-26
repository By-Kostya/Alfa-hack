import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { AdvisorAnswers, AdvisorChoice, ApiClient, Product } from '@alfa-hack/core-api';
import { formatCompactRub } from '@alfa-hack/core-credit';

type ChatLine = { role: 'user' | 'assistant'; text: string };

const DRAFT_KEY = 'alfa-hack:advisor-draft';
const EMPTY: AdvisorAnswers = {
  goal: null,
  amount_rub: null,
  term_months: null,
  purpose: null,
  profitability_rub: null,
  business_plan: null,
  phone: null,
};

function readDraft(): AdvisorAnswers {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return EMPTY;
    return { ...EMPTY, ...JSON.parse(raw) as Partial<AdvisorAnswers> };
  } catch {
    return EMPTY;
  }
}

function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Не удалось продолжить разговор.';
}

export default function AdvisorScreen({
  api,
  onBack,
  onSession,
  onCabinet,
}: {
  api: ApiClient;
  onBack: () => void;
  onSession: (token: string) => Promise<void>;
  onCabinet: () => void;
}) {
  const [answers, setAnswers] = useState<AdvisorAnswers>(readDraft);
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [choices, setChoices] = useState<AdvisorChoice[]>([]);
  const [product, setProduct] = useState<Product | null>(null);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState('');
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const started = useRef(false);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [lines, choices, product, isSending, saved]);

  async function ask(text: string, base = answers, showUser = true, shown = text) {
    const trimmed = text.trim();
    if (isSending || (showUser && !trimmed)) return;
    setIsSending(true);
    setError('');
    if (showUser) setLines((current) => [...current, { role: 'user', text: shown.trim() }]);
    setDraft('');
    try {
      const turn = await api.advise({ ...base, text: trimmed });
      setAnswers(turn.answers);
      setChoices(turn.choices);
      setProduct(turn.product);
      setLines((current) => [...current, { role: 'assistant', text: turn.reply }]);
      if (turn.token) {
        sessionStorage.removeItem(DRAFT_KEY);
        await onSession(turn.token);
        setSaved(true);
      } else {
        sessionStorage.setItem(DRAFT_KEY, JSON.stringify(turn.answers));
      }
    } catch (requestError) {
      setError(errorText(requestError));
    } finally {
      setIsSending(false);
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void ask('', readDraft(), false);
  }, []);

  function restart() {
    sessionStorage.removeItem(DRAFT_KEY);
    setAnswers(EMPTY);
    setLines([]);
    setChoices([]);
    setProduct(null);
    setSaved(false);
    setDraft('');
    void ask('', EMPTY, false);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(draft);
  }

  return (
    <main className="advisor-screen">
      <header className="advisor-topbar">
        <button className="advisor-back" type="button" onClick={onBack}>На старт</button>
        <strong>Подбор</strong>
        <button className="advisor-restart" type="button" onClick={restart} disabled={isSending}>Сначала</button>
      </header>
      <div className="advisor-thread" ref={threadRef} aria-live="polite">
        {lines.map((line, index) => (
          <p className={`advisor-line advisor-line--${line.role}`} key={`${line.role}-${index}`}>{line.text}</p>
        ))}
        {isSending && <p className="advisor-line advisor-line--assistant advisor-line--pending">Секунду…</p>}
        {error && <p className="request-error" role="alert">{error}</p>}
      </div>
      {product && (
        <section className="advisor-offer">
          <p>{product.title}</p>
          <strong>{product.annual_rate_pct}%</strong>
          <span>до {formatCompactRub(product.max_amount_rub)} · {product.min_term_months}–{product.max_term_months} мес.</span>
          {saved && (
            <button className="submit-button" type="button" onClick={onCabinet}>Открыть кабинет</button>
          )}
        </section>
      )}
      {choices.length > 0 && !saved && (
        <div className="advisor-choices">
          {choices.map((choice) => (
            <button key={choice.id} type="button" disabled={isSending} onClick={() => void ask(choice.id, answers, true, choice.label)}>
              {choice.label}
            </button>
          ))}
        </div>
      )}
      {!saved && (
        <form className="advisor-form" onSubmit={submit}>
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Напишите сообщение"
            aria-label="Сообщение"
            disabled={isSending}
          />
          <button type="submit" disabled={isSending || !draft.trim()}>Отправить</button>
        </form>
      )}
    </main>
  );
}
