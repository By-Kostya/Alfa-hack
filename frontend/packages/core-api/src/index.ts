export type ApiErrorBody = {
  error?: string;
};

export type UserProfile = {
  id: string;
  phone: string;
  full_name?: string | null;
  role?: string | null;
  email?: string | null;
  company?: CompanyProfile | null;
  [field: string]: unknown;
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

export type AuthSession = {
  token: string;
  user: UserProfile;
};

export type SmsSendResponse = {
  status: string;
  code: string;
  message: string;
};

export type Product = {
  code: string;
  title: string;
  description: string;
  badge: string;
  rate_pct: number;
  min_amount_rub: number;
  max_amount_rub: number;
  min_term_months: number;
  max_term_months: number;
};

export type ProductDetail = Product & {
  fields: string[];
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
  report: {
    flow_basis: string;
    risks: string[];
    quote: string;
  } | null;
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
  product: 'working_capital' | 'startup';
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
  code?: string | null;
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

function readApiError(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null) {
    if ('error' in payload) {
      const error = (payload as ApiErrorBody).error;
      if (typeof error === 'string' && error.trim()) return error;
    }
    if ('detail' in payload) {
      if (typeof payload.detail === 'string' && payload.detail.trim()) return payload.detail;
      if (Array.isArray(payload.detail)) {
        const firstError = payload.detail.find((item) => (
          typeof item === 'object' && item !== null && 'msg' in item && typeof item.msg === 'string'
        ));
        if (firstError && 'msg' in firstError) return firstError.msg as string;
      }
    }
  }
  return fallback;
}

export function createApiClient(
  baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://10.193.155.238:8000/api',
) {
  const base = baseUrl.replace(/\/$/, '');

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
        : response.status === 422
          ? 'Проверьте введённые данные.'
          : response.status >= 500
            ? 'Сервис временно недоступен. Попробуйте позже.'
            : 'Не удалось выполнить запрос.';
      throw new ApiError(readApiError(payload, fallback), response.status);
    }

    return payload as T;
  }

  return {
    sendSmsCode(phone: string) {
      return request<SmsSendResponse>('/auth/sms/send', {
        method: 'POST',
        body: { phone },
      });
    },
    createSession(phone: string, code: string) {
      return request<AuthSession>('/auth/session', {
        method: 'POST',
        body: { phone, code },
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
    async getApplications(token: string) {
      const response = await request<{ applications: ApplicationCard[] }>('/applications', { token });
      return response.applications;
    },
    getApplicationDetail(token: string, applicationId: string) {
      return request<ApplicationDetail>(`/applications/${encodeURIComponent(applicationId)}`, { token });
    },
    createApplication(token: string, application: ApplicationCreateRequest) {
      return request<ApplicationCard>('/applications', { method: 'POST', token, body: application });
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
    async getDashboardData(token: string): Promise<Cabinet> {
      const [user, products, applications, credits] = await Promise.all([
        this.getCurrentUser(token),
        this.getProducts(),
        this.getApplications(token),
        this.getCredits(token),
      ]);
      return { user, products, applications, credits };
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
