import axios from 'axios';

// ---------------------------------------------------------------------------
// Axios instance
// ---------------------------------------------------------------------------
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  headers: { 'Content-Type': 'application/json' },
});

// ---------------------------------------------------------------------------
// Request interceptor — attach Bearer token
// ---------------------------------------------------------------------------
api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('harven-access-token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// ---------------------------------------------------------------------------
// Response interceptor — handle 401
// ---------------------------------------------------------------------------
api.interceptors.response.use(
  (res) => res,
  (error) => {
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      sessionStorage.clear();
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const d = <T>(r: { data: T }) => r.data;

const upload = (
  url: string,
  file: File,
  fieldName = 'file',
  extra?: Record<string, string>,
  onProgress?: (pct: number) => void,
) => {
  const fd = new FormData();
  fd.append(fieldName, file);
  if (extra) Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  return api
    .post(url, fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress
        ? (e) => onProgress(Math.round(((e.loaded ?? 0) * 100) / (e.total ?? 1)))
        : undefined,
    })
    .then(d);
};

// ---------------------------------------------------------------------------
// Public
// ---------------------------------------------------------------------------
export const publicApi = {
  getSettings: () => api.get('/settings/public').then(d),
};

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export const authApi = {
  login: (ra: string, password: string) =>
    api.post<{ access_token: string; user: unknown }>('/auth/login', { ra, password }).then(d),
};

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
export const dashboardApi = {
  getStats: (userId: string) => api.get(`/dashboard/stats/${userId}`).then(d),
};

// ---------------------------------------------------------------------------
// Disciplines
// ---------------------------------------------------------------------------
export const disciplinesApi = {
  list:             ()                                          => api.get('/disciplines').then(d),
  get:              (id: string)                                => api.get(`/disciplines/${id}`).then(d),
  create:           (data: Record<string, unknown>)             => api.post('/disciplines', data).then(d),
  update:           (id: string, data: Record<string, unknown>) => api.put(`/disciplines/${id}`, data).then(d),
  delete:           (id: string)                                => api.delete(`/disciplines/${id}`).then(d),
  getStats:         (id: string)                                => api.get(`/disciplines/${id}/stats`).then(d),
  getStudents:      (id: string)                                => api.get(`/disciplines/${id}/students`).then(d),
  getStudentsStats: (id: string)                                => api.get(`/disciplines/${id}/students/stats`).then(d),
  getTeachers:      (id: string)                                => api.get(`/disciplines/${id}/teachers`).then(d),
  addTeacher:       (id: string, userId: string)                => api.post(`/disciplines/${id}/teachers`, { user_id: userId }).then(d),
  removeTeacher:    (id: string, userId: string)                => api.delete(`/disciplines/${id}/teachers/${userId}`).then(d),
  addStudent:       (id: string, userId: string)                => api.post(`/disciplines/${id}/students`, { user_id: userId }).then(d),
  removeStudent:    (id: string, userId: string)                => api.delete(`/disciplines/${id}/students/${userId}`).then(d),
  addStudentsBatch: (id: string, students: Record<string, unknown>[]) =>
    api.post(`/disciplines/${id}/students/batch`, { students }).then(d),
};

// ---------------------------------------------------------------------------
// Courses
// ---------------------------------------------------------------------------
export const coursesApi = {
  list:        ()                                          => api.get('/courses').then(d),
  get:         (id: string)                                => api.get(`/courses/${id}`).then(d),
  create:      (data: Record<string, unknown>)             => api.post('/courses', data).then(d),
  update:      (id: string, data: Record<string, unknown>) => api.put(`/courses/${id}`, data).then(d),
  delete:      (id: string)                                => api.delete(`/courses/${id}`).then(d),
  listByClass: (classId: string)                           => api.get(`/disciplines/${classId}/courses`).then(d),
};

// ---------------------------------------------------------------------------
// Chapters
// ---------------------------------------------------------------------------
export const chaptersApi = {
  list:   (courseId: string)                                => api.get(`/courses/${courseId}/chapters`).then(d),
  create: (courseId: string, data: Record<string, unknown>) => api.post(`/courses/${courseId}/chapters`, data).then(d),
  update: (id: string, data: Record<string, unknown>)       => api.put(`/chapters/${id}`, data).then(d),
  delete: (id: string)                                      => api.delete(`/chapters/${id}`).then(d),
};

// ---------------------------------------------------------------------------
// Contents
// ---------------------------------------------------------------------------
export const contentsApi = {
  list:       (chapterId: string)                           => api.get(`/chapters/${chapterId}/contents`).then(d),
  get:        (id: string)                                  => api.get(`/contents/${id}`).then(d),
  create:     (data: Record<string, unknown>)               => api.post('/contents', data).then(d),
  update:     (id: string, data: Record<string, unknown>)   => api.put(`/contents/${id}`, data).then(d),
  delete:     (id: string)                                  => api.delete(`/contents/${id}`).then(d),
  uploadFile: (chapterId: string, file: File, onProgress?: (pct: number) => void) =>
    upload(`/chapters/${chapterId}/contents/upload`, file, 'file', undefined, onProgress),
};

// ---------------------------------------------------------------------------
// Questions
// ---------------------------------------------------------------------------
export const questionsApi = {
  list:        (contentId: string)                          => api.get(`/contents/${contentId}/questions`).then(d),
  create:      (data: Record<string, unknown>)              => api.post('/questions', data).then(d),
  update:      (id: string, data: Record<string, unknown>)  => api.put(`/questions/${id}`, data).then(d),
  delete:      (id: string)                                 => api.delete(`/questions/${id}`).then(d),
  updateBatch: (questions: Record<string, unknown>[])       => api.put('/questions/batch', { questions }).then(d),
};

// ---------------------------------------------------------------------------
// Upload (generic)
// ---------------------------------------------------------------------------
export const uploadApi = {
  upload: (file: File, type: string, onProgress?: (pct: number) => void) =>
    upload('/upload', file, 'file', { type }, onProgress),
};

// ---------------------------------------------------------------------------
// AI
// ---------------------------------------------------------------------------
export const aiApi = {
  getStatus:         ()                                    => api.get('/ai/status').then(d),
  generateQuestions: (contentId: string)                   => api.post('/ai/generate-questions', { content_id: contentId }).then(d),
  socraticDialogue:  (sessionId: string, message: string) => api.post('/ai/socratic', { session_id: sessionId, message }).then(d),
  detectAI:          (text: string)                        => api.post('/ai/detect', { text }).then(d),
  generateSummary:   (contentId: string, style: string)   => api.post('/ai/summary', { content_id: contentId, style }).then(d),
  transcribe:        (contentId: string)                   => api.post('/ai/transcribe', { content_id: contentId }).then(d),
};

// ---------------------------------------------------------------------------
// TTS
// ---------------------------------------------------------------------------
export const ttsApi = {
  generateSummary: (contentId: string, style: string) =>
    api.post('/tts/summary', { content_id: contentId, style }).then(d),
  transcribe: (contentId: string) =>
    api.post('/tts/transcribe', { content_id: contentId }).then(d),
};

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
export const usersApi = {
  list:         (params?: Record<string, unknown>) => api.get('/users', { params }).then(d),
  get:          (id: string)                       => api.get(`/users/${id}`).then(d),
  create:       (data: Record<string, unknown>)    => api.post('/users', data).then(d),
  createBatch:  (users: Record<string, unknown>[]) => api.post('/users/batch', { users }).then(d),
  update:       (id: string, data: Record<string, unknown>) => api.put(`/users/${id}`, data).then(d),
  uploadAvatar: (id: string, file: File) => upload(`/users/${id}/avatar`, file, 'avatar'),
};

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------
export const adminApi = {
  getStats:        ()                                         => api.get('/admin/stats').then(d),
  getSettings:     ()                                         => api.get('/admin/settings').then(d),
  updateSettings:  (data: Record<string, unknown>)            => api.put('/admin/settings', data).then(d),
  getLogs:         (params?: Record<string, unknown>)         => api.get('/admin/logs', { params }).then(d),
  searchLogs:      (query: string, type?: string)             => api.get('/admin/logs/search', { params: { query, type } }).then(d),
  uploadLogo:      (file: File)                               => upload('/admin/branding/logo', file, 'logo'),
  uploadLoginLogo: (file: File)                               => upload('/admin/branding/login-logo', file, 'logo'),
  uploadLoginBg:   (file: File)                               => upload('/admin/branding/login-bg', file, 'bg'),
  getPerformance:  ()                                         => api.get('/admin/performance').then(d),
  getStorageStats: ()                                         => api.get('/admin/storage').then(d),
  listBackups:     ()                                         => api.get('/admin/backups').then(d),
  createBackup:    ()                                         => api.post('/admin/backups').then(d),
  downloadBackup:  (id: string)                               => api.get(`/admin/backups/${id}/download`, { responseType: 'blob' }).then(d),
  deleteBackup:    (id: string)                               => api.delete(`/admin/backups/${id}`).then(d),
  forceLogoutAll:  ()                                         => api.post('/admin/force-logout').then(d),
  clearCache:      ()                                         => api.post('/admin/cache/clear').then(d),
  exportLogs:      (format: string)                           => api.get('/admin/logs/export', { params: { format }, responseType: 'blob' }).then(d),
  createAction:    (data: Record<string, unknown>)            => api.post('/admin/actions', data).then(d),
};

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------
export const notificationsApi = {
  list:        (userId: string) => api.get(`/users/${userId}/notifications`).then(d),
  markRead:    (id: string)     => api.put(`/notifications/${id}/read`).then(d),
  markAllRead: (userId: string) => api.put(`/users/${userId}/notifications/read-all`).then(d),
};

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
export const searchApi = {
  search: (query: string) => api.get('/search', { params: { q: query } }).then(d),
};

// ---------------------------------------------------------------------------
// User Stats
// ---------------------------------------------------------------------------
export const userStatsApi = {
  getStats:        (userId: string) => api.get(`/users/${userId}/stats`).then(d),
  getActivities:   (userId: string) => api.get(`/users/${userId}/activities`).then(d),
  getAchievements: (userId: string) => api.get(`/users/${userId}/achievements`).then(d),
  getCertificates: (userId: string) => api.get(`/users/${userId}/certificates`).then(d),
};

// ---------------------------------------------------------------------------
// Chat Sessions
// ---------------------------------------------------------------------------
export const chatSessionsApi = {
  createOrGet: (params: Record<string, unknown>)               => api.post('/chat-sessions', params).then(d),
  getMessages: (sessionId: string)                             => api.get(`/chat-sessions/${sessionId}/messages`).then(d),
  addMessage:  (sessionId: string, data: Record<string, unknown>) => api.post(`/chat-sessions/${sessionId}/messages`, data).then(d),
  complete:    (sessionId: string)                             => api.post(`/chat-sessions/${sessionId}/complete`).then(d),
};

// ---------------------------------------------------------------------------
// Session Reviews
// ---------------------------------------------------------------------------
export const sessionReviewsApi = {
  list:             (sessionId: string)                          => api.get(`/chat-sessions/${sessionId}/reviews`).then(d),
  create:           (data: Record<string, unknown>)              => api.post('/session-reviews', data).then(d),
  update:           (id: string, data: Record<string, unknown>)  => api.put(`/session-reviews/${id}`, data).then(d),
  listByDiscipline: (disciplineId: string)                       => api.get(`/disciplines/${disciplineId}/session-reviews`).then(d),
};

// ---------------------------------------------------------------------------
// Default export (raw instance for edge cases)
// ---------------------------------------------------------------------------
export default api;
