export type ApiErrorBody = {
  error?: string;
};

export type CompanyProfile = {
  inn?: string | null;
  ogrn?: string | null;
  name?: string | null;
  short_name?: string | null;
  status?: string | null;
  registration_date?: string | null;
  okved?: string | null;
  monthly_revenue_rub?: number | null;
  credit_rating?: number | null;
  rating_grade?: string | null;
  preapproved_limit_rub?: number | null;
};

export type UserProfile = {
  id: string;
  phone: string;
  full_name?: string | null;
  role?: string | null;
  email?: string | null;
  company?: CompanyProfile | null;
};

export type DemoProfile = {
  phone: string;
  full_name: string;
  role: string;
  company_name: string;
};

export type AuthSession = {
  token: string;
  user: UserProfile;
};

export type Product = {
  code: string;
  title: string;
  annual_rate_pct: number;
  min_amount_rub: number;
  max_amount_rub: number;
  min_term_months: number;
  max_term_months: number;
};

export type ProductDetail = Product & {
  fields: string[];
};

export type AdvisorAnswers = {
  goal: string | null;
  amount_rub: number | null;
  term_months: number | null;
  purpose: string | null;
  profitability_rub: number | null;
  business_plan: string | null;
  phone: string | null;
};

export type AdvisorSaved = {
  id: string;
  product: string;
  status: string;
};

export type AdvisorChoice = {
  id: string;
  label: string;
};

export type AdvisorHistoryLine = {
  role: 'user' | 'assistant';
  text: string;
};

export type AdvisorTurn = {
  goal?: string | null;
  amount_rub?: number | null;
  term_months?: number | null;
  purpose?: string | null;
  profitability_rub?: number | null;
  business_plan?: string | null;
  phone?: string | null;
  text?: string;
  history?: AdvisorHistoryLine[];
};

export type AdvisorReply = {
  reply: string;
  voice: 'qwen' | 'formula';
  brief: Record<string, unknown>;
  answers: AdvisorAnswers;
  choices: AdvisorChoice[];
  product: Product | null;
  done: boolean;
  token: string | null;
  saved: AdvisorSaved | null;
};

export type ScoringReport = {
  flow_basis: string;
  risks: string[];
  quote: string;
};

export type ApplicationCard = {
  id: string;
  status: string;
  product: string;
  phone: string;
  purpose: string;
  loan_amount_rub: number;
  loan_term_months: number;
  profitability_rub: number | null;
  profitability_confirmed: boolean;
  collateral: boolean;
  own_funds_rub: number | null;
  credit_rating: number | null;
  created_at: string;
  pipeline: string | null;
  fallback: boolean;
  monthly_payment_rub: number | null;
  flow_rub: number | null;
  limit_rub: number | null;
  decision: 'approve' | 'reduced' | 'reject' | 'unknown' | null;
  credit_id: string | null;
};

export type ApplicationDetail = ApplicationCard & {
  business_plan: string;
  report: ScoringReport | null;
};

export type CreditCard = {
  id: string;
  application_id: string;
  product: string;
  status: string;
  amount_rub: number;
  loan_term_months: number;
  monthly_payment_rub: number;
  purpose?: string | null;
  created_at: string;
};

export type CreditDetail = CreditCard & {
  schedule: Array<{
    month: number;
    payment_rub: number;
  }>;
};

export type ApplicationCreateRequest = {
  product: string;
  loan_amount_rub: number;
  loan_term_months: number;
  phone?: string | null;
  purpose?: string | null;
  profitability_rub?: number | null;
  profitability_confirmed?: boolean | null;
  collateral?: boolean | null;
  business_plan?: string | null;
  own_funds_rub?: number | null;
  credit_rating?: number | null;
};

export type ApplicationConfirmRequest = {
  phone: string;
};

export type LinkApplicationResponse = {
  token: string;
  user: UserProfile;
  application: ApplicationDetail;
};

export type Cabinet = {
  user: UserProfile;
  products: Product[];
  applications: ApplicationCard[];
  credits: CreditCard[];
};

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export function isLinkApplication(
  value: ApplicationDetail | LinkApplicationResponse,
): value is LinkApplicationResponse {
  return 'token' in value && 'application' in value;
}

