import { toast } from 'sonner';

interface ApiErrorResponse {
  response?: {
    data?: {
      error?: string;
      message?: string;
    };
  };
  message?: string;
}

/**
 * Trata erros de API exibindo toast e logando no console.
 */
export function handleApiError(error: ApiErrorResponse, context: string): void {
  const msg =
    error?.response?.data?.error ||
    error?.response?.data?.message ||
    error?.message ||
    'Erro desconhecido';

  toast.error(`${context}: ${msg}`);
  console.error(`[${context}]`, error);
}
