
export interface TelegramTopicSettings {
  telegram_topics_enabled: boolean;
  telegram_topics_chat_id: string;
  telegram_topics_auto_create: boolean;
  telegram_topics_recreate_deleted: boolean;
  telegram_topics_fallback_to_main_chat: boolean;
}

export interface MonitorTopicStatus {
  exists: boolean;
  message_thread_id?: string;
  topic_name?: string;
  status: "active" | "deleted" | "error" | "not_created" | "creating";
  last_error?: string;
}

export const getTelegramTopicSettings = async (): Promise<TelegramTopicSettings> => {
  const response = await fetch("/api/v1/settings/telegram/topics", { cache: "no-store" });
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

export const getMonitorTopicStatus = async (monitorId: number): Promise<MonitorTopicStatus> => {
    const response = await fetch(`/api/v1/monitors/${monitorId}/telegram-topic`, { cache: "no-store" });
    if (!response.ok) throw new Error("Failed to fetch monitor topic status");
    return response.json();
};

export const ensureMonitorTopic = async (monitorId: number, csrfToken: string): Promise<MonitorTopicStatus> => {
    const response = await fetch(`/api/v1/monitors/${monitorId}/telegram-topic/ensure`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
    });
    if (!response.ok) throw new Error("Failed to ensure monitor topic");
    return response.json();
};

export const testMonitorTopic = async (monitorId: number, csrfToken: string): Promise<{ success: boolean; message: string }> => {
    const response = await fetch(`/api/v1/monitors/${monitorId}/telegram-topic/test`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
    });
    if (!response.ok) throw new Error("Failed to test monitor topic");
    return response.json();
};