function readApiError(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null && 'error' in payload) {
    const error = (payload as ApiErrorBody).error;
    if (typeof error === 'string' && error.trim()) return error;
  }
  return fallback;
}

function apiBase(explicit?: string): string {
  if (explicit) return explicit.replace(/\/$/, '');
  const configured = import.meta.env?.VITE_API_BASE_URL;
  if (typeof configured === 'string' && configured.trim()) return configured.replace(/\/$/, '');
  return '/api';
}

export function createApiClient(baseUrl?: string) {
  const base = apiBase(baseUrl);

  async function request<T>(
    path: string,
    options: { method?: 'GET' | 'POST' | 'DELETE'; token?: string; body?: unknown } = {},
  ): Promise<T> {
    const headers = new Headers();
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    if (options.token) headers.set('Authorization', `Bearer ${options.token}`);

    let response: Response;
    try {
      response = await fetch(`${base}${path}`, {
        method: options.method ?? 'GET',
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      });
    } catch {
      throw new ApiError('Не удалось связаться с сервером. Попробуйте ещё раз.', 0);
    }

    if (response.status === 204) return undefined as T;

    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      const fallback = response.status === 401
        ? 'Сессия завершилась. Войдите ещё раз.'
        : response.status >= 500
          ? 'Сервис временно недоступен. Попробуйте позже.'
          : 'Не удалось выполнить запрос.';
      throw new ApiError(readApiError(payload, fallback), response.status);
    }

    return payload as T;
  }

  return {
    async getDemoProfiles() {
      const response = await request<{ profiles: DemoProfile[] }>('/demo-profiles');
      return response.profiles;
    },
    createSession(phone: string) {
      return request<AuthSession>('/auth/session', {
        method: 'POST',
        body: { phone },
      });
    },
    deleteSession(token: string) {
      return request<void>('/auth/session', { method: 'DELETE', token });
    },
    getCurrentUser(token: string) {
      return request<UserProfile>('/me', { token });
    },
    async getProducts() {
      const response = await request<{ products: Product[] }>('/products');
      return response.products;
    },
    getProductDetail(code: string) {
      return request<ProductDetail>(`/products/${encodeURIComponent(code)}`);
    },
    advise(turn: AdvisorTurn) {
      return request<AdvisorReply>('/advisor', {
        method: 'POST',
        body: {
          goal: turn.goal ?? null,
          amount_rub: turn.amount_rub ?? null,
          term_months: turn.term_months ?? null,
          purpose: turn.purpose ?? null,
          profitability_rub: turn.profitability_rub ?? null,
          business_plan: turn.business_plan ?? null,
          phone: turn.phone ?? null,
          text: turn.text ?? '',
          history: turn.history ?? [],
        },
      });
    },
    async getApplications(token: string) {
      const response = await request<{ applications: ApplicationCard[] }>('/applications', { token });
      return response.applications;
    },
    getApplicationDetail(token: string, applicationId: string) {
      return request<ApplicationDetail>(`/applications/${encodeURIComponent(applicationId)}`, { token });
    },
    createApplication(token: string | null, application: ApplicationCreateRequest) {
      return request<ApplicationDetail | LinkApplicationResponse>('/applications', {
        method: 'POST',
        token: token ?? undefined,
        body: application,
      });
    },
    confirmApplication(token: string, applicationId: string, confirmation: ApplicationConfirmRequest) {
      return request<ApplicationDetail>(`/applications/${encodeURIComponent(applicationId)}/confirm`, {
        method: 'POST',
        token,
        body: confirmation,
      });
    },
    async getCredits(token: string) {
      const response = await request<{ credits: CreditCard[] }>('/credits', { token });
      return response.credits;
    },
    getCreditDetail(token: string, creditId: string) {
      return request<CreditDetail>(`/credits/${encodeURIComponent(creditId)}`, { token });
    },
    getCabinet(token: string) {
      return request<Cabinet>('/cabinet', { token });
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
