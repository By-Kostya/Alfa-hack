export type ApiErrorBody = {
  error?: string;
};

export type AuthSession = {
  token: string;
  user: {
    id: string;
    phone: string;
  };
};

export type ApplicationCard = {
  id: string;
  status: string;
  product: string;
  purpose: string;
  loan_amount_rub: number;
  loan_term_months: number;
  created_at: string;
  limit_rub: number | null;
  monthly_payment_rub: number | null;
  decision: 'approve' | 'reduced' | 'reject' | 'unknown' | null;
};

export type CreditCard = {
  id: string;
  product: string;
  status: string;
  amount_rub: number;
  loan_term_months: number;
  monthly_payment_rub: number;
  purpose: string;
  created_at: string;
};

export type Cabinet = {
  user: {
    id: string;
    phone: string;
  };
  products: Array<{
    code: string;
    title: string;
  }>;
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

const MOCK_SMS_CODE = '0000';
const pendingMockSms = new Set<string>();

function readApiError(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null) {
    if ('error' in payload) {
      const error = (payload as ApiErrorBody).error;
      if (typeof error === 'string' && error.trim()) return error;
    }
    if ('detail' in payload && typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail;
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
          ? 'Проверьте номер телефона.'
          : response.status >= 500
            ? 'Сервис временно недоступен. Попробуйте позже.'
            : 'Не удалось выполнить запрос.';
      throw new ApiError(readApiError(payload, fallback), response.status);
    }

    return payload as T;
  }

  return {
    requestMockSmsCode(phone: string) {
      pendingMockSms.add(phone);
    },
    verifyMockSmsCode(phone: string, code: string) {
      return pendingMockSms.has(phone) && code === MOCK_SMS_CODE;
    },
    createSession(phone: string) {
      return request<AuthSession>('/auth/session', {
        method: 'POST',
        body: { phone },
      });
    },
    getCabinet(token: string) {
      return request<Cabinet>('/cabinet', { token });
    },
    deleteSession(token: string) {
      return request<void>('/auth/session', { method: 'DELETE', token });
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
