
export interface TelegramTopicSettings {
  enabled: boolean;
  telegram_topics_enabled?: boolean;
  chat_id?: string;
  auto_create: boolean;
  recreate_deleted: boolean;
  fallback_to_main_chat: boolean;
}

export interface MonitorTopicStatus {
  monitor_id?: number;
  message_thread_id_masked?: string | null;
  topic_name?: string;
  status: string;
  last_error?: string | null;
  last_error_code?: string | null;
  last_verified_at?: string | null;
  updated_at?: string | null;
}

export interface MonitorTopicBatchResponse {
  topics_enabled: boolean;
  topics: Record<string, MonitorTopicStatus>;
}

interface TopicEnvelope {
  ok?: boolean;
  code?: string;
  message?: string;
  monitor_id?: number;
  enabled?: boolean;
  topic?: MonitorTopicStatus | null;
}

export const getTelegramTopicSettings = async (signal?: AbortSignal): Promise<TelegramTopicSettings> => {
  const response = await fetch("/api/v1/settings/telegram/topics", { cache: "no-store", signal });
  if (!response.ok) throw new Error("Failed to fetch Telegram topic settings");
  return response.json();
};

export const patchTelegramTopicSettings = async (settings: Partial<TelegramTopicSettings>, csrfToken: string): Promise<TelegramTopicSettings> => {
  const response = await fetch("/api/v1/settings/telegram/topics", {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(settings),
  });
  if (!response.ok) throw new Error("Failed to update Telegram topic settings");
  return response.json();
};

export const verifyTelegramTopicGroup = async (chatId: string, csrfToken: string): Promise<{ success: boolean; message: string }> => {
  const response = await fetch("/api/v1/settings/telegram/topics/verify-group", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ chat_id: chatId }),
  });
  if (!response.ok) {
    const errorData = await response.json();
    throw new Error(errorData.detail || "Verification failed");
  }
  return response.json();
};

export const getMonitorTopicBatch = async (signal?: AbortSignal): Promise<MonitorTopicBatchResponse> => {
    const response = await fetch("/api/v1/monitors/telegram-topics", { cache: "no-store", signal });
    if (!response.ok) throw new Error("Failed to fetch monitor topic statuses");
    return response.json();
};

export const getMonitorTopicStatus = async (monitorId: number, signal?: AbortSignal): Promise<MonitorTopicStatus | null> => {
    const response = await fetch(`/api/v1/monitors/${monitorId}/telegram-topic`, { cache: "no-store", signal });
    if (!response.ok) throw new Error("Failed to fetch monitor topic status");
    const data = (await response.json()) as TopicEnvelope;
    return data.topic ? { ...data.topic, monitor_id: data.monitor_id } : null;
};

export const ensureMonitorTopic = async (monitorId: number, csrfToken: string): Promise<MonitorTopicStatus | null> => {
    const response = await fetch(`/api/v1/monitors/${monitorId}/telegram-topic/ensure`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
    });
    const data = (await response.json()) as TopicEnvelope;
    if (!response.ok) throw new Error(data.message || "Failed to ensure monitor topic");
    return data.topic ? { ...data.topic, monitor_id: monitorId } : null;
};

export const testMonitorTopic = async (monitorId: number, csrfToken: string): Promise<TopicEnvelope> => {
    const response = await fetch(`/api/v1/monitors/${monitorId}/telegram-topic/test`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
    });
    const data = (await response.json()) as TopicEnvelope;
    if (!response.ok) throw new Error(data.message || "Failed to test monitor topic");
    return data;
};
