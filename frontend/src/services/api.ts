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
  getStats:     ()                  => api.get('/dashboard/stats').then(d),
  getClassStats:(classId: string)   => api.get(`/classes/${classId}/stats`).then(d),
};

// ---------------------------------------------------------------------------
// Disciplines (a.k.a. "classes" in backend URL prefix for courses/stats)
// ---------------------------------------------------------------------------
export const disciplinesApi = {
  list:             ()                                          => api.get('/disciplines').then(d),
  get:              (id: string)                                => api.get(`/disciplines/${id}`).then(d),
  create:           (data: Record<string, unknown>)             => api.post('/disciplines', data).then(d),
  update:           (id: string, data: Record<string, unknown>) => api.put(`/disciplines/${id}`, data).then(d),
  getStats:         (id: string)                                => api.get(`/classes/${id}/stats`).then(d),
  getStudentsStats: (id: string)                                => api.get(`/disciplines/${id}/students/stats`).then(d),
  uploadImage:      (id: string, file: File)                    => upload(`/disciplines/${id}/image`, file, 'file'),
  // Teachers
  getTeachers:      (id: string)                                => api.get(`/disciplines/${id}/teachers`).then(d),
  addTeacher:       (id: string, teacherId: string)             => api.post(`/disciplines/${id}/teachers`, { teacher_id: teacherId }).then(d),
  removeTeacher:    (id: string, teacherId: string)             => api.delete(`/disciplines/${id}/teachers/${teacherId}`).then(d),
  // Students
  getStudents:      (id: string)                                => api.get(`/disciplines/${id}/students`).then(d),
  addStudent:       (id: string, studentId: string)             => api.post(`/disciplines/${id}/students`, { student_id: studentId }).then(d),
  removeStudent:    (id: string, studentId: string)             => api.delete(`/disciplines/${id}/students/${studentId}`).then(d),
  addStudentsBatch: (id: string, studentIds: string[])          => api.post(`/disciplines/${id}/students/batch`, { student_ids: studentIds }).then(d),
  // Sessions (review flow)
  getSessions:      (id: string, status?: string)               => api.get(`/disciplines/${id}/sessions`, { params: status ? { status } : undefined }).then(d),
};

// ---------------------------------------------------------------------------
// Courses
// ---------------------------------------------------------------------------
export const coursesApi = {
  list:        (params?: Record<string, unknown>)         => api.get('/courses', { params }).then(d),
  get:         (id: string)                                => api.get(`/courses/${id}`).then(d),
  create:      (data: Record<string, unknown>)             => api.post('/courses', data).then(d),
  update:      (id: string, data: Record<string, unknown>) => api.put(`/courses/${id}`, data).then(d),
  delete:      (id: string)                                => api.delete(`/courses/${id}`).then(d),
  export:      (id: string)                                => api.get(`/courses/${id}/export`).then(d),
  uploadImage: (id: string, file: File)                    => upload(`/courses/${id}/image`, file, 'file'),
  listByClass: (classId: string)                           => api.get(`/classes/${classId}/courses`).then(d),
  createInClass: (classId: string, data: Record<string, unknown>) => api.post(`/classes/${classId}/courses`, data).then(d),
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
  create:     (chapterId: string, data: Record<string, unknown>) => api.post(`/chapters/${chapterId}/contents`, data).then(d),
  update:     (id: string, data: Record<string, unknown>)   => api.put(`/contents/${id}`, data).then(d),
  delete:     (id: string)                                  => api.delete(`/contents/${id}`).then(d),
  uploadFile: (chapterId: string, file: File, onProgress?: (pct: number) => void) =>
    upload(`/chapters/${chapterId}/upload`, file, 'file', undefined, onProgress),
};

// ---------------------------------------------------------------------------
// Questions
// ---------------------------------------------------------------------------
export const questionsApi = {
  list:        (contentId: string)                          => api.get(`/contents/${contentId}/questions`).then(d),
  create:      (contentId: string, items: Record<string, unknown>[]) => api.post(`/contents/${contentId}/questions`, { items }).then(d),
  update:      (id: string, data: Record<string, unknown>)  => api.put(`/questions/${id}`, data).then(d),
  delete:      (id: string)                                 => api.delete(`/questions/${id}`).then(d),
  updateBatch: (contentId: string, items: Record<string, unknown>[]) => api.put(`/contents/${contentId}/questions/batch`, { items }).then(d),
};

// ---------------------------------------------------------------------------
// Upload (avatars / discipline images handled by specific endpoints above)
// ---------------------------------------------------------------------------
export const uploadApi = {
  upload: (file: File, type: string, onProgress?: (pct: number) => void) =>
    upload('/upload', file, 'file', { type }, onProgress),
};

