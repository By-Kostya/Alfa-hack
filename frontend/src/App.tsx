import { useEffect, useRef, useState, type FormEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';
import {
  ApiError,
  createApiClient,
  type ApplicationDetail,
  type Cabinet,
  type CompanyProfile,
  type CreditDetail,
  type ProductDetail,
  type UserProfile,
} from '@alfa-hack/core-api';
import { formatRussianPhone, isRussianPhoneComplete, normalizeRussianPhone } from '@alfa-hack/core-auth';

const TOKEN_KEY = 'alfa-hack:token';
const PENDING_PHONE_KEY = 'alfa-hack:pending-phone';
const WELCOME_DURATION_MS = 3000;
const api = createApiClient();
const ROUTES = {
  login: '/',
  code: '/verify',
  welcome: '/welcome',
  dashboard: '/dashboard',
  productChoice: '/dashboard/credit',
} as const;
type AppRoute = typeof ROUTES[keyof typeof ROUTES];

function normalizeRoute(path: string): AppRoute {
  if (Object.values(ROUTES).includes(path as AppRoute)) return path as AppRoute;
  if (path === '/login') return ROUTES.login;
  return ROUTES.login;
}
type CabinetDetail =
  | { kind: 'application'; value: ApplicationDetail }
  | { kind: 'credit'; value: CreditDetail };

function App() {
  const [route, setRoute] = useState<AppRoute>(() => normalizeRoute(window.location.pathname));
  const [phone, setPhone] = useState(() => formatRussianPhone(sessionStorage.getItem(PENDING_PHONE_KEY) || '+7'));
  const [code, setCode] = useState('');
  const [cabinet, setCabinet] = useState<Cabinet | null>(null);
  const [activeProductIndex, setActiveProductIndex] = useState(0);
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null);
  const [selectedProductDetail, setSelectedProductDetail] = useState<ProductDetail | null>(null);
  const [isLoadingProductDetail, setIsLoadingProductDetail] = useState(false);
  const [productDetailError, setProductDetailError] = useState('');
  const [smsMessage, setSmsMessage] = useState('');
  const [smsCodeHint, setSmsCodeHint] = useState('0000');
  const [cabinetDetail, setCabinetDetail] = useState<CabinetDetail | null>(null);
  const [isLoadingCabinetDetail, setIsLoadingCabinetDetail] = useState(false);
  const [cabinetDetailError, setCabinetDetailError] = useState('');
  const [error, setError] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRestoring, setIsRestoring] = useState(() => Boolean(sessionStorage.getItem(TOKEN_KEY)));
  const cabinetDetailRequestId = useRef(0);
  const productCarouselRef = useRef<HTMLDivElement | null>(null);
  const productSlideRefs = useRef<Array<HTMLElement | null>>([]);
  const productDragRef = useRef<{ pointerId: number; startX: number; startScrollLeft: number; didDrag: boolean } | null>(null);
  const suppressCarouselClickRef = useRef(false);

  function navigateTo(nextRoute: AppRoute, replace = false) {
    const normalizedRoute = normalizeRoute(nextRoute);
    if (window.location.pathname !== normalizedRoute) {
      const method = replace ? 'replaceState' : 'pushState';
      window.history[method]({}, '', normalizedRoute);
    }
    setRoute(normalizedRoute);
  }

  const isComplete = isRussianPhoneComplete(phone);
  const normalizedPhone = normalizeRussianPhone(phone);

  function goToProduct(index: number) {
    if (!cabinet?.products.length) return;
    const nextIndex = Math.max(0, Math.min(index, cabinet.products.length - 1));
    setActiveProductIndex(nextIndex);
    const viewport = productCarouselRef.current;
    const slide = productSlideRefs.current[nextIndex];
    if (!viewport || !slide) return;
    viewport.scrollTo({
      left: slide.offsetLeft - (viewport.clientWidth - slide.clientWidth) / 2,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    });
  }

  function syncActiveProductFromScroll(): number {
    const viewport = productCarouselRef.current;
    if (!viewport || !cabinet?.products.length) return 0;
    const viewportCenter = viewport.scrollLeft + viewport.clientWidth / 2;
    let closestIndex = 0;
    let closestDistance = Number.POSITIVE_INFINITY;
    productSlideRefs.current.forEach((slide, index) => {
      if (!slide) return;
      const slideCenter = slide.offsetLeft + slide.clientWidth / 2;
      const distance = Math.abs(viewportCenter - slideCenter);
      const progress = Math.max(0, 1 - distance / (viewport.clientWidth * 0.58));
      slide.style.transform = `scale(${(0.91 + progress * 0.09).toFixed(3)})`;
      slide.style.opacity = `${(0.64 + progress * 0.36).toFixed(3)}`;
      if (distance < closestDistance) {
        closestDistance = distance;
        closestIndex = index;
      }
    });
    setActiveProductIndex((currentIndex) => currentIndex === closestIndex ? currentIndex : closestIndex);
    return closestIndex;
  }

  function handleCarouselPointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.pointerType !== 'mouse' || event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest('button, a, input')) return;
    productDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startScrollLeft: event.currentTarget.scrollLeft,
      didDrag: false,
    };
  }

  function handleCarouselPointerMove(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = productDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const delta = event.clientX - drag.startX;
    if (!drag.didDrag && Math.abs(delta) < 6) return;
    if (!drag.didDrag) {
      drag.didDrag = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      event.currentTarget.classList.add('product-carousel-viewport--dragging');
    }
    event.preventDefault();
    event.currentTarget.scrollLeft = drag.startScrollLeft - delta;
  }

  function handleCarouselPointerUp(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = productDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    productDragRef.current = null;
    event.currentTarget.classList.remove('product-carousel-viewport--dragging');
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (drag.didDrag) {
      suppressCarouselClickRef.current = true;
      goToProduct(syncActiveProductFromScroll());
      window.setTimeout(() => { suppressCarouselClickRef.current = false; }, 0);
    }
  }

  function handleCarouselClickCapture(event: ReactMouseEvent<HTMLDivElement>) {
    if (!suppressCarouselClickRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    suppressCarouselClickRef.current = false;
  }

  useEffect(() => {
    const handlePopState = () => setRoute(normalizeRoute(window.location.pathname));
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    const token = sessionStorage.getItem(TOKEN_KEY);
    const initialRoute = normalizeRoute(window.location.pathname);
    if (!token) return;

    api.getDashboardData(token)
      .then((nextCabinet) => {
        setCabinet(nextCabinet);
        if (initialRoute === ROUTES.dashboard || initialRoute === ROUTES.productChoice) {
          setRoute(initialRoute);
        } else {
          navigateTo(ROUTES.welcome, true);
        }
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof ApiError && requestError.status === 401) {
          sessionStorage.removeItem(TOKEN_KEY);
        }
        setError(getErrorMessage(requestError));
      })
      .finally(() => setIsRestoring(false));
  }, []);

  useEffect(() => {
    if (isRestoring) return;
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (route === ROUTES.code) {
      if (!sessionStorage.getItem(PENDING_PHONE_KEY)) navigateTo(ROUTES.login, true);
      return;
    }
    if ((route === ROUTES.welcome || route === ROUTES.dashboard || route === ROUTES.productChoice) && (!token || !cabinet)) {
      navigateTo(ROUTES.login, true);
    }
  }, [route, cabinet, isRestoring]);

  useEffect(() => {
    const titles: Record<AppRoute, string> = {
      [ROUTES.login]: 'Вход — Альфа-Бизнес',
      [ROUTES.code]: 'Подтверждение номера — Альфа-Бизнес',
      [ROUTES.welcome]: 'Добро пожаловать — Альфа-Бизнес',
      [ROUTES.dashboard]: 'Личный кабинет — Альфа-Бизнес',
      [ROUTES.productChoice]: 'Подбор кредита — Альфа-Бизнес',
    };
    document.title = titles[route];
  }, [route]);

  useEffect(() => {
    const viewport = productCarouselRef.current;
    if (!viewport || route !== ROUTES.dashboard) return;

    const updateSlideWidth = () => {
      const availablePeek = Math.max(0, (viewport.clientWidth - 220) / 2);
      const peek = cabinet && cabinet.products.length > 1
        ? Math.min(104, Math.max(24, viewport.clientWidth * 0.14), availablePeek)
        : 0;
      viewport.style.setProperty('--carousel-peek', `${peek}px`);
      viewport.style.setProperty('--carousel-slide-width', `${Math.max(220, viewport.clientWidth - peek * 2)}px`);
      syncActiveProductFromScroll();
    };
    const observer = new ResizeObserver(updateSlideWidth);
    observer.observe(viewport);
    updateSlideWidth();
    return () => observer.disconnect();
  }, [route, cabinet?.products.length]);

  useEffect(() => {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token || route !== ROUTES.welcome) return;
    const timer = window.setTimeout(() => navigateTo(ROUTES.dashboard, true), WELCOME_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [route]);

  useEffect(() => {
    if (!selectedProduct) {
      setSelectedProductDetail(null);
      setProductDetailError('');
      setIsLoadingProductDetail(false);
      return;
    }

    let isCurrentRequest = true;
    setSelectedProductDetail(null);
    setProductDetailError('');
    setIsLoadingProductDetail(true);
    api.getProductDetail(selectedProduct)
      .then((detail) => {
        if (isCurrentRequest) setSelectedProductDetail(detail);
      })
      .catch((requestError: unknown) => {
        if (isCurrentRequest) setProductDetailError(getErrorMessage(requestError));
      })
      .finally(() => {
        if (isCurrentRequest) setIsLoadingProductDetail(false);
      });

    return () => { isCurrentRequest = false; };
  }, [selectedProduct]);

  function handlePhoneChange(value: string) {
    setPhone(formatRussianPhone(value));
    setError('');
    setSmsMessage('');
    setSmsCodeHint('0000');
  }

  async function handlePhoneSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!normalizedPhone || isSubmitting) return;

    setError('');
    setSmsMessage('');
    setIsSubmitting(true);
    try {
      const response = await api.sendSmsCode(normalizedPhone);
      setSmsMessage(response.message);
      setSmsCodeHint(response.code || '0000');
      setCode('');
      sessionStorage.setItem(PENDING_PHONE_KEY, normalizedPhone);
      navigateTo(ROUTES.code);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCodeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!normalizedPhone || isSubmitting) return;

    setError('');
    setIsSubmitting(true);
    try {
      const session = await api.createSession(normalizedPhone, code);
      if (!session.token) throw new Error('Сервер не вернул токен входа.');

      sessionStorage.setItem(TOKEN_KEY, session.token);
      sessionStorage.removeItem(PENDING_PHONE_KEY);
      const nextCabinet = await api.getDashboardData(session.token);
      setCabinet(nextCabinet);
      navigateTo(ROUTES.welcome);
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
    sessionStorage.removeItem(PENDING_PHONE_KEY);
    setCabinet(null);
    setSelectedProduct(null);
    setError('');
    setPhone('+7');
    setCode('');
    navigateTo(ROUTES.login, true);
    closeCabinetDetail();

    if (!token) return;
    try {
      await api.deleteSession(token);
    } catch {
      // The local session is cleared even when the server cannot be reached.
    }
  }

  function closeCabinetDetail() {
    cabinetDetailRequestId.current += 1;
    setCabinetDetail(null);
    setCabinetDetailError('');
    setIsLoadingCabinetDetail(false);
  }

  async function showApplicationDetail(applicationId: string) {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return;
    const requestId = ++cabinetDetailRequestId.current;
    setCabinetDetail(null);
    setCabinetDetailError('');
    setIsLoadingCabinetDetail(true);
    try {
      const value = await api.getApplicationDetail(token, applicationId);
      if (requestId === cabinetDetailRequestId.current) setCabinetDetail({ kind: 'application', value });
    } catch (requestError) {
      if (requestId === cabinetDetailRequestId.current) setCabinetDetailError(getErrorMessage(requestError));
    } finally {
      if (requestId === cabinetDetailRequestId.current) setIsLoadingCabinetDetail(false);
    }
  }

  async function showCreditDetail(creditId: string) {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return;
    const requestId = ++cabinetDetailRequestId.current;
    setCabinetDetail(null);
    setCabinetDetailError('');
    setIsLoadingCabinetDetail(true);
    try {
      const value = await api.getCreditDetail(token, creditId);
      if (requestId === cabinetDetailRequestId.current) setCabinetDetail({ kind: 'credit', value });
    } catch (requestError) {
      if (requestId === cabinetDetailRequestId.current) setCabinetDetailError(getErrorMessage(requestError));
    } finally {
      if (requestId === cabinetDetailRequestId.current) setIsLoadingCabinetDetail(false);
    }
  }

  if (isRestoring) {
    return <main className="loading-screen" role="status">Загружаем личный кабинет…</main>;
  }

  if (cabinet && route === ROUTES.welcome) {
    return (
      <WelcomeScreen
        user={cabinet.user}
        onContinue={() => navigateTo(ROUTES.dashboard)}
      />
    );
  }

  return (
    <main className="auth-layout">
      <section className="auth-panel" aria-labelledby="auth-title">
        <header className="topbar">
          <div className="wordmark" aria-label="Альфа-Бизнес">
            <span className="wordmark__alpha">Альфа</span><span className="wordmark__bank">Бизнес</span>
          </div>
          {cabinet && (
            <details className="topbar-account">
              <summary className="topbar-account-trigger" aria-label={`Профиль пользователя ${cabinet.user.full_name || cabinet.user.phone}`}>
                <span className="topbar-account-avatar" aria-hidden="true">{getUserInitials(cabinet.user.full_name)}</span>
                <span className="topbar-account-copy">
                  <span>{cabinet.user.role || 'Личный кабинет'}</span>
                  <strong>{getShortUserName(cabinet.user.full_name) || cabinet.user.phone}</strong>
                  <small>{cabinet.user.email || cabinet.user.phone}</small>
                </span>
                <span className="topbar-account-caret" aria-hidden="true">⌄</span>
              </summary>
              <div className="topbar-account-panel">
                <p>ПРОФИЛЬ</p>
                <strong>{cabinet.user.full_name || cabinet.user.phone}</strong>
                <dl>
                  {cabinet.user.role && <div><dt>Должность</dt><dd>{cabinet.user.role}</dd></div>}
                  {cabinet.user.email && <div><dt>Электронная почта</dt><dd>{cabinet.user.email}</dd></div>}
                  <div><dt>Телефон</dt><dd>{cabinet.user.phone}</dd></div>
                </dl>
              </div>
            </details>
          )}
        </header>

        <div className={`auth-content${cabinet ? ' auth-content--dashboard' : ''}`}>
          <div className={`auth-copy${cabinet ? ' auth-copy--dashboard' : ''}`}>
            {cabinet ? (
              route === ROUTES.dashboard ? (
                <section className="dashboard" aria-labelledby="auth-title">
                  <section className="product-showcase" aria-label="Кредитные продукты">
                    <div className="product-showcase-heading">
                      <p className="product-showcase-kicker"><span /> АЛЬФА-БИЗНЕС · ФИНАНСИРОВАНИЕ</p>
                      <h1 id="auth-title">Продукты для<br />вашего бизнеса</h1>
                    </div>
                    {cabinet.products.length ? (
                      <>
                        <div
                          className="product-carousel-viewport"
                          ref={productCarouselRef}
                          onScroll={syncActiveProductFromScroll}
                          onPointerDown={handleCarouselPointerDown}
                          onPointerMove={handleCarouselPointerMove}
                          onPointerUp={handleCarouselPointerUp}
                          onPointerCancel={handleCarouselPointerUp}
                          onClickCapture={handleCarouselClickCapture}
                          role="region"
                          aria-roledescription="карусель"
                          aria-label="Лента кредитных продуктов"
                          tabIndex={0}
                        >
                          <div className="product-carousel-track">
                            {cabinet.products.map((product, index) => (
                              <article
                                className={`product-slide${index === activeProductIndex ? ' product-slide--active' : ''}`}
                                key={product.code}
                                ref={(element) => { productSlideRefs.current[index] = element; }}
                                role="group"
                                aria-roledescription="слайд"
                                aria-live={index === activeProductIndex ? 'polite' : 'off'}
                                aria-label={`${product.title}, ${index + 1} из ${cabinet.products.length}`}
                                aria-current={index === activeProductIndex ? 'true' : undefined}
                                onClick={(event) => {
                                  if (index !== activeProductIndex && !(event.target instanceof Element && event.target.closest('button'))) {
                                    goToProduct(index);
                                  }
                                }}
                              >
                                <div className="product-slide-copy">
                                  <span className="product-slide-badge">{product.badge}</span>
                                  <h2>{product.title}</h2>
                                  <p>{product.description}</p>
                                  <div className="product-slide-facts">
                                    <div><span>Ставка</span><strong>от {product.rate_pct}%</strong></div>
                                    <div><span>Срок</span><strong>{product.min_term_months}–{product.max_term_months} мес.</strong></div>
                                  </div>
                                  <button
                                    className="product-slide-cta"
                                    type="button"
                                    onClick={() => {
                                      setSelectedProduct(product.code);
                                      navigateTo(ROUTES.productChoice);
                                    }}
                                  >
                                    Выбрать продукт <span aria-hidden="true">→</span>
                                  </button>
                                </div>
                                <div className="product-slide-art" aria-hidden="true">
                                  <span className="product-slide-art-index">{String(index + 1).padStart(2, '0')}</span>
                                  <span className="product-slide-art-letter">А</span>
                                  <div className="product-slide-amount">
                                    <span>ДОСТУПНАЯ СУММА</span>
                                    <strong>до {formatCompactRub(product.max_amount_rub)}</strong>
                                    <i>{formatRub(product.min_amount_rub)} — {formatRub(product.max_amount_rub)}</i>
                                  </div>
                                  <span className="product-slide-art-code">{product.code.replace(/_/g, ' ').toUpperCase()}</span>
                                </div>
                              </article>
                            ))}
                          </div>
                        </div>
                        <div className="product-carousel-footer">
                          <div className="product-carousel-dots" aria-label="Выберите продукт">
                            {cabinet.products.map((item, index) => (
                              <button
                                key={item.code}
                                className={`product-carousel-dot${index === activeProductIndex ? ' product-carousel-dot--active' : ''}`}
                                type="button"
                                aria-label={`Показать продукт: ${item.title}`}
                                aria-current={index === activeProductIndex ? 'true' : undefined}
                                onClick={() => goToProduct(index)}
                              />
                            ))}
                          </div>
                          <div className="product-carousel-arrows">
                            <span>{String(activeProductIndex + 1).padStart(2, '0')} <i>/</i> {String(cabinet.products.length).padStart(2, '0')}</span>
                            <button type="button" aria-label="Предыдущий продукт" disabled={activeProductIndex === 0} onClick={() => goToProduct(activeProductIndex - 1)}>←</button>
                            <button type="button" aria-label="Следующий продукт" disabled={activeProductIndex === cabinet.products.length - 1} onClick={() => goToProduct(activeProductIndex + 1)}>→</button>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="product-showcase-empty">
                        <p>Сейчас не удалось загрузить предложения.</p>
                        <button className="product-help-button" type="button" onClick={() => navigateTo(ROUTES.productChoice)}>Помочь с выбором <span aria-hidden="true">→</span></button>
                      </div>
                    )}
                    {cabinet.products.length > 0 && (
                      <div className="product-help-row">
                        <span><strong>Не знаете, что подойдёт?</strong><small>Ответьте на один вопрос — поможем с выбором</small></span>
                        <button className="product-help-button" type="button" onClick={() => {
                          setSelectedProduct(null);
                          navigateTo(ROUTES.productChoice);
                        }}>
                          Помочь с выбором <span aria-hidden="true">→</span>
                        </button>
                      </div>
                    )}
                  </section>

                  {cabinet.user.company && <CompanyProfileCard company={cabinet.user.company} />}

                  <div className="dashboard-stats" aria-label="Сводка по кабинету">
                    <article className="dashboard-stat">
                      <span>Заявки</span>
                      <strong>{cabinet.applications.length}</strong>
                    </article>
                    <article className="dashboard-stat">
                      <span>Активные кредиты</span>
                      <strong>{cabinet.credits.filter((credit) => credit.status === 'active').length}</strong>
                    </article>
                  </div>

                  <div className="dashboard-columns">
                    <section className="dashboard-section" aria-labelledby="applications-title">
                      <div className="dashboard-section-heading">
                        <h2 id="applications-title">Мои заявки</h2>
                        <span>{cabinet.applications.length}</span>
                      </div>
                      {cabinet.applications.length ? (
                        <ul className="dashboard-list">
                          {cabinet.applications.slice(0, 3).map((application) => (
                            <li key={application.id} className="dashboard-list-item">
                              <button className="dashboard-list-item-button" type="button" onClick={() => void showApplicationDetail(application.id)}>
                                <span>
                                  <strong>{getProductTitle(cabinet, application.product)}</strong>
                                  <span>{formatShortDate(application.created_at)}</span>
                                </span>
                                <span className="dashboard-list-meta">
                                  <strong>{formatRub(application.limit_rub ?? application.loan_amount_rub)}</strong>
                                  <span>{getApplicationStatus(application.status, application.decision)}</span>
                                </span>
                              </button>
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
                              <button className="dashboard-list-item-button" type="button" onClick={() => void showCreditDetail(credit.id)}>
                                <span>
                                  <strong>{getProductTitle(cabinet, credit.product)}</strong>
                                  <span>{credit.status === 'active' ? 'Активен' : credit.status}</span>
                                </span>
                                <span className="dashboard-list-meta">
                                  <strong>{formatRub(credit.amount_rub)}</strong>
                                  <span>Платёж {formatRub(credit.monthly_payment_rub)} в месяц</span>
                                </span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="dashboard-empty">Кредитов пока нет</p>
                      )}
                    </section>
                  </div>
                  <button className="logout-button" type="button" onClick={handleLogout}>Выйти</button>
                  {(cabinetDetail || isLoadingCabinetDetail || cabinetDetailError) && (
                    <div className="detail-backdrop" role="presentation" onClick={closeCabinetDetail}>
                      <section
                        className="detail-dialog"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="detail-title"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <button className="detail-close" type="button" onClick={closeCabinetDetail} aria-label="Закрыть">×</button>
                        {isLoadingCabinetDetail && <p className="detail-loading">Загружаем данные…</p>}
                        {cabinetDetailError && <p className="request-error" role="alert">{cabinetDetailError}</p>}
                        {cabinetDetail?.kind === 'application' && (
                          <>
                            <p className="eyebrow">Заявка</p>
                            <h2 id="detail-title">{getProductTitle(cabinet, cabinetDetail.value.product)}</h2>
                            <dl className="detail-grid">
                              <div><dt>Статус</dt><dd>{getApplicationStatus(cabinetDetail.value.status, cabinetDetail.value.decision)}</dd></div>
                              <div><dt>Сумма</dt><dd>{formatRub(cabinetDetail.value.limit_rub ?? cabinetDetail.value.loan_amount_rub)}</dd></div>
                              <div><dt>Срок</dt><dd>{cabinetDetail.value.loan_term_months} мес.</dd></div>
                              <div><dt>Дата</dt><dd>{formatShortDate(cabinetDetail.value.created_at)}</dd></div>
                              <div className="detail-grid-wide"><dt>Цель</dt><dd>{cabinetDetail.value.purpose || 'Не указана'}</dd></div>
                            </dl>
                          </>
                        )}
                        {cabinetDetail?.kind === 'credit' && (
                          <>
                            <p className="eyebrow">Кредит</p>
                            <h2 id="detail-title">{getProductTitle(cabinet, cabinetDetail.value.product)}</h2>
                            <dl className="detail-grid">
                              <div><dt>Статус</dt><dd>{cabinetDetail.value.status === 'active' ? 'Активен' : cabinetDetail.value.status}</dd></div>
                              <div><dt>Сумма</dt><dd>{formatRub(cabinetDetail.value.amount_rub)}</dd></div>
                              <div><dt>Платёж в месяц</dt><dd>{formatRub(cabinetDetail.value.monthly_payment_rub)}</dd></div>
                              <div><dt>Срок</dt><dd>{cabinetDetail.value.loan_term_months} мес.</dd></div>
                              <div className="detail-grid-wide"><dt>Цель</dt><dd>{cabinetDetail.value.purpose || 'Не указана'}</dd></div>
                            </dl>
                            <div className="detail-schedule">
                              <strong>График платежей</strong>
                              {cabinetDetail.value.schedule.slice(0, 6).map((payment) => (
                                <span key={payment.month}>Месяц {payment.month}<b>{formatRub(payment.payment_rub)}</b></span>
                              ))}
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

function WelcomeScreen({ phone, onContinue }: { phone: string; onContinue: () => void }) {
  return (
    <main className="welcome-screen" aria-labelledby="welcome-title">
      <div className="welcome-shape welcome-shape--one" aria-hidden="true" />
      <div className="welcome-shape welcome-shape--two" aria-hidden="true" />
      <span className="welcome-letter" aria-hidden="true">А</span>

      <header className="welcome-topbar">
        <div className="welcome-wordmark" aria-label="Альфа-Бизнес">
          <span>Альфа</span><b>Бизнес</b>
        </div>
        <span className="welcome-topbar-label">Личный кабинет</span>
      </header>

      <section className="welcome-copy">
        <p className="welcome-kicker"><span /> Рады видеть вас</p>
        <h1 id="welcome-title">Добро<br />пожаловать</h1>
        <div className="welcome-rule" aria-hidden="true" />
        <p className="welcome-caption">Ваш личный кабинет готов</p>
        <div className="welcome-profile">
          <span className="welcome-profile-icon" aria-hidden="true">+7</span>
          <span className="welcome-profile-copy">
            <span>Вход выполнен для номера</span>
            <strong>{phone}</strong>
          </span>
          <span className="welcome-profile-check" aria-label="Вход выполнен">✓</span>
        </div>
        <button className="welcome-continue" type="button" onClick={onContinue}>
          Перейти в кабинет <span aria-hidden="true">→</span>
        </button>
      </section>

      <footer className="welcome-footer">
        <span>Альфа-Бизнес</span>
        <div className="welcome-progress" aria-label="Переход в кабинет через несколько секунд">
          <span />
        </div>
      </footer>
    </main>
  );
}

export default App;