// ---------------------------------------------------------------------------
// AI — 6 agents (Creator, Socrates, Analyst, Editor, Tester, Organizer)
// ---------------------------------------------------------------------------
export const aiApi = {
  getStatus:         ()                                                   => api.get('/api/ai/status').then(d),
  generateQuestions: (data: Record<string, unknown>)                      => api.post('/api/ai/creator/generate', data).then(d),
  suggestChapters:   (data: Record<string, unknown>)                      => api.post('/api/ai/creator/suggest-chapters', data).then(d),
  socraticDialogue:  (data: Record<string, unknown>)                      => api.post('/api/ai/socrates/dialogue', data).then(d),
  detectAI:          (data: Record<string, unknown>)                      => api.post('/api/ai/analyst/detect', data).then(d),
  editResponse:      (data: Record<string, unknown>)                      => api.post('/api/ai/editor/edit', data).then(d),
  validateResponse:  (data: Record<string, unknown>)                      => api.post('/api/ai/tester/validate', data).then(d),
  organizeSession:   (data: Record<string, unknown>)                      => api.post('/api/ai/organizer/session', data).then(d),
  prepareExport:     (data: Record<string, unknown>)                      => api.post('/api/ai/organizer/prepare-export', data).then(d),
  estimateCost:      (prompt: number, completion: number, model?: string) => api.get('/api/ai/estimate-cost', { params: { prompt_tokens: prompt, completion_tokens: completion, model } }).then(d),
  transcribe:        (file: File)                                         => upload('/api/ai/transcribe', file, 'file'),
};

// ---------------------------------------------------------------------------
// TTS
// ---------------------------------------------------------------------------
export const ttsApi = {
  getStatus: ()                                                => api.get('/api/ai/tts/status').then(d),
  listVoices:()                                                => api.get('/api/ai/tts/voices').then(d),
  generate:  (text: string, voice = 'alloy')                   => api.post('/api/ai/tts/generate', null, { params: { text, voice } }).then(d),
};

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------
export const usersApi = {
  list:         (params?: Record<string, unknown>) => api.get('/users', { params }).then(d),
  get:          (id: string)                       => api.get(`/users/${id}`).then(d),
  create:       (data: Record<string, unknown>)    => api.post('/users', data).then(d),
  createBatch:  (users: Record<string, unknown>[]) => api.post('/users/batch', users).then(d),
  update:       (id: string, data: Record<string, unknown>) => api.put(`/users/${id}`, data).then(d),
  uploadAvatar: (id: string, file: File) => upload(`/users/${id}/avatar`, file, 'file'),
};

// ---------------------------------------------------------------------------
// Admin
// ---------------------------------------------------------------------------
export const adminApi = {
  getStats:        ()                                         => api.get('/admin/stats').then(d),
  getSettings:     ()                                         => api.get('/admin/settings').then(d),
  updateSettings:  (data: Record<string, unknown>)            => api.post('/admin/settings', data).then(d),
  getLogs:         (params?: Record<string, unknown>)         => api.get('/admin/logs', { params }).then(d),
  searchLogs:      (query: string, type?: string)             => api.get('/admin/logs/search', { params: { q: query, log_type: type } }).then(d),
  uploadLogo:      (file: File)                               => upload('/admin/settings/upload-logo', file, 'file'),
  uploadLoginLogo: (file: File)                               => upload('/admin/settings/upload-login-logo', file, 'file'),
  uploadLoginBg:   (file: File)                               => upload('/admin/settings/upload-login-bg', file, 'file'),
  getPerformance:  ()                                         => api.get('/admin/performance').then(d),
  getStorageStats: ()                                         => api.get('/admin/storage').then(d),
  listBackups:     ()                                         => api.get('/admin/backups').then(d),
  createBackup:    ()                                         => api.post('/admin/backups').then(d),
  downloadBackup:  (id: string)                               => api.get(`/admin/backups/${id}/download`, { responseType: 'blob' }).then(d),
  deleteBackup:    (id: string)                               => api.delete(`/admin/backups/${id}`).then(d),
  forceLogoutAll:  ()                                         => api.post('/admin/force-logout').then(d),
  clearCache:      ()                                         => api.post('/admin/clear-cache').then(d),
  exportLogs:      (fmt: string)                              => api.get('/admin/logs/export', { params: { fmt }, responseType: 'blob' }).then(d),
};

// ---------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------
export const notificationsApi = {
  list:        (userId: string)                    => api.get(`/users/${userId}/notifications`).then(d),
  count:       (userId: string)                    => api.get(`/users/${userId}/notifications/count`).then(d),
  create:      (data: Record<string, unknown>)     => api.post('/notifications', data).then(d),
  markRead:    (id: string)                        => api.put(`/notifications/${id}/read`).then(d),
  markAllRead: (userId: string)                    => api.put(`/notifications/${userId}/read-all`).then(d),
  delete:      (id: string)                        => api.delete(`/notifications/${id}`).then(d),
};

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
export const searchApi = {
  search: (query: string) => api.get('/search', { params: { q: query } }).then(d),
};

// ---------------------------------------------------------------------------
// User Stats / Gamification
// ---------------------------------------------------------------------------
export const userStatsApi = {
  getStats:        (userId: string)                                         => api.get(`/users/${userId}/stats`).then(d),
  getActivities:   (userId: string, params?: Record<string, unknown>)       => api.get(`/users/${userId}/activities`, { params }).then(d),
  createActivity:  (userId: string, data: Record<string, unknown>)          => api.post(`/users/${userId}/activities`, data).then(d),
  getAchievements: (userId: string)                                         => api.get(`/users/${userId}/achievements`).then(d),
  unlockAchievement: (userId: string, achievementId: string)                => api.post(`/users/${userId}/achievements/${achievementId}/unlock`).then(d),
  getCertificates: (userId: string)                                         => api.get(`/users/${userId}/certificates`).then(d),
  issueCertificate:(userId: string, courseId: string)                       => api.post(`/users/${userId}/certificates`, { course_id: courseId }).then(d),
  getCourseProgress:(userId: string, courseId: string)                      => api.get(`/users/${userId}/courses/${courseId}/progress`).then(d),
  completeContent: (userId: string, courseId: string, contentId: string)    => api.post(`/users/${userId}/courses/${courseId}/complete-content/${contentId}`).then(d),
};

// ---------------------------------------------------------------------------
// Chat Sessions
// ---------------------------------------------------------------------------
export const chatSessionsApi = {
  createOrGet:  (data: Record<string, unknown>)                   => api.post('/chat-sessions', data).then(d),
  get:          (sessionId: string)                               => api.get(`/chat-sessions/${sessionId}`).then(d),
  byContent:    (contentId: string)                               => api.get(`/chat-sessions/by-content/${contentId}`).then(d),
  byUser:       (userId: string)                                  => api.get(`/users/${userId}/chat-sessions`).then(d),
  getMessages:  (sessionId: string)                               => api.get(`/chat-sessions/${sessionId}/messages`).then(d),
  addMessage:   (sessionId: string, data: Record<string, unknown>) => api.post(`/chat-sessions/${sessionId}/messages`, data).then(d),
  complete:     (sessionId: string)                               => api.put(`/chat-sessions/${sessionId}/complete`).then(d),
  exportMoodle: (sessionId: string)                               => api.post(`/chat-sessions/${sessionId}/export-moodle`).then(d),
};

// ---------------------------------------------------------------------------
// Session Reviews (professor ↔ aluno feedback on chat sessions)
// ---------------------------------------------------------------------------
export const sessionReviewsApi = {
  get:    (sessionId: string)                                          => api.get(`/chat-sessions/${sessionId}/review`).then(d),
  create: (sessionId: string, data: Record<string, unknown>)           => api.post(`/chat-sessions/${sessionId}/review`, data).then(d),
  update: (sessionId: string, data: Record<string, unknown>)           => api.put(`/chat-sessions/${sessionId}/review`, data).then(d),
  reply:  (sessionId: string, reply: string)                           => api.post(`/chat-sessions/${sessionId}/review/reply`, { reply }).then(d),
};

// ---------------------------------------------------------------------------
// Integrations
// ---------------------------------------------------------------------------
export const integrationsApi = {
  getStatus:         ()                                              => api.get('/integrations/status').then(d),
  testConnection:    (system: string)                                => api.post('/integrations/test-connection', null, { params: { system } }).then(d),
  getLogs:           (params?: Record<string, unknown>)              => api.get('/integrations/logs', { params }).then(d),
  getMappings:       (entityType?: string)                           => api.get('/integrations/mappings', { params: entityType ? { entity_type: entityType } : undefined }).then(d),
  // JACAD
  jacadSync:         ()                                              => api.post('/integrations/jacad/sync').then(d),
  jacadImportStudents:()                                             => api.post('/integrations/jacad/import-students').then(d),
  jacadImportDisciplines:()                                          => api.post('/integrations/jacad/import-disciplines').then(d),
  jacadGetStudent:   (ra: string)                                    => api.get(`/integrations/jacad/student/${ra}`).then(d),
  // Moodle
  moodleSync:        ()                                              => api.post('/integrations/moodle/sync').then(d),
  moodleExportSessions:(filters?: Record<string, unknown>)           => api.post('/integrations/moodle/export-sessions', filters ?? {}).then(d),
  moodleGetRatings:  (sessionId?: string)                            => api.get('/integrations/moodle/ratings', { params: sessionId ? { session_id: sessionId } : undefined }).then(d),
};

// ---------------------------------------------------------------------------
// Default export (raw instance for edge cases)
// ---------------------------------------------------------------------------
export default api;
